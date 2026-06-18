"""
PDF Signature Overlay Service
- Add signatures to existing PDFs generated from frontend
- Overlay signatures at specific positions
- Add signature metadata and verification stamps
- Production-ready with error handling
"""

from io import BytesIO
from datetime import datetime
import base64
from PIL import Image
import PyPDF2
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from PyPDF2 import PdfReader, PdfWriter
from .models import PIVerification, POVerification


class PDFSignatureOverlay:
    """
    Service for overlaying signatures on existing PDFs
    """

    SIGNATURE_WIDTH = 1.5  # inches
    SIGNATURE_HEIGHT = 0.6  # inches

    def __init__(self):
        self.colors = {
            'primary': '#0ea5e9',
            'success': '#10b981',
            'header': '#1a1a2e',
        }

    def add_signatures_to_pdf(self, pdf_buffer, document_id, document_type='PI', signatures_data=None):
        """
        Add signatures and verification stamps to existing PDF

        Args:
            pdf_buffer: BytesIO buffer of existing PDF
            document_id: ID of PI or PO
            document_type: 'PI' or 'PO'
            signatures_data: Optional list of signature positions and data

        Returns:
            BytesIO buffer with signatures added
        """
        try:
            # Get verification data from database if not provided
            if signatures_data is None:
                signatures_data = self._get_verification_data(document_id, document_type)

            if not signatures_data:
                # No signatures to add, return original PDF
                pdf_buffer.seek(0)
                return pdf_buffer

            # Read original PDF
            reader = PdfReader(pdf_buffer)
            writer = PdfWriter()

            # Get last page to add signature block
            last_page_index = len(reader.pages) - 1

            # Create signature overlay
            signature_overlay = self._create_signature_overlay(signatures_data)

            # Merge signature overlay with last page
            last_page = reader.pages[last_page_index]
            signature_overlay_reader = PdfReader(signature_overlay)
            signature_overlay_page = signature_overlay_reader.pages[0]

            last_page.merge_page(signature_overlay_page)

            # Copy all pages to writer
            for page_num in range(len(reader.pages)):
                if page_num == last_page_index:
                    writer.add_page(last_page)
                else:
                    writer.add_page(reader.pages[page_num])

            # Add verification stamp to last page
            self._add_verification_stamp(writer.pages[-1], signatures_data)

            # Write to buffer
            output_buffer = BytesIO()
            writer.write(output_buffer)
            output_buffer.seek(0)

            return output_buffer

        except Exception as e:
            print(f'[PDFOverlay] Error adding signatures: {str(e)}')
            pdf_buffer.seek(0)
            return pdf_buffer

    def _get_verification_data(self, document_id, document_type):
        """
        Fetch verified signatures from database
        """
        from django.contrib.auth import get_user_model
        from .models import UserSignature
        User = get_user_model()
        try:
            if document_type == 'PI':
                verifications = PIVerification.objects.filter(
                    pi_id=document_id
                )
            else:
                verifications = POVerification.objects.filter(
                    po_id=document_id
                )

            signatures_data = []
            for v in verifications:
                if v.verifiers:
                    position = 1
                    for verifier in v.verifiers:
                        if verifier.get('status') == 'VERIFIED':
                            try:
                                user = User.objects.get(id=verifier.get('user_id'))
                                sig_file = None
                                if verifier.get('signature_id'):
                                    try:
                                        sig_obj = UserSignature.objects.get(id=verifier.get('signature_id'))
                                        sig_file = sig_obj.signature_file
                                    except UserSignature.DoesNotExist:
                                        pass
                                
                                signed_date = ''
                                verified_at_str = verifier.get('verified_at')
                                if verified_at_str:
                                    try:
                                        dt = datetime.fromisoformat(verified_at_str.replace('Z', '+00:00'))
                                        signed_date = dt.strftime('%d-%m-%Y %H:%M')
                                    except Exception:
                                        signed_date = verified_at_str
                                
                                role_display = 'Checked By' if verifier.get('role') == 'CHECKED_BY' else 'Authorized Signatory'
                                
                                signatures_data.append({
                                    'signer_name': user.get_full_name(),
                                    'signer_email': user.email,
                                    'signature_file': sig_file,
                                    'signed_date': signed_date,
                                    'position': position,
                                    'role': role_display,
                                    'notes': v.notes if position == 1 else ''
                                })
                                position += 1
                            except User.DoesNotExist:
                                pass
                else:
                    # Fallback if verifiers list is empty but verification is VERIFIED
                    if v.status == 'VERIFIED':
                        signatures_data.append({
                            'signer_name': v.assigned_to.get_full_name() if v.assigned_to else 'Unknown',
                            'signer_email': v.assigned_to.email if v.assigned_to else '',
                            'signature_file': v.signature.signature_file if v.signature else None,
                            'signed_date': v.verified_at.strftime('%d-%m-%Y %H:%M') if v.verified_at else '',
                            'position': v.signature_position,
                            'role': self._get_verifier_role(v),
                            'notes': v.notes or ''
                        })

            return signatures_data

        except Exception as e:
            print(f'[PDFOverlay] Error fetching verification data: {str(e)}')
            return []

    def _create_signature_overlay(self, signatures_data):
        """
        Create a signature overlay page with all signatures
        """
        try:
            buffer = BytesIO()
            c = canvas.Canvas(buffer, pagesize=A4)
            width, height = A4

            # Start from bottom
            y_position = height - 1 * inch

            for sig in signatures_data:
                # Signature block
                y_position = self._draw_signature_block(c, sig, y_position)

                if y_position < 1 * inch:
                    # Need new page
                    c.showPage()
                    y_position = height - 1 * inch

            c.save()
            buffer.seek(0)
            return buffer

        except Exception as e:
            print(f'[PDFOverlay] Error creating signature overlay: {str(e)}')
            return BytesIO()

    def _draw_signature_block(self, canvas_obj, sig_data, y_position):
        """
        Draw individual signature block
        """
        try:
            x_start = 0.5 * inch
            block_height = 1.5 * inch

            # Background box
            canvas_obj.setFillColor(colors.HexColor('#f0f9ff'))
            canvas_obj.rect(
                x_start, y_position - block_height,
                7 * inch, block_height,
                fill=1, stroke=0
            )

            # Border
            canvas_obj.setStrokeColor(colors.HexColor('#0ea5e9'))
            canvas_obj.setLineWidth(1)
            canvas_obj.rect(
                x_start, y_position - block_height,
                7 * inch, block_height,
                fill=0, stroke=1
            )

            # Signer info
            text_x = x_start + 0.2 * inch
            text_y = y_position - 0.3 * inch

            # Name
            canvas_obj.setFont('Helvetica-Bold', 10)
            canvas_obj.setFillColor(colors.HexColor('#1e293b'))
            canvas_obj.drawString(text_x, text_y, sig_data['signer_name'])

            # Role
            canvas_obj.setFont('Helvetica', 9)
            canvas_obj.setFillColor(colors.HexColor('#64748b'))
            role_text = f"({sig_data['role']})" if sig_data['role'] else ""
            canvas_obj.drawString(text_x + 2.5 * inch, text_y, role_text)

            # Email
            canvas_obj.setFont('Helvetica', 8)
            canvas_obj.setFillColor(colors.HexColor('#94a3b8'))
            canvas_obj.drawString(text_x, text_y - 0.2 * inch, sig_data['signer_email'])

            # Date
            canvas_obj.drawString(text_x + 2.5 * inch, text_y - 0.2 * inch, f"Signed: {sig_data['signed_date']}")

            # Draw signature image if available
            if sig_data['signature_file']:
                try:
                    sig_image = Image.open(sig_data['signature_file'])

                    # Resize signature
                    sig_image.thumbnail(
                        (int(self.SIGNATURE_WIDTH * 72), int(self.SIGNATURE_HEIGHT * 72)),
                        Image.Resampling.LANCZOS
                    )

                    # Save to buffer
                    img_buffer = BytesIO()
                    sig_image.save(img_buffer, format='PNG')
                    img_buffer.seek(0)

                    # Draw on canvas
                    canvas_obj.drawImage(
                        img_buffer,
                        x_start + 5.5 * inch, y_position - 1.2 * inch,
                        width=1.2 * inch,
                        height=0.6 * inch
                    )
                except Exception as e:
                    print(f'[PDFOverlay] Error drawing signature image: {str(e)}')

            return y_position - block_height - 0.2 * inch

        except Exception as e:
            print(f'[PDFOverlay] Error drawing signature block: {str(e)}')
            return y_position

    def _add_verification_stamp(self, page, signatures_data):
        """
        Add verification stamp to PDF
        """
        try:
            # Create stamp overlay
            stamp_buffer = BytesIO()
            c = canvas.Canvas(stamp_buffer, pagesize=A4)
            width, height = A4

            # Verification badge (top right)
            badge_x = width - 1.5 * inch
            badge_y = height - 0.7 * inch

            # Draw badge background
            c.setFillColor(colors.HexColor('#ecfdf5'))
            c.rect(badge_x - 1 * inch, badge_y - 0.4 * inch, 1 * inch, 0.4 * inch, fill=1)

            # Border
            c.setStrokeColor(colors.HexColor('#10b981'))
            c.setLineWidth(1.5)
            c.rect(badge_x - 1 * inch, badge_y - 0.4 * inch, 1 * inch, 0.4 * inch, fill=0)

            # Text
            c.setFont('Helvetica-Bold', 10)
            c.setFillColor(colors.HexColor('#10b981'))
            c.drawString(badge_x - 0.9 * inch, badge_y - 0.3 * inch, '✓ VERIFIED')

            # Signer count
            c.setFont('Helvetica', 8)
            c.setFillColor(colors.HexColor('#64748b'))
            c.drawString(
                badge_x - 0.9 * inch, badge_y - 0.6 * inch,
                f'{len(signatures_data)} signature(s)'
            )

            c.save()
            stamp_buffer.seek(0)

            # Merge with page
            stamp_reader = PdfReader(stamp_buffer)
            stamp_page = stamp_reader.pages[0]
            page.merge_page(stamp_page)

        except Exception as e:
            print(f'[PDFOverlay] Error adding verification stamp: {str(e)}')

    def _get_verifier_role(self, verification):
        """
        Get verifier role from verifiers JSON array
        """
        try:
            if hasattr(verification, 'verifiers') and verification.verifiers:
                for v in verification.verifiers:
                    if v.get('user_id') == verification.assigned_to.id:
                        role = v.get('role', 'AUTHORIZED_SIGNATORY')
                        return 'Checked By' if role == 'CHECKED_BY' else 'Authorized Signatory'
            return 'Verifier'
        except Exception:
            return 'Verifier'

    def add_signature_page(self, pdf_buffer, title="Signatures"):
        """
        Add a new signature page to PDF
        """
        try:
            reader = PdfReader(pdf_buffer)
            writer = PdfWriter()

            # Copy existing pages
            for page in reader.pages:
                writer.add_page(page)

            # Create new signature page
            sig_page_buffer = BytesIO()
            c = canvas.Canvas(sig_page_buffer, pagesize=A4)
            width, height = A4

            # Title
            c.setFont('Helvetica-Bold', 16)
            c.setFillColor(colors.HexColor('#1a1a2e'))
            c.drawString(0.5 * inch, height - 0.7 * inch, title)

            # Divider
            c.setStrokeColor(colors.HexColor('#e2e8f0'))
            c.setLineWidth(1)
            c.line(0.5 * inch, height - 0.9 * inch, width - 0.5 * inch, height - 0.9 * inch)

            # Signature fields
            y = height - 1.5 * inch
            for i in range(3):  # 3 signature fields
                # Label
                c.setFont('Helvetica', 10)
                c.setFillColor(colors.HexColor('#64748b'))
                c.drawString(0.5 * inch, y, f'Signature {i+1}:')

                # Line
                c.setStrokeColor(colors.HexColor('#dbeafe'))
                c.setLineWidth(1)
                c.line(1.5 * inch, y - 0.1 * inch, 4 * inch, y - 0.1 * inch)

                # Date
                c.drawString(4.5 * inch, y, 'Date:')
                c.line(5.2 * inch, y - 0.1 * inch, 6.5 * inch, y - 0.1 * inch)

                y -= 1 * inch

            c.save()
            sig_page_buffer.seek(0)

            # Add new page
            sig_page_reader = PdfReader(sig_page_buffer)
            writer.add_page(sig_page_reader.pages[0])

            # Write to output
            output = BytesIO()
            writer.write(output)
            output.seek(0)

            return output

        except Exception as e:
            print(f'[PDFOverlay] Error adding signature page: {str(e)}')
            pdf_buffer.seek(0)
            return pdf_buffer
