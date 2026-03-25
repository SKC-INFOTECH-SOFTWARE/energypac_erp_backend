from rest_framework import serializers
from .models import PurchaseOrder, PurchaseOrderItem
from requisitions.models import Requisition, VendorQuotationItem
from vendors.models import Vendor
from collections import defaultdict
from decimal import Decimal


class VendorBasicSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Vendor
        fields = ['phone', 'email', 'address', 'gst_number', 'pan_number','bank_account_number','bank_name','ifsc_code','account_name']


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
    items                = PurchaseOrderItemSerializer(many=True, read_only=True)
    vendor_details       = VendorBasicSerializer(source='vendor', read_only=True)
    vendor_name          = serializers.CharField(source='vendor.vendor_name',             read_only=True)
    requisition_number   = serializers.CharField(source='requisition.requisition_number', read_only=True)
    created_by_name      = serializers.CharField(source='created_by.get_full_name',       read_only=True)
    cancelled_by_name    = serializers.SerializerMethodField()

    class Meta:
        model  = PurchaseOrder
        fields = [
            'id', 'po_number', 'requisition', 'requisition_number',
            'vendor', 'vendor_name', 'vendor_details',
            'po_date', 'remarks',
            'items_total', 'freight_cost', 'total_amount',
            'amount_paid', 'balance',
            'status',
            'cancellation_reason', 'cancelled_by', 'cancelled_by_name', 'cancelled_at',
            'created_by_name', 'items',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'po_number', 'items_total', 'total_amount',
            'amount_paid', 'balance',
            'cancellation_reason', 'cancelled_by', 'cancelled_at',
            'created_at', 'updated_at',
        ]

    def get_cancelled_by_name(self, obj):
        if obj.cancelled_by:
            return obj.cancelled_by.get_full_name()
        return None


class FreightCostItemSerializer(serializers.Serializer):
    vendor_id    = serializers.UUIDField()
    freight_cost = serializers.DecimalField(max_digits=12, decimal_places=2)


class GeneratePOSerializer(serializers.Serializer):
    """
    Generate PO from comparison selections.
    User selects quotation_item IDs from comparison.

    Fields
    ------
    freight_costs : Optional list of {vendor_id, freight_cost} objects.
                    Each entry sets the freight cost for that vendor's PO.
                    Vendors not listed default to 0.
    freight_cost  : Optional flat freight charge (INR). If provided and
                    freight_costs is not, this value is applied to ALL POs.
    """
    requisition   = serializers.UUIDField()
    selections    = serializers.ListField(
        child=serializers.UUIDField(),
        help_text="List of quotation_item IDs"
    )
    po_date       = serializers.DateField()
    freight_costs = FreightCostItemSerializer(
        many=True, required=False, default=[],
        help_text="Per-vendor freight costs: [{vendor_id, freight_cost}, ...]"
    )
    freight_cost  = serializers.DecimalField(
        max_digits=12, decimal_places=2,
        default=Decimal('0'),
        required=False,
        help_text="Flat freight cost applied to all POs (fallback if freight_costs not provided)."
    )
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

        for item_id in value:
            try:
                VendorQuotationItem.objects.get(id=item_id)
            except VendorQuotationItem.DoesNotExist:
                raise serializers.ValidationError(f"Quotation item {item_id} not found")

        return value

    def create(self, validated_data):
        selections       = validated_data['selections']
        requisition      = Requisition.objects.get(id=validated_data['requisition'])
        flat_freight_cost = validated_data.get('freight_cost', Decimal('0'))

        # Build per-vendor freight cost lookup from the freight_costs array
        freight_costs_list = validated_data.get('freight_costs', [])
        vendor_freight_map = {
            str(entry['vendor_id']): entry['freight_cost']
            for entry in freight_costs_list
        }

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

            # Use per-vendor freight cost if available, otherwise fall back to flat value
            vendor_freight = vendor_freight_map.get(str(vendor_id), flat_freight_cost)

            po = PurchaseOrder.objects.create(
                requisition  = requisition,
                vendor       = vendor,
                po_date      = validated_data['po_date'],
                freight_cost = vendor_freight,
                remarks      = validated_data.get('remarks', ''),
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

            # calculate_total() computes items_total + freight_cost = total_amount
            po.calculate_total()
            pos.append(po)

        return pos

    def to_representation(self, instance):
        return PurchaseOrderSerializer(instance, many=True).data
