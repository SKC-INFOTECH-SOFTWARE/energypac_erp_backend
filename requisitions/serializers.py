from rest_framework import serializers
from .models import (Requisition, RequisitionItem,
                     VendorRequisitionAssignment, VendorRequisitionItem)
from inventory.serializers import ProductSerializer
from vendors.serializers import VendorSerializer
from vendors.models import Vendor  # FIXED: Added missing import

class RequisitionItemSerializer(serializers.ModelSerializer):
    """Serializer for requisition items"""
    product_details = ProductSerializer(source='product', read_only=True)
    product_name = serializers.CharField(source='product.item_name', read_only=True)
    product_code = serializers.CharField(source='product.item_code', read_only=True)
    unit = serializers.CharField(source='product.unit', read_only=True)

    class Meta:
        model = RequisitionItem
        fields = ['id', 'product', 'product_name', 'product_code', 'unit',
                  'product_details', 'quantity', 'remarks', 'created_at']
        read_only_fields = ['id', 'created_at']


class RequisitionSerializer(serializers.ModelSerializer):
    """Serializer for viewing requisitions"""
    items = RequisitionItemSerializer(many=True, read_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    created_by_code = serializers.CharField(source='created_by.employee_code', read_only=True)
    total_items = serializers.SerializerMethodField()

    class Meta:
        model = Requisition
        fields = ['id', 'requisition_number', 'requisition_date', 'remarks',
                  'created_by', 'created_by_name', 'created_by_code',
                  'is_assigned', 'total_items', 'items', 'created_at', 'updated_at']
        read_only_fields = ['id', 'requisition_number', 'created_by',
                           'is_assigned', 'created_at', 'updated_at']

    def get_total_items(self, obj):
        return obj.items.count()


class RequisitionCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating requisitions"""
    items = RequisitionItemSerializer(many=True)

    class Meta:
        model = Requisition
        fields = ['requisition_date', 'remarks', 'items']

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("At least one item is required")
        return value

    def create(self, validated_data):
        items_data = validated_data.pop('items')
        requisition = Requisition.objects.create(**validated_data)

        for item_data in items_data:
            RequisitionItem.objects.create(requisition=requisition, **item_data)

        return requisition


class VendorRequisitionItemSerializer(serializers.ModelSerializer):
    """Serializer for vendor assigned items"""
    product_name = serializers.CharField(source='product.item_name', read_only=True)
    product_code = serializers.CharField(source='product.item_code', read_only=True)
    unit = serializers.CharField(source='product.unit', read_only=True)

    class Meta:
        model = VendorRequisitionItem
        fields = ['id', 'requisition_item', 'product', 'product_name',
                  'product_code', 'unit', 'quantity']
        read_only_fields = ['id']


class VendorRequisitionAssignmentSerializer(serializers.ModelSerializer):
    """Serializer for viewing vendor assignments"""
    items = VendorRequisitionItemSerializer(many=True, read_only=True)
    vendor_details = VendorSerializer(source='vendor', read_only=True)
    requisition_number = serializers.CharField(source='requisition.requisition_number',
                                                read_only=True)
    assigned_by_name = serializers.CharField(source='assigned_by.get_full_name',
                                              read_only=True)
    total_items = serializers.SerializerMethodField()

    class Meta:
        model = VendorRequisitionAssignment
        fields = ['id', 'requisition', 'requisition_number', 'vendor',
                  'vendor_details', 'assignment_date', 'remarks', 'assigned_by',
                  'assigned_by_name', 'total_items', 'items', 'created_at']
        read_only_fields = ['id', 'assignment_date', 'assigned_by', 'created_at']

    def get_total_items(self, obj):
        return obj.items.count()


class VendorAssignmentCreateSerializer(serializers.Serializer):
    """Serializer for creating vendor assignments"""
    requisition = serializers.UUIDField()
    vendor = serializers.UUIDField()
    remarks = serializers.CharField(required=False, allow_blank=True)
    items = serializers.ListField(
        child=serializers.DictField(),
        help_text="List of items with requisition_item and quantity"
    )

    def to_representation(self, instance):
        """Return the created assignment using VendorRequisitionAssignmentSerializer"""
        return VendorRequisitionAssignmentSerializer(instance).data

    def validate_requisition(self, value):
        try:
            Requisition.objects.get(id=value)
        except Requisition.DoesNotExist:
            raise serializers.ValidationError("Requisition not found")
        return value

    def validate_vendor(self, value):
        try:
            Vendor.objects.get(id=value)  # Now this will work!
        except Vendor.DoesNotExist:
            raise serializers.ValidationError("Vendor not found")
        return value

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("At least one item is required")
        return value

    def create(self, validated_data):
        items_data = validated_data.pop('items')

        # Get the actual model instances from UUIDs
        requisition = Requisition.objects.get(id=validated_data['requisition'])
        vendor = Vendor.objects.get(id=validated_data['vendor'])
        assigned_by = validated_data['assigned_by']
        remarks = validated_data.get('remarks', '')

        # Create assignment with actual instances
        assignment = VendorRequisitionAssignment.objects.create(
            requisition=requisition,
            vendor=vendor,
            assigned_by=assigned_by,
            remarks=remarks
        )

        # Create vendor items
        for item_data in items_data:
            req_item = RequisitionItem.objects.get(id=item_data['requisition_item'])
            VendorRequisitionItem.objects.create(
                assignment=assignment,
                requisition_item=req_item,
                product=req_item.product,
                quantity=item_data['quantity']
            )

        # Mark requisition as assigned
        requisition.is_assigned = True
        requisition.save()

        return assignment
