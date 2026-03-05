from rest_framework import serializers
from .models import Vendor


class VendorSerializer(serializers.ModelSerializer):
    """
    Serializer for Vendor model.

    vendor_code is optional on create — if omitted it is auto-generated
    as VEN/0001, VEN/0002, … by the model's save() method.
    """

    class Meta:
        model  = Vendor
        fields = [
            'id', 'vendor_code', 'vendor_name', 'contact_person', 'phone',
            'email', 'address', 'gst_number', 'pan_number',
            # Banking
            'bank_name', 'account_name', 'bank_account_number',
            'ifsc_code', 'swift_code',
            'is_active', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
        extra_kwargs = {
            'vendor_code': {'required': False, 'allow_blank': True},
        }

    def validate_vendor_code(self, value):
        """Skip uniqueness check when blank (auto-generation will handle it)."""
        if not value:
            return value
        qs = Vendor.objects.filter(vendor_code=value.upper())
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("Vendor code already exists")
        return value.upper()
