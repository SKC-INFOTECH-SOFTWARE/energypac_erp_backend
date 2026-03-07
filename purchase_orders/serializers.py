from rest_framework import serializers
from .models import PurchaseOrder, PurchaseOrderItem
from requisitions.models import Requisition, VendorQuotationItem
from vendors.models import Vendor
from collections import defaultdict


class PurchaseOrderItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.item_name', read_only=True)
    product_code = serializers.CharField(source='product.item_code', read_only=True)
    hsn_code     = serializers.CharField(source='product.hsn_code',  read_only=True)
    unit         = serializers.CharField(source='product.unit',      read_only=True)

    class Meta:
        model  = PurchaseOrderItem
        fields = [
            'id', 'product', 'product_name', 'product_code', 'hsn_code',
            'unit', 'quantity', 'rate', 'amount', 'is_received',
        ]
        read_only_fields = ['id', 'amount']


class PurchaseOrderSerializer(serializers.ModelSerializer):
    items             = PurchaseOrderItemSerializer(many=True, read_only=True)
    vendor_name       = serializers.CharField(source='vendor.vendor_name',             read_only=True)
    requisition_number = serializers.CharField(source='requisition.requisition_number', read_only=True)
    created_by_name   = serializers.CharField(source='created_by.get_full_name',       read_only=True)
    cancelled_by_name = serializers.SerializerMethodField()

    class Meta:
        model  = PurchaseOrder
        fields = [
            'id', 'po_number', 'requisition', 'requisition_number',
            'vendor', 'vendor_name', 'po_date', 'remarks',
            # Amounts
            'items_total', 'freight_cost', 'total_amount',
            'status',
            'cancellation_reason', 'cancelled_by', 'cancelled_by_name', 'cancelled_at',
            'created_by_name', 'items',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'po_number', 'items_total', 'total_amount',
            'cancellation_reason', 'cancelled_by', 'cancelled_at',
            'created_at', 'updated_at',
        ]

    def get_cancelled_by_name(self, obj):
        if obj.cancelled_by:
            return obj.cancelled_by.get_full_name()
        return None


class GeneratePOSerializer(serializers.Serializer):
    """
    Generate PO from comparison selections.
    User selects quotation_item IDs and can specify an optional freight cost
    per vendor group (one PO per vendor).
    """
    requisition  = serializers.UUIDField()
    selections   = serializers.ListField(
        child=serializers.UUIDField(),
        help_text="List of quotation_item IDs"
    )
    po_date      = serializers.DateField()
    remarks      = serializers.CharField(required=False, allow_blank=True)

    # Key addition: per-vendor freight costs
    # Format: [{"vendor_id": "uuid", "freight_cost": 500.00}, ...]
    # If a vendor is not listed here, freight defaults to 0.
    freight_costs = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        default=list,
        help_text=(
            "Optional per-vendor freight costs. "
            "Example: [{\"vendor_id\": \"uuid\", \"freight_cost\": 500.00}]"
        )
    )

    def validate_requisition(self, value):
        try:
            Requisition.objects.get(id=value)
        except Requisition.DoesNotExist:
            raise serializers.ValidationError("Requisition not found")
        return value

    def validate_selections(self, value):
        if not value:
            raise serializers.ValidationError("Select at least one item")

        for item_id in value:
            try:
                VendorQuotationItem.objects.get(id=item_id)
            except VendorQuotationItem.DoesNotExist:
                raise serializers.ValidationError(f"Quotation item {item_id} not found")

        return value

    def validate_freight_costs(self, value):
        for entry in value:
            if 'vendor_id' not in entry:
                raise serializers.ValidationError("Each freight_costs entry must have 'vendor_id'")
            if 'freight_cost' not in entry:
                raise serializers.ValidationError("Each freight_costs entry must have 'freight_cost'")
            try:
                float(entry['freight_cost'])
            except (TypeError, ValueError):
                raise serializers.ValidationError("freight_cost must be a numeric value")
        return value

    def create(self, validated_data):
        from decimal import Decimal

        selections    = validated_data['selections']
        requisition   = Requisition.objects.get(id=validated_data['requisition'])
        freight_map   = {
            str(e['vendor_id']): Decimal(str(e['freight_cost']))
            for e in validated_data.get('freight_costs', [])
        }

        # Group quotation items by vendor
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
            vendor        = Vendor.objects.get(id=vendor_id)
            freight_cost  = freight_map.get(str(vendor_id), Decimal('0'))

            po = PurchaseOrder.objects.create(
                requisition  = requisition,
                vendor       = vendor,
                po_date      = validated_data['po_date'],
                remarks      = validated_data.get('remarks', ''),
                freight_cost = freight_cost,
                created_by   = validated_data['created_by']
            )

            for q_item in items:
                PurchaseOrderItem.objects.create(
                    po             = po,
                    quotation_item = q_item,
                    product        = q_item.product,
                    quantity       = q_item.quantity,
                    rate           = q_item.quoted_rate
                )

            po.calculate_total()   # sets items_total and total_amount
            pos.append(po)

        return pos

    def to_representation(self, instance):
        return PurchaseOrderSerializer(instance, many=True).data
