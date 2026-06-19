from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.http import FileResponse, HttpResponse
import base64

from .models import UserSignature, PIVerification, POVerification, SignatureLog, Notification

User = get_user_model()
from .serializers import (
    SignatureUploadSerializer, SignatureDetailSerializer,
    PIVerificationSerializer, POVerificationSerializer,
    VerificationRequestSerializer, VerificationApprovalSerializer,
    VerificationRejectionSerializer, NotificationSerializer
)
from .services import SignatureService, PIVerificationService, POVerificationService

try:
    from .pdf_service import PDFSignatureService
    PDF_SERVICE_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    PDF_SERVICE_AVAILABLE = False


def _can_request_verification(user, module):
    """
    Who may send a document for verification: its creator is handled separately;
    here we also allow ADMINs and any user with WRITE access to the document's
    module (SALES for PI, PURCHASE for PO). This lets teammates — not just the
    original creator — route documents for sign-off.
    """
    if getattr(user, 'role', None) == 'ADMIN' or getattr(user, 'is_superuser', False):
        return True
    from accounts.models import UserModulePermission
    return UserModulePermission.objects.filter(
        user=user, module=module, can_write=True
    ).exists()


def _user_keeps_verification(verification, user, status_param):
    """
    Decide whether a verification belongs in this user's dashboard list.

    For the PENDING queue we only keep items the user can still act on — i.e.
    the user has a verifier entry that is itself still PENDING (or, for legacy
    single-verifier requests, they are the assigned_to). Once a user has signed
    their part, the request is no longer "pending" *for them*, so it drops out
    of their Pending tab and the stale Approve button (which produced
    "not authorized to approve") disappears.

    For VERIFIED / REJECTED (and any non-pending listing) we keep items the user
    participated in, so they can review their history.
    """
    uid = str(user.id)
    verifiers = verification.verifiers or []
    is_participant = (
        verification.assigned_to_id == user.id
        or any(str(x.get('user_id')) == uid for x in verifiers)
    )

    if status_param == 'PENDING':
        if verifiers:
            return any(
                str(x.get('user_id')) == uid and x.get('status') == 'PENDING'
                for x in verifiers
            )
        # Legacy single-verifier request with no verifiers array.
        return verification.assigned_to_id == user.id

    return is_participant


def _enriched_verifiers(verification):
    """
    Build a PDF-ready verifier list for the latest verification.

    Each entry carries the signer's display name and their signature as a
    base64 data-URI (pulled from the exact signature they signed with), so the
    PDF can render the real signature image — not just a name.
    """
    if not verification:
        return []

    def sig_uri(signature_id):
        if not signature_id:
            return None
        try:
            sig = UserSignature.objects.get(id=signature_id)
        except UserSignature.DoesNotExist:
            return None
        if sig.signature_base64:
            return f'data:image/png;base64,{sig.signature_base64}'
        return None

    verifiers = verification.verifiers or []

    # Pure self-verification has no verifiers array but does carry a signature.
    if not verifiers and verification.signature_id:
        signer = verification.created_by
        return [{
            'user_id': str(signer.id) if signer else None,
            'full_name': (signer.get_full_name() or signer.username) if signer else '',
            'role': 'AUTHORIZED_SIGNATORY',
            'status': verification.status,
            'verified_at': verification.verified_at.isoformat() if verification.verified_at else None,
            'signature_base64': sig_uri(verification.signature_id),
        }]

    out = []
    for v in verifiers:
        try:
            u = User.objects.get(id=v.get('user_id'))
            full_name = u.get_full_name() or u.username
        except User.DoesNotExist:
            full_name = ''
        out.append({
            'user_id': v.get('user_id'),
            'full_name': full_name,
            'role': v.get('role'),
            'status': v.get('status'),
            'verified_at': v.get('verified_at'),
            'signature_base64': sig_uri(v.get('signature_id')),
        })
    return out


# ============================================================================
# SIGNATURE VIEWS
# ============================================================================

class SignatureViewSet(viewsets.ModelViewSet):
    """
    API for managing user signatures

    POST /api/signatures/upload/ - Upload new signature
    GET /api/signatures/ - List user's signatures
    GET /api/signatures/{id}/ - Get signature details
    PATCH /api/signatures/{id}/set-active/ - Set as active
    DELETE /api/signatures/{id}/ - Delete signature
    """

    parser_classes = (MultiPartParser, FormParser)
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = SignatureDetailSerializer

    def get_queryset(self):
        """User can only see their own signatures"""
        return UserSignature.objects.filter(user=self.request.user, is_deleted=False)

    @action(detail=False, methods=['post'], parser_classes=(MultiPartParser, FormParser))
    def upload(self, request):
        """
        Upload a signature.

        A profile may only ever have ONE current signature. Uploading a new one
        replaces the old: any existing non-deleted signatures for this user are
        soft-deleted first. We soft-delete (not hard-delete) so that documents
        already signed with the old signature keep resolving their base64 image
        for historical PDFs / audit.
        """
        from django.db import transaction

        serializer = SignatureUploadSerializer(data=request.data, context={'request': request})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            UserSignature.objects.filter(
                user=request.user, is_deleted=False
            ).update(is_deleted=True, is_active=False)
            serializer.save()

        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['patch'])
    def set_active(self, request, pk=None):
        """Set signature as active"""
        signature = self.get_object()

        # Deactivate all other signatures for this user
        UserSignature.objects.filter(user=request.user).update(is_active=False)

        # Activate this one
        signature.is_active = True
        signature.save()

        return Response(
            SignatureDetailSerializer(signature, context={'request': request}).data
        )

    def destroy(self, request, *args, **kwargs):
        """Delete signature (soft delete)"""
        signature = self.get_object()

        # Check if signature is used in verified documents
        log_count = SignatureLog.objects.filter(signature=signature).count()
        if log_count > 0:
            return Response(
                {'error': 'Cannot delete signature that is already used in verified documents'},
                status=status.HTTP_400_BAD_REQUEST
            )

        signature.is_deleted = True
        signature.save()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ============================================================================
# PI VERIFICATION VIEWS
# ============================================================================

class PIVerificationViewSet(viewsets.ModelViewSet):
    """
    API for PI verification workflow

    POST /api/pi/{pi_id}/verify/ - Create verification request
    POST /api/pi/{pi_id}/self-verify/ - Self-verify PI
    POST /api/pi/{pi_id}/approve-verification/ - Approve verification
    POST /api/pi/{pi_id}/reject-verification/ - Reject verification
    GET /api/pi/{pi_id}/verification-chain/ - Get signature chain
    GET /api/pi/{pi_id}/verification-status/ - Get current status
    """

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = PIVerificationSerializer
    queryset = PIVerification.objects.all()

    def get_queryset(self):
        """
        Scope the list to the current user's verification queue.

        A verification only belongs in a user's "Verify Documents" page when
        they are an assigned verifier (in the verifiers array) or the legacy
        assigned_to. Also honour the ?status= filter the dashboard sends so the
        Pending/Verified/Rejected tabs don't bleed into each other (clicking
        Approve on a stale/verified row was returning 404 errors).
        """
        qs = PIVerification.objects.all()
        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param)

        user = self.request.user
        relevant = [
            v for v in qs.only('id', 'assigned_to', 'verifiers', 'pi', 'created_at')
            if _user_keeps_verification(v, user, status_param)
        ]
        # A document can have several verification records (e.g. legacy/repeated
        # requests). Show each PI only once — the most recent record.
        latest_by_doc = {}
        for v in relevant:
            current = latest_by_doc.get(v.pi_id)
            if current is None or v.created_at > current.created_at:
                latest_by_doc[v.pi_id] = v
        ids = [v.id for v in latest_by_doc.values()]
        return (
            qs.filter(id__in=ids)
            .select_related('pi', 'created_by', 'assigned_to')
            .prefetch_related('pi__items__product')
        )

    @action(detail=False, methods=['post'])
    def create_request(self, request, pi_id=None):
        """Create a new PI verification request with multiple verifiers"""
        from finance.models import ProformaInvoice

        pi = get_object_or_404(ProformaInvoice, id=pi_id)

        # Creator, an admin, or any Sales-write user may request verification
        if pi.created_by != request.user and not _can_request_verification(request.user, 'SALES'):
            return Response(
                {'error': 'You do not have permission to send this PI for verification'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Block duplicate sends: a PI already in-flight or completed cannot be
        # re-sent for verification.
        existing = PIVerification.objects.filter(
            pi=pi, status__in=['PENDING', 'VERIFIED']
        ).first()
        if existing:
            state = 'already verified' if existing.status == 'VERIFIED' else 'already sent for verification'
            return Response(
                {'error': f'This PI is {state}.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = VerificationRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        # Create verification using service
        service = PIVerificationService()
        try:
            # Handle both old (assigned_to_id) and new (verifiers) format
            verifiers_list = serializer.validated_data.get('verifiers') or []

            verification = service.create_verification_with_verifiers(
                obj=pi,
                created_by=request.user,
                verification_type=serializer.validated_data['verification_type'],
                verifiers=verifiers_list,  # List of {user_id, role}
                assigned_to_id=serializer.validated_data.get('assigned_to_id'),  # Fallback for backward compatibility
                notes=serializer.validated_data.get('notes', ''),
                request=request
            )
            return Response(
                PIVerificationSerializer(verification, context={'request': request}).data,
                status=status.HTTP_201_CREATED
            )
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=False, methods=['post'])
    def self_verify(self, request, pi_id=None):
        """Self-verify and sign a PI"""
        from finance.models import ProformaInvoice

        pi = get_object_or_404(ProformaInvoice, id=pi_id)

        # Check if user is the creator
        if pi.created_by != request.user:
            return Response(
                {'error': 'Only PI creator can self-verify'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Get user's active signature
        signature = UserSignature.objects.filter(
            user=request.user,
            is_active=True,
            is_deleted=False
        ).first()

        if not signature:
            return Response(
                {'error': 'No active signature found. Please upload a signature first.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Use service to create self-verification
        service = PIVerificationService()
        try:
            verification = service.self_verify(
                obj=pi,
                user=request.user,
                signature=signature,
                notes=request.data.get('notes', ''),
                request=request
            )

            # Generate download link
            download_url = f"/api/pi/{pi_id}/download-signed/"

            response_data = PIVerificationSerializer(
                verification,
                context={'request': request}
            ).data
            response_data['download_url'] = download_url

            return Response(response_data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=False, methods=['post'])
    def approve_verification(self, request, pi_id=None):
        """Approve a verification request (as assigned verifier)"""
        # Get verification request, support lookup by either verification ID or document ID
        verification = get_object_or_404(
            PIVerification,
            Q(id=pi_id) | Q(pi_id=pi_id),
            status='PENDING'
        )

        # Verify the user is authorized to approve this request
        is_authorized = False
        if verification.assigned_to == request.user:
            is_authorized = True
        elif verification.verifiers:
            user_id_str = str(request.user.id)
            for verifier in verification.verifiers:
                if str(verifier.get('user_id')) == user_id_str and verifier.get('status') == 'PENDING':
                    is_authorized = True
                    break

        if not is_authorized:
            return Response(
                {'error': 'You are not authorized to approve this verification request'},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = VerificationApprovalSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        # Get user's active signature
        signature = UserSignature.objects.filter(
            user=request.user,
            is_active=True,
            is_deleted=False
        ).first()

        if not signature:
            return Response(
                {'error': 'No active signature found. Please upload a signature first.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Use service to approve
        service = PIVerificationService()
        try:
            verification = service.approve_verification(
                verification=verification,
                signature=signature,
                notes=serializer.validated_data.get('notes', ''),
                request=request
            )
            return Response(
                PIVerificationSerializer(verification, context={'request': request}).data,
                status=status.HTTP_200_OK
            )
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=False, methods=['post'])
    def reject_verification(self, request, pi_id=None):
        """Reject a verification request"""
        # Get verification request, support lookup by either verification ID or document ID
        verification = get_object_or_404(
            PIVerification,
            Q(id=pi_id) | Q(pi_id=pi_id),
            status='PENDING'
        )

        # Verify the user is authorized to reject this request
        is_authorized = False
        if verification.assigned_to == request.user:
            is_authorized = True
        elif verification.verifiers:
            user_id_str = str(request.user.id)
            for verifier in verification.verifiers:
                if str(verifier.get('user_id')) == user_id_str and verifier.get('status') == 'PENDING':
                    is_authorized = True
                    break

        if not is_authorized:
            return Response(
                {'error': 'You are not authorized to reject this verification request'},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = VerificationRejectionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        # Use service to reject
        service = PIVerificationService()
        try:
            verification = service.reject_verification(
                verification=verification,
                rejection_reason=serializer.validated_data['rejection_reason'],
                request=request
            )
            return Response(
                PIVerificationSerializer(verification, context={'request': request}).data,
                status=status.HTTP_200_OK
            )
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=False, methods=['get'])
    def verification_chain(self, request, pi_id=None):
        """Get signature chain for a PI"""
        from finance.models import ProformaInvoice

        pi = get_object_or_404(ProformaInvoice, id=pi_id)

        # Get all verifications for this PI
        verifications = PIVerification.objects.filter(
            pi=pi,
            status='VERIFIED'
        ).order_by('signature_position')

        chain = []
        for verification in verifications:
            chain.append({
                'position': verification.signature_position,
                'signer': {
                    'id': verification.assigned_to.id,
                    'username': verification.assigned_to.username,
                    'full_name': verification.assigned_to.get_full_name(),
                },
                'signed_at': verification.verified_at,
                'signature_url': verification.signature.signature_file.url if verification.signature else None,
            })

        return Response({
            'pi_id': pi_id,
            'total_signers': len(chain),
            'chain': chain
        })

    @action(detail=False, methods=['get'])
    def verification_status(self, request, pi_id=None):
        """Get current verification status for a PI"""
        from finance.models import ProformaInvoice

        pi = get_object_or_404(ProformaInvoice, id=pi_id)

        verifications = PIVerification.objects.filter(pi=pi).order_by('-created_at')
        latest = verifications.first()

        return Response({
            'pi_id': pi_id,
            'total_verifications': verifications.count(),
            'verified_count': verifications.filter(status='VERIFIED').count(),
            'pending_count': verifications.filter(status='PENDING').count(),
            'rejected_count': verifications.filter(status='REJECTED').count(),
            'current_status': latest.status if latest else 'NOT_STARTED',
            'verifiers': _enriched_verifiers(latest),
        })

    @action(detail=False, methods=['get'])
    def download_signed(self, request, pi_id=None):
        """Download PI as PDF with all signatures"""
        from finance.models import ProformaInvoice

        pi = get_object_or_404(ProformaInvoice, id=pi_id)

        # Check if user has permission
        if pi.created_by != request.user and not request.user.is_staff:
            return Response(
                {'error': 'You do not have permission to download this document'},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            # Generate PDF
            pdf_service = PDFSignatureService()
            pdf_buffer = pdf_service.generate_pi_pdf(pi, include_verification_chain=True)

            # Return PDF as response
            response = HttpResponse(pdf_buffer.getvalue(), content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="PI_{pi.proforma_invoice_number}_Signed.pdf"'

            return response

        except Exception as e:
            print(f'[PDF] Error generating PI PDF: {str(e)}')
            return Response(
                {'error': 'Failed to generate PDF'},
                status=status.HTTP_400_BAD_REQUEST
            )


# ============================================================================
# PO VERIFICATION VIEWS (Similar to PI)
# ============================================================================

class POVerificationViewSet(viewsets.ModelViewSet):
    """
    API for PO verification workflow

    POST /api/po/{po_id}/create_request/ - Create verification request
    POST /api/po/{po_id}/self-verify/ - Self-verify PO
    POST /api/po/{po_id}/approve-verification/ - Approve verification
    POST /api/po/{po_id}/reject-verification/ - Reject verification
    GET /api/po/{po_id}/verification-chain/ - Get signature chain
    GET /api/po/{po_id}/verification-status/ - Get current status
    GET /api/po/{po_id}/download-signed/ - Download PDF with signatures
    """

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = POVerificationSerializer
    queryset = POVerification.objects.all()

    def get_queryset(self):
        """
        Scope the list to the current user's verification queue and honour the
        ?status= filter (see PIVerificationViewSet.get_queryset for rationale).
        """
        qs = POVerification.objects.all()
        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param)

        user = self.request.user
        relevant = [
            v for v in qs.only('id', 'assigned_to', 'verifiers', 'po', 'created_at')
            if _user_keeps_verification(v, user, status_param)
        ]
        # A document can have several verification records (e.g. legacy/repeated
        # requests). Show each PO only once — the most recent record.
        latest_by_doc = {}
        for v in relevant:
            current = latest_by_doc.get(v.po_id)
            if current is None or v.created_at > current.created_at:
                latest_by_doc[v.po_id] = v
        ids = [v.id for v in latest_by_doc.values()]
        return (
            qs.filter(id__in=ids)
            .select_related('po', 'po__vendor', 'created_by', 'assigned_to')
            .prefetch_related('po__items__product')
        )

    @action(detail=False, methods=['post'])
    def create_request(self, request, po_id=None):
        """Create a new PO verification request with multiple verifiers"""
        from purchase_orders.models import PurchaseOrder

        po = get_object_or_404(PurchaseOrder, id=po_id)

        # Creator, an admin, or any Purchase-write user may request verification
        if po.created_by != request.user and not _can_request_verification(request.user, 'PURCHASE'):
            return Response(
                {'error': 'You do not have permission to send this PO for verification'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Block duplicate sends: a PO already in-flight or completed cannot be
        # re-sent for verification.
        existing = POVerification.objects.filter(
            po=po, status__in=['PENDING', 'VERIFIED']
        ).first()
        if existing:
            state = 'already verified' if existing.status == 'VERIFIED' else 'already sent for verification'
            return Response(
                {'error': f'This PO is {state}.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = VerificationRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        # Create verification using service
        service = POVerificationService()
        try:
            verifiers_list = serializer.validated_data.get('verifiers') or []

            verification = service.create_verification_with_verifiers(
                obj=po,
                created_by=request.user,
                verification_type=serializer.validated_data['verification_type'],
                verifiers=verifiers_list,
                assigned_to_id=serializer.validated_data.get('assigned_to_id'),
                notes=serializer.validated_data.get('notes', ''),
                request=request
            )
            return Response(
                POVerificationSerializer(verification, context={'request': request}).data,
                status=status.HTTP_201_CREATED
            )
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=False, methods=['post'])
    def self_verify(self, request, po_id=None):
        """Self-verify and sign a PO"""
        from purchase_orders.models import PurchaseOrder

        po = get_object_or_404(PurchaseOrder, id=po_id)

        if po.created_by != request.user:
            return Response(
                {'error': 'Only PO creator can self-verify'},
                status=status.HTTP_403_FORBIDDEN
            )

        signature = UserSignature.objects.filter(
            user=request.user,
            is_active=True,
            is_deleted=False
        ).first()

        if not signature:
            return Response(
                {'error': 'No active signature found. Please upload a signature first.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        service = POVerificationService()
        try:
            verification = service.self_verify(
                obj=po,
                user=request.user,
                signature=signature,
                notes=request.data.get('notes', ''),
                request=request
            )

            response_data = POVerificationSerializer(
                verification,
                context={'request': request}
            ).data
            response_data['download_url'] = f"/api/po/{po_id}/download-signed/"

            return Response(response_data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=False, methods=['post'])
    def approve_verification(self, request, po_id=None):
        """Approve a verification request (as assigned verifier)"""
        # Get verification request, support lookup by either verification ID or document ID
        verification = get_object_or_404(
            POVerification,
            Q(id=po_id) | Q(po_id=po_id),
            status='PENDING'
        )

        # Verify the user is authorized to approve this request
        is_authorized = False
        if verification.assigned_to == request.user:
            is_authorized = True
        elif verification.verifiers:
            user_id_str = str(request.user.id)
            for verifier in verification.verifiers:
                if str(verifier.get('user_id')) == user_id_str and verifier.get('status') == 'PENDING':
                    is_authorized = True
                    break

        if not is_authorized:
            return Response(
                {'error': 'You are not authorized to approve this verification request'},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = VerificationApprovalSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        signature = UserSignature.objects.filter(
            user=request.user,
            is_active=True,
            is_deleted=False
        ).first()

        if not signature:
            return Response(
                {'error': 'No active signature found. Please upload a signature first.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        service = POVerificationService()
        try:
            verification = service.approve_verification(
                verification=verification,
                signature=signature,
                notes=serializer.validated_data.get('notes', ''),
                request=request
            )
            return Response(
                POVerificationSerializer(verification, context={'request': request}).data,
                status=status.HTTP_200_OK
            )
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=False, methods=['post'])
    def reject_verification(self, request, po_id=None):
        """Reject a verification request"""
        # Get verification request, support lookup by either verification ID or document ID
        verification = get_object_or_404(
            POVerification,
            Q(id=po_id) | Q(po_id=po_id),
            status='PENDING'
        )

        # Verify the user is authorized to reject this request
        is_authorized = False
        if verification.assigned_to == request.user:
            is_authorized = True
        elif verification.verifiers:
            user_id_str = str(request.user.id)
            for verifier in verification.verifiers:
                if str(verifier.get('user_id')) == user_id_str and verifier.get('status') == 'PENDING':
                    is_authorized = True
                    break

        if not is_authorized:
            return Response(
                {'error': 'You are not authorized to reject this verification request'},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = VerificationRejectionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        service = POVerificationService()
        try:
            verification = service.reject_verification(
                verification=verification,
                rejection_reason=serializer.validated_data['rejection_reason'],
                request=request
            )
            return Response(
                POVerificationSerializer(verification, context={'request': request}).data,
                status=status.HTTP_200_OK
            )
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=False, methods=['get'])
    def verification_chain(self, request, po_id=None):
        """Get signature chain for a PO"""
        from purchase_orders.models import PurchaseOrder

        po = get_object_or_404(PurchaseOrder, id=po_id)

        verifications = POVerification.objects.filter(
            po=po,
            status='VERIFIED'
        ).order_by('signature_position')

        chain = []
        for verification in verifications:
            chain.append({
                'position': verification.signature_position,
                'signer': {
                    'id': verification.assigned_to.id,
                    'username': verification.assigned_to.username,
                    'full_name': verification.assigned_to.get_full_name(),
                },
                'signed_at': verification.verified_at,
                'signature_url': verification.signature.signature_file.url if verification.signature else None,
            })

        return Response({
            'po_id': po_id,
            'total_signers': len(chain),
            'chain': chain
        })

    @action(detail=False, methods=['get'])
    def verification_status(self, request, po_id=None):
        """Get current verification status for a PO"""
        from purchase_orders.models import PurchaseOrder

        po = get_object_or_404(PurchaseOrder, id=po_id)

        verifications = POVerification.objects.filter(po=po).order_by('-created_at')
        latest = verifications.first()

        return Response({
            'po_id': po_id,
            'total_verifications': verifications.count(),
            'verified_count': verifications.filter(status='VERIFIED').count(),
            'pending_count': verifications.filter(status='PENDING').count(),
            'rejected_count': verifications.filter(status='REJECTED').count(),
            'current_status': latest.status if latest else 'NOT_STARTED',
            'verifiers': _enriched_verifiers(latest),
        })

    @action(detail=False, methods=['get'])
    def download_signed(self, request, po_id=None):
        """Download PO as PDF with all signatures"""
        from purchase_orders.models import PurchaseOrder

        po = get_object_or_404(PurchaseOrder, id=po_id)

        # Check if user has permission
        if po.created_by != request.user and not request.user.is_staff:
            return Response(
                {'error': 'You do not have permission to download this document'},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            # Generate PDF
            pdf_service = PDFSignatureService()
            pdf_buffer = pdf_service.generate_po_pdf(po, include_verification_chain=True)

            # Return PDF as response
            response = HttpResponse(pdf_buffer.getvalue(), content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="PO_{po.po_number}_Signed.pdf"'

            return response

        except Exception as e:
            print(f'[PDF] Error generating PO PDF: {str(e)}')
            return Response(
                {'error': 'Failed to generate PDF'},
                status=status.HTTP_400_BAD_REQUEST
            )


# ============================================================================
# NOTIFICATION VIEWS
# ============================================================================

class NotificationViewSet(viewsets.ModelViewSet):
    """
    API for managing notifications

    GET /api/notifications/ - List notifications
    PATCH /api/notifications/{id}/mark-as-read/ - Mark as read
    POST /api/notifications/mark-all-as-read/ - Mark all as read
    DELETE /api/notifications/{id}/ - Delete notification
    """

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = NotificationSerializer

    def get_queryset(self):
        """User can only see their own notifications"""
        return Notification.objects.filter(user=self.request.user)

    def get_paginated_response(self, data):
        """Custom pagination response"""
        response = super().get_paginated_response(data)
        response.data['unread_count'] = Notification.objects.filter(
            user=self.request.user,
            is_read=False
        ).count()
        return response

    @action(detail=True, methods=['patch'])
    def mark_as_read(self, request, pk=None):
        """Mark notification as read"""
        notification = self.get_object()
        notification.is_read = True
        notification.read_at = timezone.now()
        notification.save()
        return Response(NotificationSerializer(notification).data)

    @action(detail=False, methods=['post'])
    def mark_all_as_read(self, request):
        """Mark all notifications as read"""
        count = Notification.objects.filter(
            user=request.user,
            is_read=False
        ).update(is_read=True, read_at=timezone.now())
        return Response({'marked_as_read': count})

    @action(detail=False, methods=['get'])
    def unread_count(self, request):
        """Get unread notification count"""
        count = Notification.objects.filter(
            user=request.user,
            is_read=False
        ).count()
        return Response({'unread_count': count})
