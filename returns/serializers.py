from rest_framework import serializers
from django.db import transaction, models
from decimal import Decimal
from .models import (
    SalesReturn, SalesReturnItem,
    PurchaseReturn, PurchaseReturnItem,
    RETURN_REASON_CHOICES, ITEM_CONDITION_CHOICES,
)
from inventory.models import Product
from sales.models import ProformaInvoice, ProformaInvoiceItem
from purchase_orders.models import PurchaseOrder, PurchaseOrderItem


# ── Sales Return ─────────────────────────────────────────────────────────────

class SalesReturnItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.item_name', read_only=True)
    product_code = serializers.CharField(source='product.item_code', read_only=True)
    unit = serializers.CharField(source='product.unit', read_only=True)
    amount = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    reason_display = serializers.CharField(source='get_reason_display', read_only=True)
    condition_display = serializers.CharField(source='get_condition_display', read_only=True)

    class Meta:
        model = SalesReturnItem
        fields = [
            'id', 'product', 'product_name', 'product_code', 'unit',
            'quantity', 'unit_price', 'amount',
            'reason', 'reason_display', 'condition', 'condition_display', 'notes',
        ]
        read_only_fields = ['id', 'amount']


class SalesReturnSerializer(serializers.ModelSerializer):
    items = SalesReturnItemSerializer(many=True, read_only=True)
    pi_number = serializers.CharField(source='proforma_invoice.pi_number', read_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    approved_by_name = serializers.SerializerMethodField()
    total_return_amount_inr = serializers.SerializerMethodField()

    class Meta:
        model = SalesReturn
        fields = [
            'id', 'return_number', 'proforma_invoice', 'pi_number',
            'return_date', 'reason', 'status',
            'credit_note_number', 'total_return_amount', 'total_return_amount_inr',
            'currency', 'conversion_rate', 'notes',
            'created_by', 'created_by_name',
            'approved_by', 'approved_by_name', 'approved_at',
            'items', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'return_number', 'credit_note_number',
            'total_return_amount', 'total_return_amount_inr',
            'approved_by', 'approved_at', 'created_at', 'updated_at',
        ]

    def get_approved_by_name(self, obj):
        return obj.approved_by.get_full_name() if obj.approved_by else None

    def get_total_return_amount_inr(self, obj):
        rate = obj.conversion_rate or Decimal('1')
        if obj.currency == 'INR':
            rate = Decimal('1')
        return float(obj.total_return_amount * rate)


class SalesReturnItemCreateSerializer(serializers.Serializer):
    product = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=10, decimal_places=2)
    unit_price = serializers.DecimalField(max_digits=10, decimal_places=2)
    reason = serializers.ChoiceField(choices=RETURN_REASON_CHOICES, default='OTHER')
    condition = serializers.ChoiceField(choices=ITEM_CONDITION_CHOICES, default='GOOD')
    notes = serializers.CharField(required=False, allow_blank=True, default='')


class SalesReturnCreateSerializer(serializers.Serializer):
    proforma_invoice = serializers.UUIDField()
    return_date = serializers.DateField()
    reason = serializers.CharField(required=False, allow_blank=True, default='')
    notes = serializers.CharField(required=False, allow_blank=True, default='')
    items = SalesReturnItemCreateSerializer(many=True)

    def validate_proforma_invoice(self, value):
        try:
            pi = ProformaInvoice.objects.get(id=value)
        except ProformaInvoice.DoesNotExist:
            raise serializers.ValidationError("Proforma Invoice not found")
        if pi.status != 'ACCEPTED':
            raise serializers.ValidationError("Can only return items from ACCEPTED PI")
        return value

    def validate(self, data):
        pi = ProformaInvoice.objects.get(id=data['proforma_invoice'])
        items = data.get('items', [])
        if not items:
            raise serializers.ValidationError({'items': 'At least one item required'})

        errors = []
        for item in items:
            product = Product.objects.filter(id=item['product']).first()
            if not product:
                errors.append(f"Product {item['product']} not found")
                continue

            pi_item = ProformaInvoiceItem.objects.filter(
                proforma_invoice=pi, product=product
            ).first()
            if not pi_item:
                errors.append(f"{product.item_name} was not in this PI")
                continue

            already_returned = SalesReturnItem.objects.filter(
                sales_return__proforma_invoice=pi,
                product=product,
            ).exclude(
                sales_return__status='CANCELLED'
            ).aggregate(total=models.Sum('quantity'))['total'] or Decimal('0')

            max_returnable = pi_item.quantity - already_returned
            if Decimal(str(item['quantity'])) > max_returnable:
                errors.append(
                    f"{product.item_name}: max returnable {max_returnable} "
                    f"(sold {pi_item.quantity}, already returned {already_returned})"
                )

        if errors:
            raise serializers.ValidationError({'items': ' | '.join(errors)})
        return data

    def create(self, validated_data):
        items_data = validated_data.pop('items')
        pi_id = validated_data.pop('proforma_invoice')
        pi = ProformaInvoice.objects.get(id=pi_id)
        created_by = validated_data.pop('created_by')

        with transaction.atomic():
            sr = SalesReturn.objects.create(
                proforma_invoice=pi,
                created_by=created_by,
                currency=pi.currency,
                conversion_rate=pi.conversion_rate or Decimal('1'),
                **validated_data,
            )
            for item_data in items_data:
                product = Product.objects.get(id=item_data['product'])
                SalesReturnItem.objects.create(
                    sales_return=sr,
                    product=product,
                    quantity=item_data['quantity'],
                    unit_price=item_data['unit_price'],
                    reason=item_data.get('reason', 'OTHER'),
                    condition=item_data.get('condition', 'GOOD'),
                    notes=item_data.get('notes', ''),
                )
            sr.calculate_total()

        return sr

    def to_representation(self, instance):
        return SalesReturnSerializer(instance).data


# ── Purchase Return ──────────────────────────────────────────────────────────

class PurchaseReturnItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.item_name', read_only=True)
    product_code = serializers.CharField(source='product.item_code', read_only=True)
    unit = serializers.CharField(source='product.unit', read_only=True)
    amount = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    reason_display = serializers.CharField(source='get_reason_display', read_only=True)
    condition_display = serializers.CharField(source='get_condition_display', read_only=True)

    class Meta:
        model = PurchaseReturnItem
        fields = [
            'id', 'product', 'product_name', 'product_code', 'unit',
            'quantity', 'unit_price', 'amount',
            'reason', 'reason_display', 'condition', 'condition_display', 'notes',
        ]
        read_only_fields = ['id', 'amount']


class PurchaseReturnSerializer(serializers.ModelSerializer):
    items = PurchaseReturnItemSerializer(many=True, read_only=True)
    po_number = serializers.CharField(source='purchase_order.po_number', read_only=True)
    vendor_name = serializers.SerializerMethodField()
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    approved_by_name = serializers.SerializerMethodField()
    total_return_amount_inr = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseReturn
        fields = [
            'id', 'return_number', 'purchase_order', 'po_number', 'vendor_name',
            'return_date', 'reason', 'status',
            'debit_note_number', 'total_return_amount', 'total_return_amount_inr',
            'currency', 'conversion_rate', 'notes',
            'created_by', 'created_by_name',
            'approved_by', 'approved_by_name', 'approved_at',
            'items', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'return_number', 'debit_note_number',
            'total_return_amount', 'total_return_amount_inr',
            'approved_by', 'approved_at', 'created_at', 'updated_at',
        ]

    def get_vendor_name(self, obj):
        return obj.purchase_order.vendor.vendor_name if obj.purchase_order.vendor else None

    def get_approved_by_name(self, obj):
        return obj.approved_by.get_full_name() if obj.approved_by else None

    def get_total_return_amount_inr(self, obj):
        rate = obj.conversion_rate or Decimal('1')
        if obj.currency == 'INR':
            rate = Decimal('1')
        return float(obj.total_return_amount * rate)


class PurchaseReturnItemCreateSerializer(serializers.Serializer):
    product = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=10, decimal_places=2)
    unit_price = serializers.DecimalField(max_digits=10, decimal_places=2)
    reason = serializers.ChoiceField(choices=RETURN_REASON_CHOICES, default='OTHER')
    condition = serializers.ChoiceField(choices=ITEM_CONDITION_CHOICES, default='GOOD')
    notes = serializers.CharField(required=False, allow_blank=True, default='')


class PurchaseReturnCreateSerializer(serializers.Serializer):
    purchase_order = serializers.UUIDField()
    return_date = serializers.DateField()
    reason = serializers.CharField(required=False, allow_blank=True, default='')
    notes = serializers.CharField(required=False, allow_blank=True, default='')
    items = PurchaseReturnItemCreateSerializer(many=True)

    def validate_purchase_order(self, value):
        try:
            po = PurchaseOrder.objects.get(id=value)
        except PurchaseOrder.DoesNotExist:
            raise serializers.ValidationError("Purchase Order not found")
        if po.status == 'CANCELLED':
            raise serializers.ValidationError("Cannot return items from cancelled PO")
        return value

    def validate(self, data):
        po = PurchaseOrder.objects.get(id=data['purchase_order'])
        items = data.get('items', [])
        if not items:
            raise serializers.ValidationError({'items': 'At least one item required'})

        errors = []
        for item in items:
            product = Product.objects.filter(id=item['product']).first()
            if not product:
                errors.append(f"Product {item['product']} not found")
                continue

            po_item = PurchaseOrderItem.objects.filter(
                po=po, product=product, is_received=True
            ).first()
            if not po_item:
                errors.append(f"{product.item_name} not received in this PO")
                continue

            already_returned = PurchaseReturnItem.objects.filter(
                purchase_return__purchase_order=po,
                product=product,
            ).exclude(
                purchase_return__status='CANCELLED'
            ).aggregate(total=models.Sum('quantity'))['total'] or Decimal('0')

            max_returnable = po_item.quantity - already_returned
            if Decimal(str(item['quantity'])) > max_returnable:
                errors.append(
                    f"{product.item_name}: max returnable {max_returnable} "
                    f"(received {po_item.quantity}, already returned {already_returned})"
                )

        if errors:
            raise serializers.ValidationError({'items': ' | '.join(errors)})
        return data

    def create(self, validated_data):
        items_data = validated_data.pop('items')
        po_id = validated_data.pop('purchase_order')
        po = PurchaseOrder.objects.get(id=po_id)
        created_by = validated_data.pop('created_by')

        with transaction.atomic():
            pr = PurchaseReturn.objects.create(
                purchase_order=po,
                created_by=created_by,
                currency=po.currency,
                conversion_rate=po.conversion_rate or Decimal('1'),
                **validated_data,
            )
            for item_data in items_data:
                product = Product.objects.get(id=item_data['product'])
                PurchaseReturnItem.objects.create(
                    purchase_return=pr,
                    product=product,
                    quantity=item_data['quantity'],
                    unit_price=item_data['unit_price'],
                    reason=item_data.get('reason', 'OTHER'),
                    condition=item_data.get('condition', 'GOOD'),
                    notes=item_data.get('notes', ''),
                )
            pr.calculate_total()

        return pr

    def to_representation(self, instance):
        return PurchaseReturnSerializer(instance).data
