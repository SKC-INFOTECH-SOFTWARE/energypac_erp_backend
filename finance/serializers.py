from rest_framework import serializers
from .models import PurchasePayment, IncomingPayment
from purchase_orders.models import PurchaseOrder, PurchaseOrderItem
from billing.models import Bill, BillItem
from work_orders.models import WorkOrder
from decimal import Decimal


# ─────────────────────────────────────────────────────────────────────────────
# Purchase Payment Serializers (Outgoing)
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
# Incoming Payment Serializers (From clients)
# ─────────────────────────────────────────────────────────────────────────────

class IncomingPaymentSerializer(serializers.ModelSerializer):
    recorded_by_name     = serializers.CharField(source='recorded_by.get_full_name', read_only=True)
    payment_mode_display = serializers.CharField(source='get_payment_mode_display', read_only=True)
    bill_number          = serializers.CharField(source='bill.bill_number', read_only=True)
    client_name          = serializers.CharField(source='bill.client_name', read_only=True)
    wo_number            = serializers.CharField(source='bill.work_order.wo_number', read_only=True)

    class Meta:
        model  = IncomingPayment
        fields = [
            'id', 'bill', 'bill_number', 'client_name', 'wo_number',
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
    """Shows PO items with purchased status and price info."""
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
    """Purchase Order summary for the finance/accounts section."""
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

    # FIX (Issue 3): always compute balance from total_amount - amount_paid
    # so old POs (where stored balance=0) show the correct outstanding amount
    balance = serializers.SerializerMethodField()

    class Meta:
        model  = PurchaseOrder
        fields = [
            'id', 'po_number', 'requisition', 'requisition_number',
            'vendor', 'vendor_name', 'vendor_phone', 'vendor_email', 'vendor_gst',
            'po_date', 'remarks',
            'items_total', 'freight_cost', 'total_amount',
            'amount_paid', 'balance',
            'purchased_items_total', 'purchased_items_count', 'total_items_count',
            'status', 'payment_count',
            'created_by_name', 'items',
            'created_at', 'updated_at',
        ]
        read_only_fields = fields

    def get_balance(self, obj):
        """Always compute from live values — never trust the stored balance field."""
        computed = obj.total_amount - obj.amount_paid
        return float(max(computed, Decimal('0')))

    def get_payment_count(self, obj):
        return obj.purchase_payments.count()

    def get_purchased_items_total(self, obj):
        """Total amount of only the items marked as received/purchased."""
        return float(
            sum(item.amount for item in obj.items.filter(is_received=True))
        )

    def get_purchased_items_count(self, obj):
        return obj.items.filter(is_received=True).count()

    def get_total_items_count(self, obj):
        return obj.items.count()


# ─────────────────────────────────────────────────────────────────────────────
# Bill summary for finance views
# ─────────────────────────────────────────────────────────────────────────────

class BillItemFinanceSerializer(serializers.ModelSerializer):
    class Meta:
        model  = BillItem
        fields = [
            'id', 'item_code', 'item_name', 'hsn_code', 'unit',
            'ordered_quantity', 'delivered_quantity', 'pending_quantity',
            'rate', 'amount',
        ]
        read_only_fields = fields


class BillFinanceSummarySerializer(serializers.ModelSerializer):
    """Bill summary for the finance/accounts section."""
    items           = BillItemFinanceSerializer(many=True, read_only=True)
    wo_number       = serializers.CharField(source='work_order.wo_number', read_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    total_gst       = serializers.SerializerMethodField()
    payment_count   = serializers.SerializerMethodField()

    # FIX (Issue 3): always compute balance from net_payable - amount_paid
    balance = serializers.SerializerMethodField()

    class Meta:
        model  = Bill
        fields = [
            'id', 'bill_number', 'bill_type',
            'work_order', 'wo_number', 'bill_date',
            'client_name', 'contact_person', 'phone', 'email', 'address',
            'subtotal',
            'cgst_percentage', 'sgst_percentage', 'igst_percentage',
            'cgst_amount', 'sgst_amount', 'igst_amount', 'total_gst',
            'total_amount', 'freight_cost',
            'advance_deducted', 'net_payable',
            'amount_paid', 'balance',
            'payment_count', 'status',
            'created_by_name', 'items',
            'created_at', 'updated_at',
        ]
        read_only_fields = fields

    def get_balance(self, obj):
        """Always compute from live values — never trust the stored balance field."""
        computed = obj.net_payable - obj.amount_paid
        return float(max(computed, Decimal('0')))

    def get_total_gst(self, obj):
        return float(obj.cgst_amount + obj.sgst_amount + obj.igst_amount)

    def get_payment_count(self, obj):
        return obj.incoming_payments.count()
