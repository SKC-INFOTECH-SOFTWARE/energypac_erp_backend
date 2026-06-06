from rest_framework import serializers
from django.db import transaction
from .models import PurchaseOrder, PurchaseOrderItem
from requisitions.models import Requisition, VendorQuotationItem
from inventory.models import Product
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
            'unit', 'quantity', 'rate', 'amount',
            'is_received',
        ]
        read_only_fields = ['id', 'amount']


class PurchaseOrderSerializer(serializers.ModelSerializer):
    items                = PurchaseOrderItemSerializer(many=True, read_only=True)
    vendor_details       = VendorBasicSerializer(source='vendor', read_only=True)
    vendor_name          = serializers.CharField(source='vendor.vendor_name',             read_only=True)
    requisition_number   = serializers.CharField(source='requisition.requisition_number', read_only=True)
    created_by_name      = serializers.CharField(source='created_by.get_full_name',       read_only=True)
    cancelled_by_name    = serializers.SerializerMethodField()
    locked_by_name       = serializers.SerializerMethodField()

    class Meta:
        model  = PurchaseOrder
        fields = [
            'id', 'po_number', 'requisition', 'requisition_number',
            'vendor', 'vendor_name', 'vendor_details',
            'po_date', 'subject', 'project_name', 'bill_to', 'ship_to',
            'terms_and_conditions', 'remarks',
            'currency', 'conversion_rate', 'payment_due_date',
            'items_total',
            'discount_amount',
            'cgst_percentage', 'sgst_percentage', 'igst_percentage',
            'cgst_amount', 'sgst_amount', 'igst_amount',
            'total_amount',
            'amount_paid', 'balance',
            'revision_number', 'is_revised',
            'locked_by', 'locked_by_name', 'locked_at',
            'status',
            'cancellation_reason', 'cancelled_by', 'cancelled_by_name', 'cancelled_at',
            'created_by_name', 'items',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'po_number', 'items_total', 'total_amount',
            'currency', 'conversion_rate',
            'cgst_amount', 'sgst_amount', 'igst_amount',
            'amount_paid', 'balance',
            'revision_number', 'is_revised',
            'locked_by', 'locked_at',
            'cancellation_reason', 'cancelled_by', 'cancelled_at',
            'created_at', 'updated_at',
        ]

    def get_cancelled_by_name(self, obj):
        if obj.cancelled_by:
            return obj.cancelled_by.get_full_name()
        return None

    def get_locked_by_name(self, obj):
        if obj.locked_by:
            return obj.locked_by.get_full_name()
        return None


# ─────────────────────────────────────────────────────────────────────────────
# PO Update Serializer — full edit (items, rates, quantities, GST, etc.)
# ─────────────────────────────────────────────────────────────────────────────

class POItemUpdateSerializer(serializers.Serializer):
    id       = serializers.UUIDField(required=False, allow_null=True)
    product  = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=10, decimal_places=2)
    rate     = serializers.DecimalField(max_digits=10, decimal_places=2)
    remarks  = serializers.CharField(required=False, allow_blank=True, default='')


class PurchaseOrderUpdateSerializer(serializers.ModelSerializer):
    items = POItemUpdateSerializer(many=True, required=False)

    class Meta:
        model  = PurchaseOrder
        fields = [
            'po_date', 'subject', 'project_name', 'bill_to', 'ship_to',
            'terms_and_conditions', 'remarks', 'payment_due_date',
            'conversion_rate',
            'discount_amount',
            'cgst_percentage', 'sgst_percentage', 'igst_percentage',
            'items',
        ]

    def update(self, instance, validated_data):
        items_data = validated_data.pop('items', None)

        with transaction.atomic():
            for attr, value in validated_data.items():
                setattr(instance, attr, value)
            instance.save()

            if items_data is not None:
                existing_items = {str(item.id): item for item in instance.items.all()}
                submitted_ids = set()

                for item_data in items_data:
                    item_id = item_data.get('id')
                    product = Product.objects.get(id=item_data['product'])

                    if item_id and str(item_id) in existing_items:
                        item = existing_items[str(item_id)]
                        if item.is_received:
                            raise serializers.ValidationError(
                                f'Cannot edit item "{product.item_name}" — already received.'
                            )
                        item.product = product
                        item.quantity = item_data['quantity']
                        item.rate = item_data['rate']
                        item.save()
                        submitted_ids.add(str(item_id))
                    else:
                        new_item = PurchaseOrderItem.objects.create(
                            po=instance,
                            quotation_item=instance.items.first().quotation_item if instance.items.exists() else None,
                            product=product,
                            quantity=item_data['quantity'],
                            rate=item_data['rate'],
                        )
                        submitted_ids.add(str(new_item.id))

                for item_id, item in existing_items.items():
                    if item_id not in submitted_ids:
                        if item.is_received:
                            raise serializers.ValidationError(
                                f'Cannot remove item "{item.product.item_name}" — already received.'
                            )
                        item.delete()

            instance.calculate_total()

        return instance

    def to_representation(self, instance):
        return PurchaseOrderSerializer(instance).data


# ─────────────────────────────────────────────────────────────────────────────
# Generate PO from comparison
# ─────────────────────────────────────────────────────────────────────────────

class GeneratePOSerializer(serializers.Serializer):
    """
    Generate PO from comparison selections.
    User selects quotation_item IDs from comparison.
    Separate PO per vendor. GST applied on total selected amount.
    """
    requisition      = serializers.UUIDField()
    selections       = serializers.ListField(
        child=serializers.UUIDField(),
        help_text="List of quotation_item IDs"
    )
    po_date          = serializers.DateField()
    subject          = serializers.CharField(required=False, allow_blank=True, default='')
    project_name     = serializers.CharField(required=False, allow_blank=True, default='')
    bill_to          = serializers.CharField(required=False, allow_blank=True, default='')
    ship_to          = serializers.CharField(required=False, allow_blank=True, default='')
    terms_and_conditions = serializers.ListField(child=serializers.JSONField(), required=False, default=list)
    cgst_percentage  = serializers.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('0'), required=False
    )
    sgst_percentage  = serializers.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('0'), required=False
    )
    igst_percentage  = serializers.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('0'), required=False
    )
    remarks = serializers.CharField(required=False, allow_blank=True)
    discount_amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0'), required=False,
        help_text="Vendor discount in PO currency (subtracted from total). Default 0."
    )
    conversion_rate = serializers.DecimalField(
        max_digits=10, decimal_places=4, required=False, allow_null=True, default=None,
        help_text="Current INR conversion rate (for record only, no conversion applied). Required for non-INR POs."
    )
    payment_due_date = serializers.DateField(required=False, allow_null=True, default=None)

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
        selections  = validated_data['selections']
        requisition = Requisition.objects.get(id=validated_data['requisition'])

        vendor_groups = defaultdict(list)
        for item_id in selections:
            q_item = VendorQuotationItem.objects.select_related(
                'quotation__assignment__vendor', 'product'
            ).get(id=item_id)
            if not q_item.quotation or not q_item.quotation.assignment:
                raise serializers.ValidationError(
                    f"Quotation item {item_id} has no valid quotation or vendor assignment"
                )
            vendor = q_item.quotation.assignment.vendor
            vendor_groups[vendor.id].append(q_item)

        pos = []
        for vendor_id, items in vendor_groups.items():
            vendor = Vendor.objects.get(id=vendor_id)

            first_item = items[0]
            currency = first_item.quotation.currency

            po = PurchaseOrder.objects.create(
                requisition      = requisition,
                vendor           = vendor,
                po_date          = validated_data['po_date'],
                subject          = validated_data.get('subject', ''),
                project_name     = validated_data.get('project_name', ''),
                bill_to          = validated_data.get('bill_to', ''),
                ship_to          = validated_data.get('ship_to', ''),
                terms_and_conditions = validated_data.get('terms_and_conditions', []),
                currency         = currency,
                conversion_rate  = validated_data.get('conversion_rate'),
                payment_due_date = validated_data.get('payment_due_date'),
                discount_amount  = validated_data.get('discount_amount', Decimal('0')),
                cgst_percentage  = validated_data.get('cgst_percentage', Decimal('0')),
                sgst_percentage  = validated_data.get('sgst_percentage', Decimal('0')),
                igst_percentage  = validated_data.get('igst_percentage', Decimal('0')),
                remarks          = validated_data.get('remarks', ''),
                created_by       = validated_data['created_by']
            )

            for q_item in items:
                PurchaseOrderItem.objects.create(
                    po             = po,
                    quotation_item = q_item,
                    product        = q_item.product,
                    quantity       = q_item.quantity,
                    rate           = q_item.quoted_rate,
                )

            po.calculate_total()
            pos.append(po)

        return pos

    def to_representation(self, instance):
        return PurchaseOrderSerializer(instance, many=True).data
