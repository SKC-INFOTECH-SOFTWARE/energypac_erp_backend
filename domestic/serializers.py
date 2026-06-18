from rest_framework import serializers
from django.db import transaction

from .models import TaxInvoice, TaxInvoiceItem, TaxInvoicePayment
from .utils import amount_in_words_inr


_HEADER_FIELDS = [
    'kind',
    'company_name', 'company_address', 'company_gstin', 'company_pan', 'company_iec', 'copy_label',
    'invoice_no', 'invoice_date', 'challan_no', 'challan_date', 'state', 'state_code',
    'vendor_code', 'vehicle_no', 'mode_of_transport', 'place_of_supply',
    'buyers_order_no', 'buyers_order_date', 'work_order_no',
    'bill_to_name', 'bill_to_address', 'bill_to_gstin', 'bill_to_state',
    'ship_to_name', 'ship_to_address', 'ship_to_project', 'ship_to_state',
    'gst_on_reverse_charge', 'bank_name', 'bank_account', 'bank_ifsc', 'terms_of_payment',
]


class TaxInvoiceItemSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(required=False)

    class Meta:
        model = TaxInvoiceItem
        fields = [
            'id', 'pi_item', 'description', 'hs_sac_code', 'quantity', 'unit', 'rate',
            'amount', 'taxable_value',
            'sgst_rate', 'sgst_amount', 'cgst_rate', 'cgst_amount', 'igst_rate', 'igst_amount',
            'total_amount', 'sort_order',
        ]
        read_only_fields = ['amount', 'sgst_amount', 'cgst_amount', 'igst_amount', 'total_amount']


class TaxInvoiceSerializer(serializers.ModelSerializer):
    items = TaxInvoiceItemSerializer(many=True, read_only=True)
    pi_number = serializers.SerializerMethodField()
    kind_display = serializers.CharField(source='get_kind_display', read_only=True)

    def get_pi_number(self, obj):
        return obj.proforma_invoice.pi_number if obj.proforma_invoice else None
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)

    class Meta:
        model = TaxInvoice
        fields = [
            'id', 'ti_number', 'proforma_invoice', 'pi_number', 'kind', 'kind_display',
            *_HEADER_FIELDS[1:],
            'total_amount_before_tax', 'total_tax_amount', 'total_amount_after_tax',
            'amount_paid', 'balance',
            'amount_in_words', 'status', 'created_by', 'created_by_name',
            'created_at', 'updated_at', 'items',
        ]
        read_only_fields = [
            'id', 'ti_number', 'total_amount_before_tax', 'total_tax_amount',
            'total_amount_after_tax', 'amount_paid', 'balance', 'amount_in_words', 'created_by',
            'created_at', 'updated_at',
        ]


class TaxInvoicePaymentSerializer(serializers.ModelSerializer):
    recorded_by_name     = serializers.CharField(source='recorded_by.get_full_name', read_only=True)
    payment_mode_display = serializers.CharField(source='get_payment_mode_display', read_only=True)

    class Meta:
        model = TaxInvoicePayment
        fields = [
            'id', 'payment_number', 'amount', 'payment_date',
            'payment_mode', 'payment_mode_display', 'reference_number', 'remarks',
            'total_paid_after', 'balance_after',
            'recorded_by', 'recorded_by_name', 'created_at',
        ]
        read_only_fields = fields


class TaxInvoiceWriteSerializer(serializers.ModelSerializer):
    items = TaxInvoiceItemSerializer(many=True)

    class Meta:
        model = TaxInvoice
        fields = ['proforma_invoice', *_HEADER_FIELDS, 'items']

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("At least one item is required")
        return value

    def _save_item(self, ti, data, idx):
        data = dict(data)
        data.pop('id', None)
        data.pop('sort_order', None)
        TaxInvoiceItem.objects.create(tax_invoice=ti, sort_order=idx, **data)

    def _finalize(self, ti):
        ti.recalc_totals()
        ti.amount_in_words = amount_in_words_inr(ti.total_amount_after_tax)
        ti.save()

    @transaction.atomic
    def create(self, validated_data):
        items_data = validated_data.pop('items')
        created_by = validated_data.pop('created_by')
        ti = TaxInvoice.objects.create(created_by=created_by, **validated_data)
        for idx, item in enumerate(items_data):
            self._save_item(ti, item, idx)
        self._finalize(ti)
        return ti

    @transaction.atomic
    def update(self, instance, validated_data):
        items_data = validated_data.pop('items', None)
        for attr, val in validated_data.items():
            setattr(instance, attr, val)
        instance.save()
        if items_data is not None:
            instance.items.all().delete()
            for idx, item in enumerate(items_data):
                self._save_item(instance, item, idx)
        self._finalize(instance)
        return instance

    def to_representation(self, instance):
        return TaxInvoiceSerializer(instance, context=self.context).data
