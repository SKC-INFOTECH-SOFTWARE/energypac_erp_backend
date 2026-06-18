from rest_framework import serializers
from django.db import transaction
from decimal import Decimal
from .models import (
    TransportEntry, TransportCostItem,
    Transporter, TransportConsignmentItem, TransportPayment,
)
from purchase_orders.models import PurchaseOrder, PurchaseOrderItem
from sales.models import ProformaInvoice, ProformaInvoiceItem


class TransporterSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    entry_count = serializers.SerializerMethodField()

    class Meta:
        model = Transporter
        fields = [
            'id', 'transporter_code', 'name', 'contact_person',
            'phone', 'email', 'address', 'gst_number', 'pan_number',
            'is_active', 'entry_count',
            'created_by', 'created_by_name', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'transporter_code', 'created_by', 'created_at', 'updated_at']

    def get_entry_count(self, obj):
        return obj.transport_entries.exclude(status='CANCELLED').count()


class TransportCostItemSerializer(serializers.ModelSerializer):
    cost_type_display = serializers.CharField(source='get_cost_type_display', read_only=True)

    class Meta:
        model = TransportCostItem
        fields = [
            'id', 'cost_type', 'cost_type_display',
            'description', 'amount', 'remarks',
        ]
        read_only_fields = ['id']


class TransportConsignmentItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.item_name', read_only=True)
    product_code = serializers.CharField(source='product.item_code', read_only=True)
    unit = serializers.CharField(source='product.unit', read_only=True)

    class Meta:
        model = TransportConsignmentItem
        fields = [
            'id', 'po_item', 'pi_item', 'product',
            'product_name', 'product_code', 'unit',
            'quantity', 'remarks',
        ]
        read_only_fields = ['id']


class TransportPaymentSerializer(serializers.ModelSerializer):
    payment_mode_display = serializers.CharField(source='get_payment_mode_display', read_only=True)
    recorded_by_name = serializers.CharField(source='recorded_by.get_full_name', read_only=True)

    class Meta:
        model = TransportPayment
        fields = [
            'id', 'transport_entry', 'payment_number', 'amount',
            'payment_date', 'payment_mode', 'payment_mode_display',
            'reference_number', 'remarks',
            'total_paid_after', 'balance_after',
            'recorded_by', 'recorded_by_name', 'created_at',
        ]
        read_only_fields = fields


class TransportEntrySerializer(serializers.ModelSerializer):
    cost_items = TransportCostItemSerializer(many=True, read_only=True)
    consignment_items = TransportConsignmentItemSerializer(many=True, read_only=True)
    po_number = serializers.CharField(source='purchase_order.po_number', read_only=True, allow_null=True)
    vendor_name = serializers.SerializerMethodField()
    pi_number = serializers.CharField(source='proforma_invoice.pi_number', read_only=True, allow_null=True)
    client_name = serializers.SerializerMethodField()
    transporter_code = serializers.CharField(source='transporter.transporter_code', read_only=True, allow_null=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    payment_status_display = serializers.CharField(source='get_payment_status_display', read_only=True)
    direction = serializers.CharField(read_only=True)
    cost_breakdown = serializers.SerializerMethodField()

    class Meta:
        model = TransportEntry
        fields = [
            'id', 'transport_number', 'direction',
            'purchase_order', 'po_number', 'vendor_name',
            'proforma_invoice', 'pi_number', 'client_name',
            'transporter', 'transporter_code',
            'transporter_name', 'transporter_contact',
            'vehicle_number', 'driver_name', 'driver_contact',
            'lr_number', 'invoice_reference',
            'dispatch_date', 'expected_delivery_date', 'actual_delivery_date',
            'dispatch_from', 'dispatch_to',
            'total_cost', 'amount_paid', 'balance',
            'payment_status', 'payment_status_display',
            'status', 'status_display', 'remarks',
            'cost_breakdown', 'cost_items', 'consignment_items',
            'created_by', 'created_by_name', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'transport_number', 'total_cost',
            'amount_paid', 'balance', 'payment_status',
            'created_by', 'created_at', 'updated_at',
        ]

    def get_vendor_name(self, obj):
        if obj.purchase_order:
            return obj.purchase_order.vendor.vendor_name
        return None

    def get_client_name(self, obj):
        pi = obj.proforma_invoice
        if not pi:
            return None
        if pi.consignee:
            return pi.consignee.split('\n')[0].strip()
        req = getattr(pi, 'requisition', None)
        cq = getattr(req, 'client_query', None) if req else None
        if cq:
            return cq.client_name
        return None

    def get_cost_breakdown(self, obj):
        breakdown = {}
        for item in obj.cost_items.all():
            label = item.get_cost_type_display()
            breakdown[label] = breakdown.get(label, 0) + float(item.amount)
        return breakdown


class CostItemInputSerializer(serializers.Serializer):
    id = serializers.UUIDField(required=False, allow_null=True)
    cost_type = serializers.ChoiceField(choices=TransportCostItem.COST_TYPE_CHOICES)
    description = serializers.CharField(required=False, allow_blank=True, default='')
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    remarks = serializers.CharField(required=False, allow_blank=True, default='')


class ConsignmentItemInputSerializer(serializers.Serializer):
    id = serializers.UUIDField(required=False, allow_null=True)
    po_item = serializers.UUIDField(required=False, allow_null=True)
    pi_item = serializers.UUIDField(required=False, allow_null=True)
    quantity = serializers.DecimalField(max_digits=10, decimal_places=2)
    remarks = serializers.CharField(required=False, allow_blank=True, default='')


def _shipped_qty_excluding(source_item, exclude_entry_id=None):
    """Sum of consignment quantities already shipped for a PO/PI line, excluding cancelled
    entries and optionally the entry currently being edited."""
    from django.db.models import Sum
    qs = source_item.consignment_items.exclude(
        transport_entry__status='CANCELLED'
    )
    if exclude_entry_id:
        qs = qs.exclude(transport_entry_id=exclude_entry_id)
    return qs.aggregate(s=Sum('quantity'))['s'] or Decimal('0')


def _resolve_and_validate_consignment(items_data, purchase_order, proforma_invoice, exclude_entry_id=None):
    """Resolve PO/PI line items, enforce pending-qty limits, return list of
    (source_kind, source_item, quantity, remarks) tuples."""
    resolved = []
    # aggregate requested qty per source line (so two rows on the same line are summed)
    requested = {}
    for row in items_data:
        po_item_id = row.get('po_item')
        pi_item_id = row.get('pi_item')
        qty = row.get('quantity') or Decimal('0')
        if qty <= 0:
            raise serializers.ValidationError("Consignment quantity must be greater than zero.")

        if purchase_order is not None:
            if not po_item_id:
                raise serializers.ValidationError("po_item is required for a purchase-order consignment.")
            try:
                src = PurchaseOrderItem.objects.get(id=po_item_id, po=purchase_order)
            except PurchaseOrderItem.DoesNotExist:
                raise serializers.ValidationError("Consignment item does not belong to the selected Purchase Order.")
            kind = 'PO'
        else:
            if not pi_item_id:
                raise serializers.ValidationError("pi_item is required for a proforma-invoice consignment.")
            try:
                src = ProformaInvoiceItem.objects.get(id=pi_item_id, proforma_invoice=proforma_invoice)
            except ProformaInvoiceItem.DoesNotExist:
                raise serializers.ValidationError("Consignment item does not belong to the selected Proforma Invoice.")
            kind = 'PI'

        requested[str(src.id)] = requested.get(str(src.id), Decimal('0')) + qty
        resolved.append((kind, src, qty, row.get('remarks', '')))

    # validate against ordered qty
    for src_id, total_req in requested.items():
        if resolved and resolved[0][0] == 'PO':
            src = PurchaseOrderItem.objects.get(id=src_id)
        else:
            src = ProformaInvoiceItem.objects.get(id=src_id)
        already = _shipped_qty_excluding(src, exclude_entry_id)
        ordered = src.quantity or Decimal('0')
        pending = ordered - already
        if total_req > pending:
            raise serializers.ValidationError(
                f"{src.product.item_name}: trying to ship {total_req} but only {pending} pending "
                f"(ordered {ordered}, already shipped {already})."
            )
    return resolved


class TransportEntryCreateSerializer(serializers.ModelSerializer):
    cost_items = CostItemInputSerializer(many=True)
    consignment_items = ConsignmentItemInputSerializer(many=True, required=False)

    class Meta:
        model = TransportEntry
        fields = [
            'purchase_order', 'proforma_invoice', 'transporter',
            'transporter_name', 'transporter_contact',
            'vehicle_number', 'driver_name', 'driver_contact',
            'lr_number', 'invoice_reference',
            'dispatch_date', 'expected_delivery_date', 'actual_delivery_date',
            'dispatch_from', 'dispatch_to',
            'status', 'remarks', 'cost_items', 'consignment_items',
        ]
        extra_kwargs = {
            'purchase_order': {'required': False, 'allow_null': True},
            'proforma_invoice': {'required': False, 'allow_null': True},
            'transporter': {'required': False, 'allow_null': True},
        }

    def validate(self, data):
        if not data.get('purchase_order') and not data.get('proforma_invoice'):
            raise serializers.ValidationError(
                "Either purchase_order or proforma_invoice is required"
            )
        if data.get('purchase_order') and data.get('proforma_invoice'):
            raise serializers.ValidationError(
                "A transport entry is either inbound (PO) or outbound (PI), not both."
            )

        # If a transporter master is selected, auto-fill the snapshot name/contact.
        transporter = data.get('transporter')
        if transporter and not data.get('transporter_name'):
            data['transporter_name'] = transporter.name
            if not data.get('transporter_contact'):
                data['transporter_contact'] = transporter.phone

        # validate consignment items against pending qty (multiple entries now allowed per PO/PI)
        consignment = data.get('consignment_items') or []
        self._resolved_consignment = _resolve_and_validate_consignment(
            consignment, data.get('purchase_order'), data.get('proforma_invoice')
        )
        return data

    def validate_cost_items(self, value):
        if not value:
            raise serializers.ValidationError("At least one cost item is required")
        return value

    def create(self, validated_data):
        items_data = validated_data.pop('cost_items')
        validated_data.pop('consignment_items', None)
        resolved = getattr(self, '_resolved_consignment', [])
        with transaction.atomic():
            entry = TransportEntry.objects.create(**validated_data)
            for item_data in items_data:
                item_data.pop('id', None)
                TransportCostItem.objects.create(transport_entry=entry, **item_data)
            for kind, src, qty, remarks in resolved:
                TransportConsignmentItem.objects.create(
                    transport_entry=entry,
                    po_item=src if kind == 'PO' else None,
                    pi_item=src if kind == 'PI' else None,
                    product=src.product,
                    quantity=qty,
                    remarks=remarks or '',
                )
            entry.calculate_total()
        return entry

    def to_representation(self, instance):
        return TransportEntrySerializer(instance).data


class TransportEntryUpdateSerializer(serializers.ModelSerializer):
    cost_items = CostItemInputSerializer(many=True, required=False)
    consignment_items = ConsignmentItemInputSerializer(many=True, required=False)

    class Meta:
        model = TransportEntry
        fields = [
            'transporter', 'transporter_name', 'transporter_contact',
            'vehicle_number', 'driver_name', 'driver_contact',
            'lr_number', 'invoice_reference',
            'dispatch_date', 'expected_delivery_date', 'actual_delivery_date',
            'dispatch_from', 'dispatch_to',
            'status', 'remarks', 'cost_items', 'consignment_items',
        ]
        extra_kwargs = {
            'transporter': {'required': False, 'allow_null': True},
        }

    def validate(self, data):
        # Cancellation must go through the dedicated, password-confirmed `cancel` action
        if data.get('status') == 'CANCELLED' and self.instance.status != 'CANCELLED':
            raise serializers.ValidationError(
                "Use the Cancel action to cancel a shipment (it requires confirmation)."
            )

        # Freight total can never drop below what has already been paid
        items_data = data.get('cost_items')
        if items_data is not None:
            new_total = sum((Decimal(str(i.get('amount') or 0)) for i in items_data), Decimal('0'))
            already_paid = self.instance.amount_paid or Decimal('0')
            if new_total < already_paid:
                raise serializers.ValidationError(
                    f"Total freight ({new_total}) cannot be less than the amount already paid ({already_paid})."
                )

        consignment = data.get('consignment_items')
        if consignment is not None:
            self._resolved_consignment = _resolve_and_validate_consignment(
                consignment,
                self.instance.purchase_order,
                self.instance.proforma_invoice,
                exclude_entry_id=self.instance.id,
            )
        return data

    def update(self, instance, validated_data):
        items_data = validated_data.pop('cost_items', None)
        consignment_data = validated_data.pop('consignment_items', None)

        with transaction.atomic():
            for attr, value in validated_data.items():
                setattr(instance, attr, value)
            instance.save()

            if items_data is not None:
                existing = {str(item.id): item for item in instance.cost_items.all()}
                submitted_ids = set()

                for item_data in items_data:
                    item_id = item_data.pop('id', None)
                    if item_id and str(item_id) in existing:
                        item = existing[str(item_id)]
                        for attr, value in item_data.items():
                            setattr(item, attr, value)
                        item.save()
                        submitted_ids.add(str(item_id))
                    else:
                        new_item = TransportCostItem.objects.create(
                            transport_entry=instance, **item_data
                        )
                        submitted_ids.add(str(new_item.id))

                for item_id, item in existing.items():
                    if item_id not in submitted_ids:
                        item.delete()

            # consignment items are replaced wholesale (validated already)
            if consignment_data is not None:
                instance.consignment_items.all().delete()
                for kind, src, qty, remarks in getattr(self, '_resolved_consignment', []):
                    TransportConsignmentItem.objects.create(
                        transport_entry=instance,
                        po_item=src if kind == 'PO' else None,
                        pi_item=src if kind == 'PI' else None,
                        product=src.product,
                        quantity=qty,
                        remarks=remarks or '',
                    )

            instance.calculate_total()

        return instance

    def to_representation(self, instance):
        return TransportEntrySerializer(instance).data


class LandedCostItemSerializer(serializers.Serializer):
    item_id = serializers.UUIDField()
    product_code = serializers.CharField()
    product_name = serializers.CharField()
    quantity = serializers.DecimalField(max_digits=10, decimal_places=2)
    unit = serializers.CharField()
    purchase_rate = serializers.DecimalField(max_digits=10, decimal_places=2)
    purchase_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    value_percentage = serializers.DecimalField(max_digits=5, decimal_places=2)
    allocated_transport = serializers.DecimalField(max_digits=12, decimal_places=2)
    landed_cost = serializers.DecimalField(max_digits=12, decimal_places=2)
    landed_rate_per_unit = serializers.DecimalField(max_digits=12, decimal_places=2)
