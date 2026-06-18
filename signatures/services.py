from django.utils import timezone
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.exceptions import ValidationError
from django.db import transaction
import base64
import uuid

from .models import UserSignature, PIVerification, POVerification, SignatureLog, Notification

User = get_user_model()


class SignatureService:
    """Service for managing signatures"""

    @staticmethod
    def validate_signature_file(file):
        """Validate signature file"""
        # Check file type
        allowed_types = ['image/png', 'image/jpeg']
        if file.content_type not in allowed_types:
            raise ValidationError("Only PNG and JPG files are allowed")

        # Check file size (max 5MB)
        if file.size > 5 * 1024 * 1024:
            raise ValidationError("File size must be less than 5MB")

        return True

    @staticmethod
    def get_user_active_signature(user):
        """Get user's active signature"""
        return UserSignature.objects.filter(
            user=user,
            is_active=True,
            is_deleted=False
        ).first()

    @staticmethod
    def convert_to_base64(file):
        """Convert file to base64"""
        file.open('rb')
        base64_str = base64.b64encode(file.read()).decode('utf-8')
        file.close()
        return base64_str


class VerificationServiceBase:
    """Base service for PI and PO verifications"""

    VERIFICATION_MODEL = None  # Override in subclass

    def create_verification_with_verifiers(self, obj, created_by, verification_type,
                                          verifiers=None, assigned_to_id=None, notes='', request=None):
        """Create a new verification request with multiple verifiers and roles"""

        if verification_type == 'EXTERNAL_VERIFICATION':
            if not verifiers and not assigned_to_id:
                raise ValidationError("Either verifiers or assigned_to_id is required for external verification")

        # Prepare verifiers list for JSON storage
        verifiers_data = []
        assigned_to = None  # Set to first verifier for backward compatibility

        if verifiers and len(verifiers) > 0:
            for v in verifiers:
                user = User.objects.get(id=v['user_id'])
                verifiers_data.append({
                    'user_id': str(v['user_id']),
                    'role': v['role'],
                    'status': 'PENDING',
                    'verified_at': None,
                    'signature_id': None,
                })
                if not assigned_to:  # Set first verifier as primary
                    assigned_to = user
        elif assigned_to_id:  # Fallback for backward compatibility
            user = User.objects.get(id=assigned_to_id)
            verifiers_data.append({
                'user_id': str(assigned_to_id),
                'role': 'AUTHORIZED_SIGNATORY',
                'status': 'PENDING',
                'verified_at': None,
                'signature_id': None,
            })
            assigned_to = user

        # Dynamically set the correct FK field based on the model
        model_kwargs = dict(
            created_by=created_by,
            assigned_to=assigned_to,
            verification_type=verification_type,
            status='PENDING',
            notes=notes,
            verifiers=verifiers_data,
        )
        if hasattr(self.VERIFICATION_MODEL, 'pi'):
            model_kwargs['pi'] = obj
        if hasattr(self.VERIFICATION_MODEL, 'po'):
            model_kwargs['po'] = obj

        verification = self.VERIFICATION_MODEL(**model_kwargs)

        if verification_type == 'SELF_VERIFICATION':
            signature = SignatureService.get_user_active_signature(created_by)
            if not signature:
                raise ValidationError("No active signature found")
            verification.signature = signature
            verification.signature_position = 1

        # If the creator assigned themselves to a role, make sure they have a
        # signature BEFORE we persist anything — so we never leave a half-signed
        # request behind and self-verification can be applied in one step.
        creator_id = str(created_by.id)
        creator_is_verifier = any(v['user_id'] == creator_id for v in verifiers_data)
        creator_signature = None
        if creator_is_verifier:
            creator_signature = SignatureService.get_user_active_signature(created_by)
            if not creator_signature:
                raise ValidationError(
                    "Please upload your signature in your profile before assigning yourself as a verifier."
                )

        with transaction.atomic():
            verification.save()

            # Notify the OTHER assigned verifiers (skip the creator — their slot
            # is signed automatically just below).
            notify_list = [v for v in verifiers_data if v['user_id'] != creator_id]
            if notify_list:
                self._send_notification_to_verifiers(verification, notify_list, request)

            # Auto-sign the creator's own slot(s) so self-verification is one click.
            if creator_is_verifier:
                self.approve_verification(
                    verification, creator_signature, user=created_by, request=request
                )
                verification.refresh_from_db()

        return verification

    def create_verification(self, obj, created_by, verification_type, assigned_to_id=None,
                          notes='', request=None):
        """Create a new verification request (backward compatible)"""

        if verification_type == 'EXTERNAL_VERIFICATION' and not assigned_to_id:
            raise ValidationError("assigned_to_id is required for external verification")

        assigned_to = None
        if assigned_to_id:
            assigned_to = User.objects.get(id=assigned_to_id)

        # Dynamically set the correct FK field based on the model
        model_kwargs = dict(
            created_by=created_by,
            assigned_to=assigned_to,
            verification_type=verification_type,
            status='PENDING',
            notes=notes,
        )
        if hasattr(self.VERIFICATION_MODEL, 'pi'):
            model_kwargs['pi'] = obj
        if hasattr(self.VERIFICATION_MODEL, 'po'):
            model_kwargs['po'] = obj

        verification = self.VERIFICATION_MODEL(**model_kwargs)

        if verification_type == 'SELF_VERIFICATION':
            signature = SignatureService.get_user_active_signature(created_by)
            if not signature:
                raise ValidationError("No active signature found")
            verification.signature = signature
            verification.signature_position = 1

        verification.save()

        # Send notification
        self._send_notification(verification, 'VERIFICATION_REQUESTED', request)

        return verification

    def self_verify(self, obj, user, signature, notes='', request=None):
        """Self-verify and sign"""

        # Dynamically set the correct FK field based on the model
        model_kwargs = dict(
            created_by=user,
            assigned_to=user,
            verification_type='SELF_VERIFICATION',
            status='VERIFIED',
            verified_at=timezone.now(),
            notes=notes,
            signature=signature,
            signature_position=1,
        )
        if hasattr(self.VERIFICATION_MODEL, 'pi'):
            model_kwargs['pi'] = obj
        if hasattr(self.VERIFICATION_MODEL, 'po'):
            model_kwargs['po'] = obj

        verification = self.VERIFICATION_MODEL(**model_kwargs)
        verification.save()

        # Log signature
        self._log_signature(verification, user, signature, 1, request)

        # Update verification chain
        self._update_verification_chain(verification)

        # Send notification
        self._send_notification(verification, 'VERIFICATION_COMPLETED', request)

        return verification

    def approve_verification(self, verification, signature, notes='', user=None, request=None):
        """Approve a verification request"""
        if not user and request:
            user = request.user
        if not user:
            user = verification.assigned_to

        user_id_str = str(user.id)
        
        # 1. Update the verifier status in JSON array if present
        if verification.verifiers:
            updated_verifiers = []
            for verifier in verification.verifiers:
                if str(verifier.get('user_id')) == user_id_str:
                    verifier['status'] = 'VERIFIED'
                    verifier['verified_at'] = timezone.now().isoformat()
                    verifier['signature_id'] = str(signature.id)
                updated_verifiers.append(verifier)
            verification.verifiers = updated_verifiers

        # 2. Determine if all verifiers have verified
        all_verified = True
        next_verifier_user = None
        next_role = 'AUTHORIZED_SIGNATORY'
        
        if verification.verifiers:
            for verifier in verification.verifiers:
                if verifier.get('status') == 'PENDING':
                    all_verified = False
                    if not next_verifier_user:
                        try:
                            next_verifier_user = User.objects.get(id=verifier.get('user_id'))
                            next_role = verifier.get('role', 'AUTHORIZED_SIGNATORY')
                        except User.DoesNotExist:
                            pass
        else:
            all_verified = True

        # 3. Calculate signature position
        position = 1
        if verification.verifiers:
            position = sum(1 for v in verification.verifiers if v.get('status') == 'VERIFIED')

        # 4. Log signature for audit trail
        self._log_signature(verification, user, signature, position, request)

        # 5. Handle status update & next steps
        if all_verified:
            verification.status = 'VERIFIED'
            verification.verified_at = timezone.now()
            verification.signature = signature
            verification.notes = notes
            verification.save()

            # Update verification chain
            self._update_verification_chain(verification)

            # Send notification to creator
            self._send_notification(verification, 'VERIFICATION_COMPLETED', request)
        else:
            # Move to next verifier
            verification.assigned_to = next_verifier_user
            verification.save()

            # Update verification chain
            self._update_verification_chain(verification)

            # Send notification to the next verifier
            self._send_notification_to_verifiers(
                verification, 
                [{'user_id': str(next_verifier_user.id), 'role': next_role}], 
                request
            )

        return verification

    def reject_verification(self, verification, rejection_reason='', user=None, request=None):
        """Reject a verification request"""
        if not user and request:
            user = request.user
        if not user:
            user = verification.assigned_to

        # Update the verifier status in JSON array if present
        if verification.verifiers and user:
            user_id_str = str(user.id)
            updated_verifiers = []
            for verifier in verification.verifiers:
                if str(verifier.get('user_id')) == user_id_str:
                    verifier['status'] = 'REJECTED'
                updated_verifiers.append(verifier)
            verification.verifiers = updated_verifiers

        verification.status = 'REJECTED'
        verification.rejection_reason = rejection_reason
        verification.save()

        # Send notification to creator
        self._send_notification(verification, 'VERIFICATION_REJECTED', request)

        return verification

    @staticmethod
    def _is_pi(verification):
        """Check if verification is for a PI (safe for both PI and PO models)"""
        return hasattr(verification, 'pi_id') and verification.pi_id is not None

    @staticmethod
    def _get_doc_id(verification):
        """Get the document ID (pi_id or po_id) safely"""
        if hasattr(verification, 'pi_id') and verification.pi_id is not None:
            return verification.pi_id
        if hasattr(verification, 'po_id') and verification.po_id is not None:
            return verification.po_id
        return None

    @staticmethod
    def _doc_content_type(verification):
        """Resolve the ContentType + label ('PI'/'PO') for the signed document."""
        from django.contrib.contenttypes.models import ContentType
        if VerificationServiceBase._is_pi(verification):
            from sales.models import ProformaInvoice as DocModel
            return ContentType.objects.get_for_model(DocModel), 'PI'
        from purchase_orders.models import PurchaseOrder as DocModel
        return ContentType.objects.get_for_model(DocModel), 'PO'

    @staticmethod
    def _log_signature(verification, user, signature, position, request):
        """Log signature for audit trail"""

        user_agent = ''
        ip_address = '0.0.0.0'

        if request:
            user_agent = request.META.get('HTTP_USER_AGENT', '')
            # Get IP address
            x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
            ip_address = x_forwarded_for.split(',')[0] if x_forwarded_for else request.META.get(
                'REMOTE_ADDR'
            )

        doc_id = VerificationServiceBase._get_doc_id(verification)
        content_type, obj_type = VerificationServiceBase._doc_content_type(verification)

        SignatureLog.objects.create(
            content_type=content_type,
            object_id=doc_id,
            content_object_type=obj_type,
            user=user,
            signature=signature,
            signature_position=position,
            ip_address=ip_address,
            user_agent=user_agent,
            device_info={}
        )

    @staticmethod
    def _update_verification_chain(verification):
        """Update verification chain JSON"""
        chain = []
        
        # If the new multi-verifier flow is used
        if verification.verifiers:
            position = 1
            for v in verification.verifiers:
                if v.get('status') == 'VERIFIED':
                    try:
                        user = User.objects.get(id=v.get('user_id'))
                        sig_url = None
                        if v.get('signature_id'):
                            try:
                                sig = UserSignature.objects.get(id=v.get('signature_id'))
                                sig_url = sig.signature_file.url if sig.signature_file else None
                            except UserSignature.DoesNotExist:
                                pass
                        
                        chain.append({
                            'position': position,
                            'signer_id': str(user.id),
                            'signer_name': user.get_full_name(),
                            'signed_at': v.get('verified_at'),
                            'signature_id': v.get('signature_id'),
                            'signature_url': sig_url,
                        })
                        position += 1
                    except User.DoesNotExist:
                        pass
        else:
            # Fallback to single verifier logic
            # Build filter kwargs based on model type
            filter_kwargs = {'status': 'VERIFIED'}
            if hasattr(verification, 'pi_id') and verification.pi_id is not None:
                filter_kwargs['pi_id'] = verification.pi_id
            elif hasattr(verification, 'po_id') and verification.po_id is not None:
                filter_kwargs['po_id'] = verification.po_id

            verification_qs = verification.__class__.objects.filter(
                **filter_kwargs
            ).order_by('signature_position')

            for ver in verification_qs:
                chain.append({
                    'position': ver.signature_position,
                    'signer_id': str(ver.assigned_to.id) if ver.assigned_to else None,
                    'signer_name': ver.assigned_to.get_full_name() if ver.assigned_to else 'Unknown',
                    'signed_at': ver.verified_at.isoformat() if ver.verified_at else None,
                    'signature_id': str(ver.signature.id) if ver.signature else None,
                    'signature_url': ver.signature.signature_file.url if ver.signature and ver.signature.signature_file else None,
                })

        verification.verification_chain = chain
        verification.save()

    @staticmethod
    def _send_notification_to_verifiers(verification, verifiers_data, request):
        """Send notifications to multiple verifiers with their roles"""

        is_pi = VerificationServiceBase._is_pi(verification)
        doc_id = VerificationServiceBase._get_doc_id(verification)
        content_type, doc_type = VerificationServiceBase._doc_content_type(verification)
        notifications_to_create = []

        for verifier in verifiers_data:
            user = User.objects.get(id=verifier['user_id'])
            role = verifier['role']
            role_display = 'Checked By' if role == 'CHECKED_BY' else 'Authorized Signatory'

            title = f"{doc_type} Verification Requested - {role_display}"
            message = f"{verification.created_by.get_full_name()} needs your approval as '{role_display}'"

            notifications_to_create.append(
                Notification(
                    user=user,
                    notification_type=f'{doc_type}_VERIFICATION_REQUESTED',
                    content_type=content_type,
                    object_id=doc_id,
                    actor=verification.created_by,
                    title=title,
                    message=message,
                    action_url=f"/{doc_type.lower()}/{doc_id}/verify/"
                )
            )

        if notifications_to_create:
            Notification.objects.bulk_create(notifications_to_create)

    @staticmethod
    def _send_notification(verification, notification_type, request):
        """Send notification to relevant user"""

        is_pi = VerificationServiceBase._is_pi(verification)
        doc_id = VerificationServiceBase._get_doc_id(verification)
        content_type, doc_type = VerificationServiceBase._doc_content_type(verification)
        notifications_to_create = []

        if notification_type == 'VERIFICATION_REQUESTED':
            # Notify the assigned verifier
            if verification.assigned_to:
                title = f"{doc_type} Verification Requested"
                message = f"{verification.created_by.get_full_name()} has sent you a verification request"

                notifications_to_create.append(
                    Notification(
                        user=verification.assigned_to,
                        notification_type=f'{doc_type}_VERIFICATION_REQUESTED',
                        content_type=content_type,
                        object_id=doc_id,
                        actor=verification.created_by,
                        title=title,
                        message=message,
                        action_url=f"/{doc_type.lower()}/{doc_id}/verify/"
                    )
                )

        elif notification_type == 'VERIFICATION_COMPLETED':
            # Notify the creator
            signer_name = "Your verifier"
            actor = None
            if request and request.user:
                signer_name = request.user.get_full_name()
                actor = request.user
            elif verification.assigned_to:
                signer_name = verification.assigned_to.get_full_name()
                actor = verification.assigned_to

            title = f"{doc_type} Verification Completed"
            message = f"{signer_name} has verified your document"

            notifications_to_create.append(
                Notification(
                    user=verification.created_by,
                    notification_type=f'{doc_type}_VERIFIED',
                    content_type=content_type,
                    object_id=doc_id,
                    actor=actor,
                    title=title,
                    message=message,
                    action_url=f"/{doc_type.lower()}/{doc_id}/"
                )
            )

        elif notification_type == 'VERIFICATION_REJECTED':
            # Notify the creator
            rejecter_name = "A verifier"
            actor = None
            if request and request.user:
                rejecter_name = request.user.get_full_name()
                actor = request.user
            elif verification.assigned_to:
                rejecter_name = verification.assigned_to.get_full_name()
                actor = verification.assigned_to

            title = f"{doc_type} Verification Rejected"
            message = f"{rejecter_name} has rejected your verification request"

            notifications_to_create.append(
                Notification(
                    user=verification.created_by,
                    notification_type=f'{doc_type}_REJECTED',
                    content_type=content_type,
                    object_id=doc_id,
                    actor=actor,
                    title=title,
                    message=message,
                    action_url=f"/{doc_type.lower()}/{doc_id}/"
                )
            )

        # Bulk create notifications
        if notifications_to_create:
            Notification.objects.bulk_create(notifications_to_create)


class PIVerificationService(VerificationServiceBase):
    """Service for PI verifications"""

    VERIFICATION_MODEL = PIVerification


class POVerificationService(VerificationServiceBase):
    """Service for PO verifications"""

    VERIFICATION_MODEL = POVerification
