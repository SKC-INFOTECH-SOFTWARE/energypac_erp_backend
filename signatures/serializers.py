from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import UserSignature, PIVerification, POVerification, SignatureLog, Notification
import base64

User = get_user_model()


class UserSimpleSerializer(serializers.ModelSerializer):
    """Simple user serializer for nested use"""
    full_name = serializers.CharField(source='get_full_name', read_only=True)

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'full_name']


# ============================================================================
# SIGNATURE SERIALIZERS
# ============================================================================

class SignatureUploadSerializer(serializers.ModelSerializer):
    """For uploading new signatures"""

    class Meta:
        model = UserSignature
        fields = ['signature_file', 'name', 'is_active']

    def create(self, validated_data):
        """Create signature with base64 encoding"""
        signature = UserSignature(**validated_data)

        # Convert file to base64 WITHOUT closing it — save() still needs to
        # write the same file to storage, so rewind to the start instead.
        if signature.signature_file:
            signature.signature_file.seek(0)
            signature.signature_base64 = base64.b64encode(
                signature.signature_file.read()
            ).decode('utf-8')
            signature.signature_file.seek(0)

        signature.user = self.context['request'].user
        signature.save()
        return signature


class SignatureDetailSerializer(serializers.ModelSerializer):
    """For displaying signature details"""

    user = UserSimpleSerializer(read_only=True)
    signature_url = serializers.SerializerMethodField()

    class Meta:
        model = UserSignature
        fields = ['id', 'user', 'name', 'is_active', 'signature_url', 'created_at']
        read_only_fields = ['id', 'user', 'created_at']

    def get_signature_url(self, obj):
        """Return signature file URL"""
        if obj.signature_file:
            request = self.context.get('request')
            return request.build_absolute_uri(obj.signature_file.url)
        return None


# ============================================================================
# VERIFICATION SERIALIZERS
# ============================================================================

class SignatureChainItemSerializer(serializers.Serializer):
    """Represent a single signature in the chain"""

    position = serializers.IntegerField()
    signer = UserSimpleSerializer()
    signed_at = serializers.DateTimeField()
    signature_url = serializers.CharField()
    ip_address = serializers.CharField()
    device_info = serializers.JSONField()


class VerificationBaseSerializer(serializers.ModelSerializer):
    """Base serializer for PI/PO verifications"""

    created_by = UserSimpleSerializer(read_only=True)
    assigned_to = UserSimpleSerializer(read_only=True)
    signature_details = SignatureDetailSerializer(source='signature', read_only=True)
    verification_chain = serializers.SerializerMethodField()
    verifiers_detailed = serializers.SerializerMethodField()

    class Meta:
        fields = [
            'id', 'created_by', 'assigned_to', 'verification_type', 'status',
            'verified_at', 'notes', 'rejection_reason', 'signature_details',
            'signature_position', 'verification_chain', 'verifiers', 'verifiers_detailed',
            'expires_at', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'created_by', 'verified_at', 'created_at', 'updated_at', 'verifiers_detailed'
        ]

    def get_verification_chain(self, obj):
        """Return formatted verification chain"""
        chain = []
        for item in obj.verification_chain:
            chain.append({
                'position': item.get('position'),
                'signer': item.get('signer'),
                'signed_at': item.get('signed_at'),
                'signature_url': item.get('signature_url'),
            })
        return chain

    def get_verifiers_detailed(self, obj):
        """Return detailed verifier info with user data"""
        verifiers = []
        for v in obj.verifiers:
            try:
                user = User.objects.get(id=v.get('user_id'))
                verifiers.append({
                    'user_id': v.get('user_id'),
                    'user': UserSimpleSerializer(user).data,
                    'role': v.get('role'),
                    'status': v.get('status', 'PENDING'),
                    'verified_at': v.get('verified_at'),
                })
            except User.DoesNotExist:
                pass
        return verifiers


class PIVerificationSerializer(VerificationBaseSerializer):
    """Serializer for PI verifications"""

    pi_number = serializers.CharField(source='pi.pi_number', read_only=True)
    pi_id = serializers.UUIDField(source='pi.id', read_only=True)
    document = serializers.SerializerMethodField()

    class Meta(VerificationBaseSerializer.Meta):
        model = PIVerification
        fields = VerificationBaseSerializer.Meta.fields + ['pi_number', 'pi_id', 'document']

    def get_document(self, obj):
        """Self-contained PI summary so the verifier sees what they're signing."""
        pi = obj.pi
        return {
            'type': 'PI',
            'number': pi.pi_number,
            'date': pi.pi_date,
            'currency': pi.currency,
            'trade_type': pi.trade_type,
            'status': pi.status,
            'party': pi.consignee or pi.applicant_importer or '',
            'grand_total': pi.grand_total,
            'balance': pi.balance,
            'items': [
                {
                    'name': it.product.item_name if it.product else '',
                    'hsn_code': it.hsn_code,
                    'quantity': it.quantity,
                    'unit_price': it.unit_price,
                    'amount': it.amount,
                }
                for it in pi.items.all()
            ],
        }


class POVerificationSerializer(VerificationBaseSerializer):
    """Serializer for PO verifications"""

    po_number = serializers.CharField(source='po.po_number', read_only=True)
    po_id = serializers.UUIDField(source='po.id', read_only=True)
    document = serializers.SerializerMethodField()

    class Meta(VerificationBaseSerializer.Meta):
        model = POVerification
        fields = VerificationBaseSerializer.Meta.fields + ['po_number', 'po_id', 'document']

    def get_document(self, obj):
        """Self-contained PO summary so the verifier sees what they're signing."""
        po = obj.po
        return {
            'type': 'PO',
            'number': po.po_number,
            'date': po.po_date,
            'currency': po.currency,
            'status': po.status,
            'party': po.vendor.vendor_name if po.vendor else '',
            'project_name': po.project_name,
            'grand_total': po.total_amount,
            'balance': po.balance,
            'items': [
                {
                    'name': it.product.item_name if it.product else '',
                    'quantity': it.quantity,
                    'rate': it.rate,
                    'amount': it.amount,
                }
                for it in po.items.all()
            ],
        }


# ============================================================================
# VERIFICATION REQUEST SERIALIZERS
# ============================================================================

class VerifierDetailSerializer(serializers.Serializer):
    """Serializer for individual verifiers with roles"""
    user_id = serializers.UUIDField()
    role = serializers.ChoiceField(choices=['CHECKED_BY', 'AUTHORIZED_SIGNATORY'])


class VerificationRequestSerializer(serializers.Serializer):
    """For creating verification requests with multiple verifiers"""

    verification_type = serializers.ChoiceField(
        choices=['SELF_VERIFICATION', 'EXTERNAL_VERIFICATION', 'CHAIN_VERIFICATION'],
        required=False,
        default=None,
    )
    assigned_to_id = serializers.IntegerField(required=False, allow_null=True, help_text="Deprecated: use verifiers field")
    verifiers = VerifierDetailSerializer(many=True, required=False, allow_empty=True)
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate(self, data):
        # Auto-determine verification_type if not provided
        if not data.get('verification_type'):
            has_verifiers = data.get('verifiers') and len(data.get('verifiers', [])) > 0
            has_assigned_to = data.get('assigned_to_id')
            if has_verifiers or has_assigned_to:
                data['verification_type'] = 'EXTERNAL_VERIFICATION'
            else:
                data['verification_type'] = 'SELF_VERIFICATION'

        if data.get('verification_type') == 'EXTERNAL_VERIFICATION':
            # Check either assigned_to_id OR verifiers is provided
            has_assigned_to = data.get('assigned_to_id')
            has_verifiers = data.get('verifiers') and len(data.get('verifiers', [])) > 0

            if not has_assigned_to and not has_verifiers:
                raise serializers.ValidationError(
                    "Either assigned_to_id or verifiers is required for external verification"
                )
        return data


class VerificationApprovalSerializer(serializers.Serializer):
    """For approving verifications"""

    notes = serializers.CharField(required=False, allow_blank=True)


class VerificationRejectionSerializer(serializers.Serializer):
    """For rejecting verifications"""

    rejection_reason = serializers.CharField(required=True)


# ============================================================================
# SIGNATURE LOG SERIALIZER
# ============================================================================

class SignatureLogSerializer(serializers.ModelSerializer):
    """For audit trail"""

    user = UserSimpleSerializer(read_only=True)
    signature_details = SignatureDetailSerializer(source='signature', read_only=True)

    class Meta:
        model = SignatureLog
        fields = [
            'id', 'user', 'signature_details', 'signature_position',
            'signed_at', 'ip_address', 'device_info', 'created_at'
        ]
        read_only_fields = fields


# ============================================================================
# NOTIFICATION SERIALIZERS
# ============================================================================

class NotificationSerializer(serializers.ModelSerializer):
    """For notifications"""

    user = UserSimpleSerializer(read_only=True)
    actor = UserSimpleSerializer(read_only=True)

    class Meta:
        model = Notification
        fields = [
            'id', 'user', 'notification_type', 'actor', 'title', 'message',
            'action_url', 'is_read', 'read_at', 'created_at', 'expires_at'
        ]
        read_only_fields = [
            'id', 'user', 'actor', 'created_at', 'expires_at'
        ]
