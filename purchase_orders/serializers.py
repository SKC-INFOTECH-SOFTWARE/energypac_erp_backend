from rest_framework import serializers
from .models import PurchaseOrder, PurchaseOrderItem
from requisitions.models import Requisition, VendorQuotationItem
from vendors.models import Vendor
from collections import defaultdict

class PurchaseOrderItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.item_name', read_only=True)
    product_code = serializers.CharField(source='product.item_code', read_only=True)
    unit = serializers.CharField(source='product.unit', read_only=True)

    class Meta:
        model = PurchaseOrderItem
        fields = ['id', 'product', 'product_name', 'product_code', 'unit',
                  'quantity', 'rate', 'amount', 'is_received']
        read_only_fields = ['id', 'amount']


class PurchaseOrderSerializer(serializers.ModelSerializer):
    items = PurchaseOrderItemSerializer(many=True, read_only=True)
    vendor_name = serializers.CharField(source='vendor.vendor_name', read_only=True)
    requisition_number = serializers.CharField(source='requisition.requisition_number', read_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)

    class Meta:
        model = PurchaseOrder
        fields = ['id', 'po_number', 'requisition', 'requisition_number',
                  'vendor', 'vendor_name', 'po_date', 'remarks',
                  'total_amount', 'status', 'created_by_name', 'items',
                  'created_at', 'updated_at']
        read_only_fields = ['id', 'po_number', 'total_amount', 'created_at', 'updated_at']


class GeneratePOSerializer(serializers.Serializer):
    """
    Generate PO from comparison selections
    User selects quotation_item IDs from comparison
    """
    requisition = serializers.UUIDField()
    selections = serializers.ListField(
        child=serializers.UUIDField(),
        help_text="List of quotation_item IDs"
    )
    po_date = serializers.DateField()
    remarks = serializers.CharField(required=False, allow_blank=True)

    def validate_requisition(self, value):
        try:
            Requisition.objects.get(id=value)
        except Requisition.DoesNotExist:
            raise serializers.ValidationError("Requisition not found")
        return value

    def validate_selections(self, value):
        if not value:
            raise serializers.ValidationError("Select at least one item")

        # Verify all quotation items exist
        for item_id in value:
            try:
                VendorQuotationItem.objects.get(id=item_id)
            except VendorQuotationItem.DoesNotExist:
                raise serializers.ValidationError(f"Quotation item {item_id} not found")

        return value

    def create(self, validated_data):
        selections = validated_data['selections']
        requisition = Requisition.objects.get(id=validated_data['requisition'])

        # Group by vendor
        vendor_groups = defaultdict(list)

        for item_id in selections:
            q_item = VendorQuotationItem.objects.select_related(
                'quotation__assignment__vendor', 'product'
            ).get(id=item_id)

            vendor = q_item.quotation.assignment.vendor
            vendor_groups[vendor.id].append(q_item)

        # Create one PO per vendor
        pos = []

        for vendor_id, items in vendor_groups.items():
            vendor = Vendor.objects.get(id=vendor_id)

            po = PurchaseOrder.objects.create(
                requisition=requisition,
                vendor=vendor,
                po_date=validated_data['po_date'],
                remarks=validated_data.get('remarks', ''),
                created_by=validated_data['created_by']
            )

            for q_item in items:
                PurchaseOrderItem.objects.create(
                    po=po,
                    quotation_item=q_item,
                    product=q_item.product,
                    quantity=q_item.quantity,
                    rate=q_item.quoted_rate
                )

            po.calculate_total()
            pos.append(po)

        return pos

    def to_representation(self, instance):
        return PurchaseOrderSerializer(instance, many=True).data
