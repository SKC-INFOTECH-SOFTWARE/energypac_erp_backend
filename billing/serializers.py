from rest_framework import serializers
from django.db import transaction
from .models import PIBill, PIBillItem, PIBillPayment
from django.db.models import Q
from sales.models import ProformaInvoice, ProformaInvoiceItem
from inventory.models import Product


# ═════════════════════════════════════════════════════════════════════════════
# PI Bill Serializers (Bill generated from Proforma Invoice)
# ═════════════════════════════════════════════════════════════════════════════

class PIBillItemSerializer(serializers.ModelSerializer):
    product_code = serializers.SerializerMethodField()

    class Meta:
        model  = PIBillItem
        fields = [
            'id', 'pi_item', 'product', 'product_code',
            'item_name', 'hsn_code', 'unit',
            'quantity', 'rate', 'amount',
        ]
        read_only_fields = ['id', 'amount']

    def get_product_code(self, obj):
        return obj.product.item_code if obj.product else ''


class PIBillSerializer(serializers.ModelSerializer):
    items           = PIBillItemSerializer(source='pi_bill_items', many=True, read_only=True)
    pi_number       = serializers.CharField(source='proforma_invoice.pi_number', read_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    total_gst       = serializers.SerializerMethodField()

    class Meta:
        model  = PIBill
        fields = [
            'id', 'bill_number', 'bill_type',
            'proforma_invoice', 'pi_number', 'bill_date',
            'client_name', 'contact_person', 'phone', 'email', 'address',
            'currency', 'conversion_rate',
            'subtotal',
            'cgst_percentage', 'sgst_percentage', 'igst_percentage',
            'cgst_amount', 'sgst_amount', 'igst_amount', 'total_gst',
            'discount_amount',
            'total_amount', 'net_payable',
            'amount_paid', 'balance',
            'remarks', 'status',
            'created_by', 'created_by_name',
            'items',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'bill_number',
            'subtotal', 'cgst_amount', 'sgst_amount', 'igst_amount',
            'total_amount', 'net_payable', 'balance',
            'created_at', 'updated_at',
        ]

    def get_total_gst(self, obj):
        return float(obj.cgst_amount + obj.sgst_amount + obj.igst_amount)


class PIBillPaymentSerializer(serializers.ModelSerializer):
    recorded_by_name = serializers.CharField(source='recorded_by.get_full_name', read_only=True)
    payment_mode_display = serializers.CharField(source='get_payment_mode_display', read_only=True)
    bill_number = serializers.CharField(source='pi_bill.bill_number', read_only=True)

    class Meta:
        model = PIBillPayment
        fields = [
            'id', 'pi_bill', 'bill_number',
            'payment_number', 'amount',
            'payment_date', 'payment_mode', 'payment_mode_display',
            'reference_number', 'remarks',
            'total_paid_after', 'balance_after',
            'recorded_by', 'recorded_by_name', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']


class PIBillItemInputSerializer(serializers.Serializer):
    pi_item   = serializers.UUIDField(required=False, allow_null=True)
    product   = serializers.UUIDField(required=False, allow_null=True)
    item_name = serializers.CharField()
    hsn_code  = serializers.CharField(required=False, allow_blank=True, default='')
    unit      = serializers.CharField(default='PCS')
    quantity  = serializers.DecimalField(max_digits=10, decimal_places=2)
    rate      = serializers.DecimalField(max_digits=10, decimal_places=2)


class PIBillCreateSerializer(serializers.Serializer):
    proforma_invoice = serializers.UUIDField()
    bill_date        = serializers.DateField()
    bill_type        = serializers.ChoiceField(choices=['DOMESTIC', 'INTERNATIONAL'], default='DOMESTIC')

    client_name    = serializers.CharField()
    contact_person = serializers.CharField(required=False, allow_blank=True, default='')
    phone          = serializers.CharField(required=False, allow_blank=True, default='')
    email          = serializers.EmailField(required=False, allow_blank=True, default='')
    address        = serializers.CharField(required=False, allow_blank=True, default='')

    cgst_percentage = serializers.DecimalField(max_digits=5, decimal_places=2, default=0)
    sgst_percentage = serializers.DecimalField(max_digits=5, decimal_places=2, default=0)
    igst_percentage = serializers.DecimalField(max_digits=5, decimal_places=2, default=0)
    discount_amount = serializers.DecimalField(max_digits=12, decimal_places=2, default=0)

    remarks = serializers.CharField(required=False, allow_blank=True, default='')
    items   = PIBillItemInputSerializer(many=True)

    def validate_proforma_invoice(self, value):
        try:
            pi = ProformaInvoice.objects.get(id=value)
        except ProformaInvoice.DoesNotExist:
            raise serializers.ValidationError("Proforma Invoice not found")
        if pi.status == 'CANCELLED':
            raise serializers.ValidationError("Cannot generate bill for cancelled PI")
        existing_bill = PIBill.objects.filter(
            proforma_invoice=pi
        ).exclude(status='CANCELLED').first()
        if existing_bill:
            raise serializers.ValidationError(
                f"A bill ({existing_bill.bill_number}) has already been generated for this PI. "
                f"Duplicate bills are not allowed."
            )
        return value

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("At least one item is required")
        return value

    def create(self, validated_data):
        items_data = validated_data.pop('items')
        pi = ProformaInvoice.objects.get(id=validated_data.pop('proforma_invoice'))
        created_by = validated_data.pop('created_by')

        with transaction.atomic():
            bill = PIBill.objects.create(
                proforma_invoice=pi,
                bill_date=validated_data['bill_date'],
                bill_type=validated_data.get('bill_type', 'DOMESTIC'),
                client_name=validated_data['client_name'],
                contact_person=validated_data.get('contact_person', ''),
                phone=validated_data.get('phone', ''),
                email=validated_data.get('email', ''),
                address=validated_data.get('address', ''),
                currency=pi.currency,
                conversion_rate=pi.conversion_rate,
                cgst_percentage=validated_data.get('cgst_percentage', 0),
                sgst_percentage=validated_data.get('sgst_percentage', 0),
                igst_percentage=validated_data.get('igst_percentage', 0),
                discount_amount=validated_data.get('discount_amount', 0),
                remarks=validated_data.get('remarks', ''),
                created_by=created_by,
            )

            for item_data in items_data:
                pi_item_id = item_data.get('pi_item')
                product_id = item_data.get('product')

                pi_item = None
                product = None
                if pi_item_id:
                    pi_item = ProformaInvoiceItem.objects.get(id=pi_item_id)
                    product = pi_item.product
                elif product_id:
                    product = Product.objects.get(id=product_id)

                PIBillItem.objects.create(
                    pi_bill=bill,
                    pi_item=pi_item,
                    product=product,
                    item_name=item_data['item_name'],
                    hsn_code=item_data.get('hsn_code', ''),
                    unit=item_data.get('unit', 'PCS'),
                    quantity=item_data['quantity'],
                    rate=item_data['rate'],
                )

            bill.calculate_totals()

        return bill

    def to_representation(self, instance):
        return PIBillSerializer(instance).data
