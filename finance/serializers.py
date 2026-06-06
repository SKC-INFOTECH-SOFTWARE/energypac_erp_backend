from rest_framework import serializers
from .models import PurchasePayment, PIPayment, AdvancePayment
from purchase_orders.models import PurchaseOrder, PurchaseOrderItem
from sales.models import ProformaInvoice
from decimal import Decimal


# ─────────────────────────────────────────────────────────────────────────────
# Purchase Payment Serializers (Outgoing payments to vendors)
# ─────────────────────────────────────────────────────────────────────────────

class PurchasePaymentSerializer(serializers.ModelSerializer):
    recorded_by_name     = serializers.CharField(source='recorded_by.get_full_name', read_only=True)
    payment_mode_display = serializers.CharField(source='get_payment_mode_display', read_only=True)
    po_number            = serializers.CharField(source='purchase_order.po_number', read_only=True)
    vendor_name          = serializers.CharField(source='purchase_order.vendor.vendor_name', read_only=True)

    class Meta:
        model  = PurchasePayment
        fields = [
            'id', 'purchase_order', 'po_number', 'vendor_name',
            'payment_number', 'amount', 'payment_date',
            'payment_mode', 'payment_mode_display', 'reference_number',
            'remarks', 'payment_status',
            'total_paid_after', 'balance_after',
            'recorded_by', 'recorded_by_name', 'created_at',
        ]
        read_only_fields = fields


# ─────────────────────────────────────────────────────────────────────────────
# Purchase Order summary for finance views
# ─────────────────────────────────────────────────────────────────────────────

class POItemFinanceSerializer(serializers.ModelSerializer):
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
        read_only_fields = fields


class POFinanceSummarySerializer(serializers.ModelSerializer):
    items              = POItemFinanceSerializer(many=True, read_only=True)
    vendor_name        = serializers.CharField(source='vendor.vendor_name', read_only=True)
    vendor_phone       = serializers.CharField(source='vendor.phone', read_only=True)
    vendor_email       = serializers.CharField(source='vendor.email', read_only=True)
    vendor_gst         = serializers.CharField(source='vendor.gst_number', read_only=True)
    requisition_number = serializers.CharField(source='requisition.requisition_number', read_only=True)
    created_by_name    = serializers.CharField(source='created_by.get_full_name', read_only=True)
    payment_count      = serializers.SerializerMethodField()
    purchased_items_total = serializers.SerializerMethodField()
    purchased_items_count = serializers.SerializerMethodField()
    total_items_count     = serializers.SerializerMethodField()

    balance = serializers.SerializerMethodField()
    total_amount_inr = serializers.SerializerMethodField()
    is_overdue = serializers.SerializerMethodField()

    class Meta:
        model  = PurchaseOrder
        fields = [
            'id', 'po_number', 'requisition', 'requisition_number',
            'vendor', 'vendor_name', 'vendor_phone', 'vendor_email', 'vendor_gst',
            'po_date', 'remarks',
            'currency', 'conversion_rate', 'payment_due_date',
            'items_total',
            'cgst_percentage', 'sgst_percentage', 'igst_percentage',
            'cgst_amount', 'sgst_amount', 'igst_amount',
            'total_amount', 'total_amount_inr',
            'amount_paid', 'balance',
            'purchased_items_total', 'purchased_items_count', 'total_items_count',
            'status', 'payment_count', 'is_overdue',
            'created_by_name', 'items',
            'created_at', 'updated_at',
        ]
        read_only_fields = fields

    def get_balance(self, obj):
        computed = obj.total_amount - obj.amount_paid
        return float(max(computed, Decimal('0')))

    def get_total_amount_inr(self, obj):
        if obj.currency == 'INR' or not obj.conversion_rate:
            return float(obj.total_amount)
        return float(obj.total_amount * obj.conversion_rate)

    def get_is_overdue(self, obj):
        if not obj.payment_due_date:
            return False
        from datetime import date
        return date.today() > obj.payment_due_date and obj.amount_paid < obj.total_amount

    def get_payment_count(self, obj):
        return obj.purchase_payments.count()

    def get_purchased_items_total(self, obj):
        return float(sum(item.amount for item in obj.items.filter(is_received=True)))

    def get_purchased_items_count(self, obj):
        return obj.items.filter(is_received=True).count()

    def get_total_items_count(self, obj):
        return obj.items.count()


# ─────────────────────────────────────────────────────────────────────────────
# PI Payment Serializer (Incoming from clients against Proforma Invoice)
# ─────────────────────────────────────────────────────────────────────────────

class PIPaymentSerializer(serializers.ModelSerializer):
    recorded_by_name     = serializers.CharField(source='recorded_by.get_full_name', read_only=True)
    payment_mode_display = serializers.CharField(source='get_payment_mode_display', read_only=True)
    pi_number            = serializers.CharField(source='proforma_invoice.pi_number', read_only=True)

    class Meta:
        model  = PIPayment
        fields = [
            'id', 'proforma_invoice', 'pi_number',
            'payment_number', 'amount', 'payment_date',
            'payment_mode', 'payment_mode_display', 'reference_number',
            'remarks', 'payment_status',
            'total_paid_after', 'balance_after',
            'recorded_by', 'recorded_by_name', 'created_at',
        ]
        read_only_fields = fields


class PIFinanceSummarySerializer(serializers.ModelSerializer):
    requisition_number = serializers.SerializerMethodField()
    created_by_name    = serializers.CharField(source='created_by.get_full_name', read_only=True)
    payment_count      = serializers.SerializerMethodField()
    balance            = serializers.SerializerMethodField()
    grand_total_inr    = serializers.SerializerMethodField()
    is_overdue         = serializers.SerializerMethodField()

    class Meta:
        model  = ProformaInvoice
        fields = [
            'id', 'pi_number', 'requisition', 'requisition_number',
            'pi_date', 'currency', 'conversion_rate', 'payment_due_date',
            'grand_total', 'grand_total_inr', 'amount_received', 'balance',
            'status', 'payment_count', 'is_overdue',
            'created_by_name',
            'created_at', 'updated_at',
        ]
        read_only_fields = fields

    def get_requisition_number(self, obj):
        if obj.requisition:
            return obj.requisition.requisition_number
        return None

    def get_balance(self, obj):
        return float(max(obj.grand_total - obj.amount_received, Decimal('0')))

    def get_grand_total_inr(self, obj):
        if obj.currency == 'INR' or not obj.conversion_rate:
            return float(obj.grand_total)
        return float(obj.grand_total * obj.conversion_rate)

    def get_payment_count(self, obj):
        return obj.pi_payments.count()

    def get_is_overdue(self, obj):
        if not obj.payment_due_date:
            return False
        from datetime import date
        return date.today() > obj.payment_due_date and obj.amount_received < obj.grand_total


# ─────────────────────────────────────────────────────────────────────────────
# Advance Payment Serializer
# ─────────────────────────────────────────────────────────────────────────────

class AdvancePaymentSerializer(serializers.ModelSerializer):
    recorded_by_name     = serializers.CharField(source='recorded_by.get_full_name', read_only=True)
    payment_mode_display = serializers.CharField(source='get_payment_mode_display', read_only=True)
    pi_number            = serializers.CharField(source='proforma_invoice.pi_number', read_only=True)

    class Meta:
        model  = AdvancePayment
        fields = [
            'id', 'advance_number', 'client_name',
            'proforma_invoice', 'pi_number',
            'amount', 'currency', 'conversion_rate', 'amount_inr',
            'amount_used', 'remaining',
            'payment_date', 'payment_mode', 'payment_mode_display',
            'reference_number', 'remarks', 'status',
            'recorded_by', 'recorded_by_name', 'created_at',
        ]
        read_only_fields = [
            'id', 'advance_number', 'currency', 'conversion_rate',
            'amount_inr', 'remaining',
            'recorded_by', 'created_at',
        ]

    def create(self, validated_data):
        pi = validated_data['proforma_invoice']
        validated_data['currency'] = pi.currency
        validated_data['conversion_rate'] = pi.conversion_rate
        return super().create(validated_data)
