from rest_framework import serializers
from django.db import transaction
from decimal import Decimal
from .models import TransportEntry, TransportCostItem
from purchase_orders.models import PurchaseOrder
from sales.models import ProformaInvoice


class TransportCostItemSerializer(serializers.ModelSerializer):
    cost_type_display = serializers.CharField(source='get_cost_type_display', read_only=True)

    class Meta:
        model = TransportCostItem
        fields = [
            'id', 'cost_type', 'cost_type_display',
            'description', 'amount', 'remarks',
        ]
        read_only_fields = ['id']


class TransportEntrySerializer(serializers.ModelSerializer):
    cost_items = TransportCostItemSerializer(many=True, read_only=True)
    po_number = serializers.CharField(source='purchase_order.po_number', read_only=True, allow_null=True)
    vendor_name = serializers.SerializerMethodField()
    pi_number = serializers.CharField(source='proforma_invoice.pi_number', read_only=True, allow_null=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    cost_breakdown = serializers.SerializerMethodField()

    class Meta:
        model = TransportEntry
        fields = [
            'id', 'transport_number',
            'purchase_order', 'po_number', 'vendor_name',
            'proforma_invoice', 'pi_number',
            'transporter_name', 'transporter_contact',
            'vehicle_number', 'driver_name', 'driver_contact',
            'dispatch_date', 'expected_delivery_date', 'actual_delivery_date',
            'dispatch_from', 'dispatch_to',
            'total_cost', 'status', 'status_display', 'remarks',
            'cost_breakdown', 'cost_items',
            'created_by', 'created_by_name', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'transport_number', 'total_cost',
            'created_by', 'created_at', 'updated_at',
        ]

    def get_vendor_name(self, obj):
        if obj.purchase_order:
            return obj.purchase_order.vendor.vendor_name
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


class TransportEntryCreateSerializer(serializers.ModelSerializer):
    cost_items = CostItemInputSerializer(many=True)

    class Meta:
        model = TransportEntry
        fields = [
            'purchase_order', 'proforma_invoice',
            'transporter_name', 'transporter_contact',
            'vehicle_number', 'driver_name', 'driver_contact',
            'dispatch_date', 'expected_delivery_date', 'actual_delivery_date',
            'dispatch_from', 'dispatch_to',
            'status', 'remarks', 'cost_items',
        ]
        extra_kwargs = {
            'purchase_order': {'required': False, 'allow_null': True},
            'proforma_invoice': {'required': False, 'allow_null': True},
        }

    def validate(self, data):
        if not data.get('purchase_order') and not data.get('proforma_invoice'):
            raise serializers.ValidationError(
                "Either purchase_order or proforma_invoice is required"
            )
        return data

    def validate_cost_items(self, value):
        if not value:
            raise serializers.ValidationError("At least one cost item is required")
        return value

    def create(self, validated_data):
        items_data = validated_data.pop('cost_items')
        with transaction.atomic():
            entry = TransportEntry.objects.create(**validated_data)
            for item_data in items_data:
                item_data.pop('id', None)
                TransportCostItem.objects.create(transport_entry=entry, **item_data)
            entry.calculate_total()
        return entry

    def to_representation(self, instance):
        return TransportEntrySerializer(instance).data


class TransportEntryUpdateSerializer(serializers.ModelSerializer):
    cost_items = CostItemInputSerializer(many=True, required=False)

    class Meta:
        model = TransportEntry
        fields = [
            'transporter_name', 'transporter_contact',
            'vehicle_number', 'driver_name', 'driver_contact',
            'dispatch_date', 'expected_delivery_date', 'actual_delivery_date',
            'dispatch_from', 'dispatch_to',
            'status', 'remarks', 'cost_items',
        ]

    def update(self, instance, validated_data):
        items_data = validated_data.pop('cost_items', None)

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
