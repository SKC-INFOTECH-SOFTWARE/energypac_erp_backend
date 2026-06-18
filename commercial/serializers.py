from decimal import Decimal
from rest_framework import serializers
from django.db import transaction

from sales.models import ProformaInvoice
from .models import (
    CommercialInvoice, CommercialInvoiceItem,
    PackingList, PackingListItem,
)
from .utils import amount_in_words


# ─────────────────────────────────────────────────────────────────────────────
# Commercial Invoice
# ─────────────────────────────────────────────────────────────────────────────

class CommercialInvoiceItemSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(required=False)

    class Meta:
        model = CommercialInvoiceItem
        fields = [
            'id', 'pi_item', 'marks_nos', 'no_kind_pkgs', 'description', 'hs_code',
            'quantity', 'unit', 'unit_price', 'total_amount', 'sort_order',
        ]
        read_only_fields = ['total_amount']


class CommercialInvoiceSerializer(serializers.ModelSerializer):
    items = CommercialInvoiceItemSerializer(many=True, read_only=True)
    pi_number = serializers.CharField(source='proforma_invoice.pi_number', read_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    has_packing_list = serializers.SerializerMethodField()

    class Meta:
        model = CommercialInvoice
        fields = [
            'id', 'ci_number', 'proforma_invoice', 'pi_number',
            'invoice_no', 'invoice_date', 'exporters_ref', 'gst_no',
            'buyers_order_no', 'buyers_order_date',
            'exporter', 'consigned_to_order_of', 'importer_notify_party', 'applicant',
            'terms_of_delivery', 'terms_of_delivery_and_payment',
            'place_of_supply', 'vessel_flight_no', 'port_of_loading', 'port_of_discharge',
            'place_of_delivery', 'pre_carriage_by', 'place_of_receipt',
            'country_of_origin', 'final_destination',
            'marks_from', 'marks_to',
            'currency', 'total_fca_value', 'total_freight', 'total_cpt_value',
            'amount_in_words', 'project_name', 'declarations', 'lut_no',
            'status', 'created_by', 'created_by_name', 'created_at', 'updated_at',
            'items', 'has_packing_list',
        ]
        read_only_fields = [
            'id', 'ci_number', 'total_fca_value', 'total_cpt_value',
            'amount_in_words', 'created_by', 'created_at', 'updated_at',
        ]

    def get_has_packing_list(self, obj):
        return obj.packing_lists.exclude(status='CANCELLED').exists()


class CommercialInvoiceWriteSerializer(serializers.ModelSerializer):
    items = CommercialInvoiceItemSerializer(many=True)

    class Meta:
        model = CommercialInvoice
        fields = [
            'proforma_invoice',
            'invoice_no', 'invoice_date', 'exporters_ref', 'gst_no',
            'buyers_order_no', 'buyers_order_date',
            'exporter', 'consigned_to_order_of', 'importer_notify_party', 'applicant',
            'terms_of_delivery', 'terms_of_delivery_and_payment',
            'place_of_supply', 'vessel_flight_no', 'port_of_loading', 'port_of_discharge',
            'place_of_delivery', 'pre_carriage_by', 'place_of_receipt',
            'country_of_origin', 'final_destination',
            'marks_from', 'marks_to',
            'currency', 'total_freight', 'project_name', 'declarations', 'lut_no',
            'items',
        ]

    def validate_proforma_invoice(self, pi):
        if pi.trade_type != 'INTERNATIONAL':
            raise serializers.ValidationError(
                "Commercial Invoice can only be created for an INTERNATIONAL Proforma Invoice."
            )
        # One active Commercial Invoice per PI — block duplicates.
        existing = CommercialInvoice.objects.filter(
            proforma_invoice=pi
        ).exclude(status='CANCELLED')
        if self.instance is not None:
            existing = existing.exclude(pk=self.instance.pk)
        dup = existing.first()
        if dup:
            raise serializers.ValidationError(
                f"A Commercial Invoice ({dup.ci_number}) already exists for this PI. "
                "Cancel it before generating a new one."
            )
        return pi

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("At least one item is required")
        return value

    def _apply_totals(self, ci):
        ci.recalc_totals()
        ci.amount_in_words = amount_in_words(ci.total_cpt_value, ci.currency)
        ci.save()

    @transaction.atomic
    def create(self, validated_data):
        items_data = validated_data.pop('items')
        created_by = validated_data.pop('created_by')
        ci = CommercialInvoice.objects.create(created_by=created_by, **validated_data)
        for idx, item in enumerate(items_data):
            item.pop('id', None)
            CommercialInvoiceItem.objects.create(
                commercial_invoice=ci, sort_order=item.pop('sort_order', idx), **item
            )
        self._apply_totals(ci)
        return ci

    @transaction.atomic
    def update(self, instance, validated_data):
        items_data = validated_data.pop('items', None)
        for attr, val in validated_data.items():
            setattr(instance, attr, val)
        instance.save()

        if items_data is not None:
            existing = {str(i.id): i for i in instance.items.all()}
            seen = set()
            for idx, item in enumerate(items_data):
                item_id = item.pop('id', None)
                item.pop('sort_order', None)
                if item_id and str(item_id) in existing:
                    obj = existing[str(item_id)]
                    for attr, val in item.items():
                        setattr(obj, attr, val)
                    obj.sort_order = idx
                    obj.save()
                    seen.add(str(item_id))
                else:
                    CommercialInvoiceItem.objects.create(
                        commercial_invoice=instance, sort_order=idx, **item
                    )
            for old_id, obj in existing.items():
                if old_id not in seen:
                    obj.delete()

        self._apply_totals(instance)
        return instance

    def to_representation(self, instance):
        return CommercialInvoiceSerializer(instance, context=self.context).data


# ─────────────────────────────────────────────────────────────────────────────
# Packing List
# ─────────────────────────────────────────────────────────────────────────────

class PackingListItemSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(required=False)

    class Meta:
        model = PackingListItem
        fields = [
            'id', 'ci_item', 'marks_nos', 'no_kind_pkgs', 'description', 'hs_code',
            'quantity', 'unit', 'nett_weight', 'gross_weight', 'sort_order',
        ]


class PackingListSerializer(serializers.ModelSerializer):
    items = PackingListItemSerializer(many=True, read_only=True)
    ci_number = serializers.CharField(source='commercial_invoice.ci_number', read_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)

    class Meta:
        model = PackingList
        fields = [
            'id', 'pl_number', 'commercial_invoice', 'ci_number',
            'packing_specification', 'lut_no',
            'total_nett_weight', 'total_gross_weight',
            'status', 'created_by', 'created_by_name', 'created_at', 'updated_at',
            'items',
        ]
        read_only_fields = [
            'id', 'pl_number', 'total_nett_weight', 'total_gross_weight',
            'created_by', 'created_at', 'updated_at',
        ]


class PackingListWriteSerializer(serializers.ModelSerializer):
    items = PackingListItemSerializer(many=True)

    class Meta:
        model = PackingList
        fields = [
            'commercial_invoice', 'packing_specification', 'lut_no', 'items',
        ]

    def validate_commercial_invoice(self, ci):
        # One active Packing List per Commercial Invoice — block duplicates.
        existing = PackingList.objects.filter(
            commercial_invoice=ci
        ).exclude(status='CANCELLED')
        if self.instance is not None:
            existing = existing.exclude(pk=self.instance.pk)
        dup = existing.first()
        if dup:
            raise serializers.ValidationError(
                f"A Packing List ({dup.pl_number}) already exists for this Commercial Invoice. "
                "Cancel it before generating a new one."
            )
        return ci

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("At least one item is required")
        return value

    def _apply_totals(self, pl):
        pl.recalc_totals()
        pl.save()

    @transaction.atomic
    def create(self, validated_data):
        items_data = validated_data.pop('items')
        created_by = validated_data.pop('created_by')
        pl = PackingList.objects.create(created_by=created_by, **validated_data)
        for idx, item in enumerate(items_data):
            item.pop('id', None)
            PackingListItem.objects.create(
                packing_list=pl, sort_order=item.pop('sort_order', idx), **item
            )
        self._apply_totals(pl)
        return pl

    @transaction.atomic
    def update(self, instance, validated_data):
        items_data = validated_data.pop('items', None)
        for attr, val in validated_data.items():
            setattr(instance, attr, val)
        instance.save()

        if items_data is not None:
            existing = {str(i.id): i for i in instance.items.all()}
            seen = set()
            for idx, item in enumerate(items_data):
                item_id = item.pop('id', None)
                item.pop('sort_order', None)
                if item_id and str(item_id) in existing:
                    obj = existing[str(item_id)]
                    for attr, val in item.items():
                        setattr(obj, attr, val)
                    obj.sort_order = idx
                    obj.save()
                    seen.add(str(item_id))
                else:
                    PackingListItem.objects.create(
                        packing_list=instance, sort_order=idx, **item
                    )
            for old_id, obj in existing.items():
                if old_id not in seen:
                    obj.delete()

        self._apply_totals(instance)
        return instance

    def to_representation(self, instance):
        return PackingListSerializer(instance, context=self.context).data
