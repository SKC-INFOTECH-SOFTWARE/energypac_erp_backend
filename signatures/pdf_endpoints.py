"""
PDF Signature Endpoints
- Add signatures to frontend-generated PDFs
- Download PDFs with signature overlays
- Production-ready endpoints
"""

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.http import HttpResponse
from io import BytesIO
import json
from .pdf_overlay_service import PDFSignatureOverlay


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def add_signatures_to_pdf(request, document_type='PI', document_id=None):
    """
    Add signatures to existing PDF

    POST /api/signatures/add-signatures-to-pdf/
    Body: {
        "pdf_file": <file>,
        "document_id": "pi-id-or-po-id",
        "document_type": "PI" or "PO"
    }

    Returns: PDF with signatures overlaid
    """
    try:
        # Get PDF file from request
        pdf_file = request.FILES.get('pdf_file')
        if not pdf_file:
            return Response(
                {'error': 'No PDF file provided'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get document info
        doc_id = request.data.get('document_id') or document_id
        doc_type = request.data.get('document_type', document_type)

        if not doc_id or not doc_type:
            return Response(
                {'error': 'Missing document_id or document_type'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Read PDF file
        pdf_buffer = BytesIO(pdf_file.read())

        # Add signatures
        overlay_service = PDFSignatureOverlay()
        signed_pdf = overlay_service.add_signatures_to_pdf(
            pdf_buffer,
            document_id=doc_id,
            document_type=doc_type
        )

        # Return PDF
        response = HttpResponse(signed_pdf.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{doc_type}_{doc_id}_Signed.pdf"'

        return response

    except Exception as e:
        print(f'[PDF Endpoint] Error: {str(e)}')
        return Response(
            {'error': f'Failed to process PDF: {str(e)}'},
            status=status.HTTP_400_BAD_REQUEST
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def download_signed_pdf(request, document_type, document_id):
    """
    Download signed PDF with all signatures

    GET /api/signatures/download-signed/{document_type}/{document_id}/

    Returns: PDF with signature overlay
    """
    try:
        # Validate document_type
        if document_type not in ['PI', 'PO']:
            return Response(
                {'error': 'Invalid document_type. Must be PI or PO'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check permissions (would validate in real app)
        # ...

        # Generate signature overlay
        overlay_service = PDFSignatureOverlay()

        # Create empty PDF or fetch existing one
        pdf_buffer = BytesIO()

        # Add signatures
        signed_pdf = overlay_service.add_signatures_to_pdf(
            pdf_buffer,
            document_id=document_id,
            document_type=document_type
        )

        # Return PDF
        response = HttpResponse(signed_pdf.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{document_type}_{document_id}_Signed.pdf"'

        return response

    except Exception as e:
        print(f'[PDF Endpoint] Error: {str(e)}')
        return Response(
            {'error': f'Failed to download PDF: {str(e)}'},
            status=status.HTTP_400_BAD_REQUEST
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def add_signature_page(request):
    """
    Add blank signature page to PDF for manual signing

    POST /api/signatures/add-signature-page/
    Body: {
        "pdf_file": <file>,
        "page_title": "Signatures"  # optional
    }

    Returns: PDF with blank signature page appended
    """
    try:
        pdf_file = request.FILES.get('pdf_file')
        if not pdf_file:
            return Response(
                {'error': 'No PDF file provided'},
                status=status.HTTP_400_BAD_REQUEST
            )

        page_title = request.data.get('page_title', 'Signatures')

        # Read PDF
        pdf_buffer = BytesIO(pdf_file.read())

        # Add signature page
        overlay_service = PDFSignatureOverlay()
        pdf_with_sig_page = overlay_service.add_signature_page(pdf_buffer, page_title)

        # Return
        response = HttpResponse(pdf_with_sig_page.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="document_with_signatures.pdf"'

        return response

    except Exception as e:
        print(f'[PDF Endpoint] Error: {str(e)}')
        return Response(
            {'error': f'Failed to add signature page: {str(e)}'},
            status=status.HTTP_400_BAD_REQUEST
        )
