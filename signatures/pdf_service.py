"""
PDF Generation Service with Signature Integration
- Generates PDFs with all signatures embedded
- Supports multiple signatures in verification chain
- Includes audit trail
- Production-ready with error handling
"""

from io import BytesIO
from datetime import datetime
import base64
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle,
    PageBreak, KeepTogether
)
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY
from django.core.files.base import ContentFile
from django.utils import timezone
from .models import PIVerification, POVerification


class PDFSignatureService:
    """
    Service for generating PDFs with embedded signatures
    """

    # Color scheme
    COLORS = {
        'primary': colors.HexColor('#0ea5e9'),
        'success': colors.HexColor('#10b981'),
        'danger': colors.HexColor('#ef4444'),
        'header': colors.HexColor('#1a1a2e'),
        'light': colors.HexColor('#f1f5f9'),
        'border': colors.HexColor('#e2e8f0'),
    }

    def __init__(self, page_size=A4):
        self.page_size = page_size
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()

    def _setup_custom_styles(self):
        """Setup custom paragraph styles"""
        self.styles.add(ParagraphStyle(
            name='CustomHeading1',
            parent=self.styles['Heading1'],
            fontSize=18,
            textColor=self.COLORS['header'],
            spaceAfter=12,
            fontName='Helvetica-Bold'
        ))

        self.styles.add(ParagraphStyle(
            name='CustomHeading2',
            parent=self.styles['Heading2'],
            fontSize=14,
            textColor=self.COLORS['primary'],
            spaceAfter=10,
            fontName='Helvetica-Bold'
        ))

        self.styles.add(ParagraphStyle(
            name='SmallText',
            fontSize=9,
            textColor=colors.HexColor('#64748b'),
            spaceAfter=4
        ))

    def generate_pi_pdf(self, pi, include_verification_chain=True):
        """
        Generate PDF for Proforma Invoice with signatures
        """
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=self.page_size,
            rightMargin=0.5*inch,
            leftMargin=0.5*inch,
            topMargin=0.5*inch,
            bottomMargin=0.5*inch
        )

        # Build PDF elements
        elements = []

        # Header
        elements.append(self._build_header(f"Proforma Invoice - {pi.proforma_invoice_number}"))

        # PI Details
        elements.append(self._build_pi_details(pi))

        # Items Table
        if hasattr(pi, 'items') and pi.items.exists():
            elements.append(self._build_items_table(pi))

        # Verification Chain
        if include_verification_chain:
            verifications = PIVerification.objects.filter(pi=pi)
            # Check if there are any verified entries in JSON list or if any row is verified
            has_signatures = False
            for v in verifications:
                if v.status == 'VERIFIED' or (v.verifiers and any(ver.get('status') == 'VERIFIED' for ver in v.verifiers)):
                    has_signatures = True
                    break
            if has_signatures:
                elements.append(PageBreak())
                elements.append(self._build_verification_section(verifications))

        # Audit Trail
        elements.append(PageBreak())
        elements.append(self._build_audit_trail(pi, 'PI'))

        # Build PDF
        doc.build(elements)
        buffer.seek(0)
        return buffer

    def generate_po_pdf(self, po, include_verification_chain=True):
        """
        Generate PDF for Purchase Order with signatures
        """
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=self.page_size,
            rightMargin=0.5*inch,
            leftMargin=0.5*inch,
            topMargin=0.5*inch,
            bottomMargin=0.5*inch
        )

        elements = []

        # Header
        elements.append(self._build_header(f"Purchase Order - {po.po_number}"))

        # PO Details
        elements.append(self._build_po_details(po))

        # Items Table
        if hasattr(po, 'items') and po.items.exists():
            elements.append(self._build_items_table(po))

        # Verification Chain
        if include_verification_chain:
            verifications = POVerification.objects.filter(po=po)
            # Check if there are any verified entries in JSON list or if any row is verified
            has_signatures = False
            for v in verifications:
                if v.status == 'VERIFIED' or (v.verifiers and any(ver.get('status') == 'VERIFIED' for ver in v.verifiers)):
                    has_signatures = True
                    break
            if has_signatures:
                elements.append(PageBreak())
                elements.append(self._build_verification_section(verifications))

        # Audit Trail
        elements.append(PageBreak())
        elements.append(self._build_audit_trail(po, 'PO'))

        # Build PDF
        doc.build(elements)
        buffer.seek(0)
        return buffer

    def _build_header(self, title):
        """Build document header"""
        return Paragraph(
            f"<font size=18 color='{self.COLORS['header'].hexval()}' face='Helvetica-Bold'>"
            f"{title}</font>",
            self.styles['Normal']
        )

    def _build_pi_details(self, pi):
        """Build PI details section"""
        elements = []

        data = [
            ['PI Number:', pi.proforma_invoice_number or 'N/A'],
            ['Vendor:', getattr(pi, 'vendor__name', 'N/A') if hasattr(pi, 'vendor') else 'N/A'],
            ['Date:', pi.created_at.strftime('%d-%m-%Y') if pi.created_at else 'N/A'],
            ['Status:', 'SIGNED' if hasattr(pi, 'verifications') and pi.verifications.filter(status='VERIFIED').exists() else 'DRAFT'],
        ]

        table = Table(data, colWidths=[2*inch, 4*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), self.COLORS['light']),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 1, self.COLORS['border']),
        ]))

        elements.append(table)
        elements.append(Spacer(1, 0.3*inch))

        return elements[0] if elements else Spacer(1, 0)

    def _build_po_details(self, po):
        """Build PO details section"""
        elements = []

        data = [
            ['PO Number:', po.po_number or 'N/A'],
            ['Vendor:', getattr(po, 'vendor__name', 'N/A') if hasattr(po, 'vendor') else 'N/A'],
            ['Date:', po.created_at.strftime('%d-%m-%Y') if po.created_at else 'N/A'],
            ['Status:', 'SIGNED' if hasattr(po, 'verifications') and po.verifications.filter(status='VERIFIED').exists() else 'DRAFT'],
        ]

        table = Table(data, colWidths=[2*inch, 4*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), self.COLORS['light']),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 1, self.COLORS['border']),
        ]))

        elements.append(table)
        elements.append(Spacer(1, 0.3*inch))

        return elements[0] if elements else Spacer(1, 0)

    def _build_items_table(self, obj):
        """Build items table (PI or PO)"""
        elements = []

        elements.append(Paragraph(
            '<b style="color: #0ea5e9">Items</b>',
            self.styles['Heading2']
        ))

        # Get items based on object type
        items = []
        if hasattr(obj, 'pi_items'):
            items = list(obj.pi_items.all())
        elif hasattr(obj, 'po_items'):
            items = list(obj.po_items.all())
        elif hasattr(obj, 'items'):
            items = list(obj.items.all())

        if not items:
            elements.append(Paragraph('No items', self.styles['Normal']))
            return KeepTogether(elements)

        # Build table data
        data = [['Item', 'Description', 'Quantity', 'Unit Price', 'Total']]

        for i, item in enumerate(items, 1):
            qty = getattr(item, 'quantity', 0)
            price = getattr(item, 'unit_price', 0)
            total = qty * float(price) if price else 0

            data.append([
                str(i),
                getattr(item, 'description', 'N/A'),
                str(qty),
                f"${float(price):.2f}" if price else '$0.00',
                f"${float(total):.2f}"
            ])

        table = Table(data, colWidths=[0.8*inch, 2.5*inch, 1*inch, 1.2*inch, 1.2*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), self.COLORS['header']),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('ALIGN', (1, 1), (1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('TOPPADDING', (0, 0), (-1, 0), 8),
            ('GRID', (0, 0), (-1, -1), 1, self.COLORS['border']),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')])
        ]))

        elements.append(table)
        elements.append(Spacer(1, 0.3*inch))

        return KeepTogether(elements)

    def _build_verification_section(self, verifications):
        """
        Build verification/signature section with all signers
        """
        from django.contrib.auth import get_user_model
        from .models import UserSignature
        User = get_user_model()
        elements = []

        elements.append(Paragraph(
            '<b style="color: #10b981">✓ Verification & Signatures</b>',
            self.styles['Heading2']
        ))

        for verification in verifications:
            if verification.verifiers:
                position = 1
                for v in verification.verifiers:
                    if v.get('status') == 'VERIFIED':
                        try:
                            user = User.objects.get(id=v.get('user_id'))
                            signer_name = user.get_full_name()
                            signer_email = user.email
                            verified_at_str = v.get('verified_at')
                            if verified_at_str:
                                try:
                                    dt = datetime.fromisoformat(verified_at_str.replace('Z', '+00:00'))
                                    verified_at = dt.strftime('%d-%m-%Y %H:%M:%S')
                                except Exception:
                                    verified_at = verified_at_str
                            else:
                                verified_at = 'N/A'

                            info_data = [
                                [
                                    f'<b>{signer_name}</b><br/>{signer_email}',
                                    f'Position: {position}<br/>Signed: {verified_at}'
                                ]
                            ]

                            info_table = Table(info_data, colWidths=[3.5*inch, 2.5*inch])
                            info_table.setStyle(TableStyle([
                                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#e8f5e9')),
                                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                                ('FONTSIZE', (0, 0), (-1, -1), 9),
                                ('PADDING', (0, 0), (-1, -1), 8),
                                ('BORDER', (0, 0), (-1, -1), 1, self.COLORS['border']),
                            ]))
                            elements.append(info_table)

                            # Signature image
                            if v.get('signature_id'):
                                try:
                                    sig = UserSignature.objects.get(id=v.get('signature_id'))
                                    if sig.signature_file:
                                        sig_image = Image(
                                            sig.signature_file.path,
                                            width=2*inch,
                                            height=0.8*inch
                                        )
                                        sig_box = Table([[sig_image]], colWidths=[2*inch])
                                        sig_box.setStyle(TableStyle([
                                            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                                            ('PADDING', (0, 0), (-1, -1), 8),
                                            ('BORDER', (0, 0), (-1, -1), 1, self.COLORS['border']),
                                        ]))
                                        elements.append(sig_box)
                                except Exception as e:
                                    print(f'[PDF] Error embedding signature for verifier: {str(e)}')

                            # Notes
                            if verification.notes and position == 1:
                                elements.append(Paragraph(
                                    f'<font size=9><b>Notes:</b> {verification.notes}</font>',
                                    self.styles['Normal']
                                ))

                            elements.append(Spacer(1, 0.2*inch))
                            position += 1
                        except User.DoesNotExist:
                            pass
            else:
                if verification.status == 'VERIFIED':
                    elements.extend(self._build_signature_block(verification))

        return KeepTogether(elements)

    def _build_signature_block(self, verification):
        """Build individual signature block"""
        elements = []

        # Signer info box
        signer_name = verification.assigned_to.get_full_name()
        signer_email = verification.assigned_to.email
        verified_at = verification.verified_at.strftime('%d-%m-%Y %H:%M:%S') if verification.verified_at else 'N/A'

        info_data = [
            [
                f'<b>{signer_name}</b><br/>{signer_email}',
                f'Position: {verification.signature_position}<br/>Signed: {verified_at}'
            ]
        ]

        info_table = Table(info_data, colWidths=[3.5*inch, 2.5*inch])
        info_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#e8f5e9')),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('PADDING', (0, 0), (-1, -1), 8),
            ('BORDER', (0, 0), (-1, -1), 1, self.COLORS['border']),
        ]))
        elements.append(info_table)

        # Signature image
        if verification.signature and verification.signature.signature_file:
            try:
                sig_image = Image(
                    verification.signature.signature_file.path,
                    width=2*inch,
                    height=0.8*inch
                )
                sig_box = Table([[sig_image]], colWidths=[2*inch])
                sig_box.setStyle(TableStyle([
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ('PADDING', (0, 0), (-1, -1), 8),
                    ('BORDER', (0, 0), (-1, -1), 1, self.COLORS['border']),
                ]))
                elements.append(sig_box)
            except Exception as e:
                print(f'[PDF] Error embedding signature: {str(e)}')

        # Notes
        if verification.notes:
            elements.append(Paragraph(
                f'<font size=9><b>Notes:</b> {verification.notes}</font>',
                self.styles['Normal']
            ))

        elements.append(Spacer(1, 0.2*inch))

        return elements

    def _build_audit_trail(self, obj, doc_type):
        """
        Build complete audit trail
        """
        elements = []

        elements.append(Paragraph(
            '<b style="color: #1a1a2e">📋 Audit Trail</b>',
            self.styles['Heading2']
        ))

        # Get verifications
        if doc_type == 'PI':
            verifications = PIVerification.objects.filter(pi=obj)
        else:
            verifications = POVerification.objects.filter(po=obj)

        if not verifications.exists():
            elements.append(Paragraph('No verification history', self.styles['Normal']))
            return KeepTogether(elements)

        # Build audit data
        data = [['Action', 'User', 'Role', 'Timestamp', 'Status']]

        for v in verifications.order_by('created_at'):
            action = 'Created' if v.status == 'PENDING' else 'Verified' if v.status == 'VERIFIED' else 'Rejected'
            role = 'Document Creator' if v.created_by == v.assigned_to else 'Verifier'
            status_color = '#10b981' if v.status == 'VERIFIED' else '#ef4444' if v.status == 'REJECTED' else '#f59e0b'

            data.append([
                action,
                v.assigned_to.get_full_name() if v.assigned_to else v.created_by.get_full_name(),
                role,
                (v.verified_at or v.created_at).strftime('%d-%m-%Y %H:%M'),
                f'<font color="{status_color}"><b>{v.status}</b></font>'
            ])

        table = Table(data, colWidths=[1.2*inch, 1.8*inch, 1.2*inch, 1.3*inch, 1*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), self.COLORS['header']),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('PADDING', (0, 0), (-1, 0), 8),
            ('GRID', (0, 0), (-1, -1), 1, self.COLORS['border']),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')])
        ]))

        elements.append(table)

        # Footer
        elements.append(Spacer(1, 0.3*inch))
        elements.append(Paragraph(
            f'<font size=8 color="#94a3b8">Generated on {datetime.now().strftime("%d-%m-%Y %H:%M:%S")}</font>',
            self.styles['Normal']
        ))

        return KeepTogether(elements)
