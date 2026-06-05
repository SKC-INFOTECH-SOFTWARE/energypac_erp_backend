from django.conf import settings
from django.db import transaction
from rest_framework import serializers
from .models import ClientQuery, SalesQuotation, SalesQuotationItem, ProformaInvoice, ProformaInvoiceItem
from inventory.models import Product
from requisitions.models import Requisition, RequisitionItem
from decimal import Decimal
import os


class ClientQuerySerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    quotation_count = serializers.SerializerMethodField()

    class Meta:
        model = ClientQuery
        fields = [
            'id', 'query_number', 'client_name', 'contact_person', 'phone',
            'email', 'address', 'query_date', 'currency',
            'pdf_file', 'remarks', 'status',
            'created_by', 'created_by_name', 'quotation_count',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'query_number', 'created_at', 'updated_at']

    def get_quotation_count(self, obj):
        return obj.quotations.count()


class ClientQueryCreateSerializer(serializers.ModelSerializer):
    pdf_upload = serializers.FileField(write_only=True, required=False)
    query_date = serializers.DateField(input_formats=['%Y-%m-%d', '%d-%m-%Y'])

    class Meta:
        model = ClientQuery
        fields = [
            'client_name', 'contact_person', 'phone', 'email', 'address',
            'query_date', 'currency', 'remarks', 'pdf_upload'
        ]

    def create(self, validated_data):
        pdf_file = validated_data.pop('pdf_upload', None)
        client_query = ClientQuery.objects.create(**validated_data)

        if pdf_file:
            year = client_query.created_at.year
            upload_dir = os.path.join(settings.BASE_DIR, 'client', 'sales_pdfs', str(year))
            safe_number = client_query.query_number.replace('/', '_')
            filename = f"{safe_number}{os.path.splitext(pdf_file.name)[1]}"
            filepath = os.path.join(upload_dir, filename)

            os.makedirs(upload_dir, exist_ok=True)

            with open(filepath, 'wb+') as destination:
                for chunk in pdf_file.chunks():
                    destination.write(chunk)

            client_query.pdf_file = os.path.relpath(filepath, settings.BASE_DIR)
            client_query.save()

        return client_query

    def to_representation(self, instance):
        return ClientQuerySerializer(instance).data


# ─────────────────────────────────────────────────────────────────────────────
# Item serializers
# ─────────────────────────────────────────────────────────────────────────────

class SalesQuotationItemSerializer(serializers.ModelSerializer):
    """Read serializer for quotation items (used in GET responses)"""
    product_details = serializers.SerializerMethodField()

    class Meta:
        model = SalesQuotationItem
        fields = [
            'id', 'product', 'product_details', 'item_code', 'item_name',
            'description', 'hsn_code', 'unit', 'quantity', 'rate', 'amount',
            'remarks'
        ]
        read_only_fields = ['id', 'amount']

    def get_product_details(self, obj):
        if obj.product:
            return {
                'id': str(obj.product.id),
                'item_code': obj.product.item_code,
                'item_name': obj.product.item_name,
                'current_stock': float(obj.product.current_stock)
            }
        return None

    def validate(self, data):
        product = data.get('product')
        if product:
            data['item_code'] = product.item_code
            data['item_name'] = product.item_name
            data['hsn_code'] = product.hsn_code
            data['unit'] = product.unit
            if not data.get('description'):
                data['description'] = product.description
            if not data.get('rate'):
                data['rate'] = product.rate
        else:
            if not data.get('item_code'):
                raise serializers.ValidationError("item_code is required for manual entry")
            if not data.get('item_name'):
                raise serializers.ValidationError("item_name is required for manual entry")
            if not data.get('rate'):
                raise serializers.ValidationError("rate is required for manual entry")
        return data


class SalesQuotationItemUpdateSerializer(serializers.ModelSerializer):
    """
    Write serializer for items during quotation UPDATE.

    Key difference from SalesQuotationItemSerializer:
    - `id` is writable (UUIDField, optional) so the update method can match
      existing rows.  Omitting `id` = new item, sending `id` = update that row.
    """
    id = serializers.UUIDField(required=False, allow_null=True)

    class Meta:
        model = SalesQuotationItem
        fields = [
            'id', 'product', 'item_code', 'item_name', 'description',
            'hsn_code', 'unit', 'quantity', 'rate', 'amount', 'remarks'
        ]
        read_only_fields = ['amount']

    def validate(self, data):
        product = data.get('product')
        if product:
            data['item_code'] = product.item_code
            data['item_name'] = product.item_name
            data['hsn_code'] = product.hsn_code
            data['unit'] = product.unit
            if not data.get('description'):
                data['description'] = product.description
            if not data.get('rate'):
                data['rate'] = product.rate
        else:
            if not data.get('item_code'):
                raise serializers.ValidationError("item_code is required for manual entry")
            if not data.get('item_name'):
                raise serializers.ValidationError("item_name is required for manual entry")
            if not data.get('rate'):
                raise serializers.ValidationError("rate is required for manual entry")
        return data


# ─────────────────────────────────────────────────────────────────────────────
# Quotation serializers
# ─────────────────────────────────────────────────────────────────────────────

class SalesQuotationSerializer(serializers.ModelSerializer):
    """Read serializer — used for GET list/retrieve responses."""
    items = SalesQuotationItemSerializer(many=True, read_only=True)
    client_name = serializers.CharField(source='client_query.client_name', read_only=True)
    query_number = serializers.CharField(source='client_query.query_number', read_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    total_items = serializers.SerializerMethodField()
    total_gst = serializers.SerializerMethodField()
    gst_breakdown = serializers.SerializerMethodField()

    class Meta:
        model = SalesQuotation
        fields = [
            'id', 'quotation_number', 'client_query', 'client_name', 'query_number',
            'quotation_date', 'validity_date', 'payment_terms', 'delivery_terms',
            'remarks',
            'currency',
            'cgst_percentage', 'sgst_percentage', 'igst_percentage',
            'subtotal', 'cgst_amount', 'sgst_amount', 'igst_amount',
            'total_gst', 'gst_breakdown', 'total_amount',
            'status',
            'created_by', 'created_by_name', 'total_items', 'items',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'quotation_number', 'subtotal', 'cgst_amount',
            'sgst_amount', 'igst_amount', 'total_amount',
            'created_at', 'updated_at'
        ]

    def get_total_items(self, obj):
        return obj.items.count()

    def get_total_gst(self, obj):
        return float(obj.cgst_amount + obj.sgst_amount + obj.igst_amount)

    def get_gst_breakdown(self, obj):
        breakdown = []
        if obj.cgst_amount > 0:
            breakdown.append({'type': 'CGST', 'percentage': float(obj.cgst_percentage), 'amount': float(obj.cgst_amount)})
        if obj.sgst_amount > 0:
            breakdown.append({'type': 'SGST', 'percentage': float(obj.sgst_percentage), 'amount': float(obj.sgst_amount)})
        if obj.igst_amount > 0:
            breakdown.append({'type': 'IGST', 'percentage': float(obj.igst_percentage), 'amount': float(obj.igst_amount)})
        return breakdown


class SalesQuotationUpdateSerializer(serializers.ModelSerializer):
    """
    Full quotation update serializer — used for PUT / PATCH.

    Supports updating ALL header fields plus adding / editing / removing items
    in a single request.

    Item matching rules
    -------------------
    - Item sent WITH  an `id` that belongs to this quotation → UPDATE that row.
    - Item sent WITHOUT an `id` (or `id` not found on this quotation) → CREATE new row.
    - Existing item whose `id` is NOT present in the payload → DELETE that row.

    Example PATCH body
    ------------------
    {
        "quotation_date": "2026-03-01",
        "validity_date":  "2026-03-31",
        "payment_terms":  "30 days net",
        "delivery_terms": "Ex-works",
        "remarks":        "Revised as discussed",
        "cgst_percentage": 9,
        "sgst_percentage": 9,
        "igst_percentage": 0,
        "status": "SENT",
        "items": [
            {                              // UPDATE existing item
                "id": "existing-uuid",
                "quantity": 5,
                "rate": 1200,
                "remarks": "updated remark"
            },
            {                              // CREATE new item (no id)
                "item_code": "X001",
                "item_name": "New Widget",
                "unit": "PCS",
                "quantity": 2,
                "rate": 500
            }
            // any item NOT listed here will be DELETED
        ]
    }
    """
    # Use the update-aware item serializer for writes
    items = SalesQuotationItemUpdateSerializer(many=True, required=False)

    # Read-only convenience fields (same as SalesQuotationSerializer)
    client_name  = serializers.CharField(source='client_query.client_name',  read_only=True)
    query_number = serializers.CharField(source='client_query.query_number', read_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    total_items  = serializers.SerializerMethodField()
    total_gst    = serializers.SerializerMethodField()
    gst_breakdown = serializers.SerializerMethodField()

    class Meta:
        model  = SalesQuotation
        fields = [
            'id', 'quotation_number', 'client_query', 'client_name', 'query_number',
            'quotation_date', 'validity_date', 'payment_terms', 'delivery_terms',
            'remarks',
            'currency',
            'cgst_percentage', 'sgst_percentage', 'igst_percentage',
            'subtotal', 'cgst_amount', 'sgst_amount', 'igst_amount',
            'total_gst', 'gst_breakdown', 'total_amount',
            'status',
            'created_by', 'created_by_name', 'total_items', 'items',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'quotation_number', 'subtotal',
            'cgst_amount', 'sgst_amount', 'igst_amount', 'total_amount',
            'created_at', 'updated_at',
        ]

    # ── computed read fields ──────────────────────────────────────────────────
    def get_total_items(self, obj):
        return obj.items.count()

    def get_total_gst(self, obj):
        return float(obj.cgst_amount + obj.sgst_amount + obj.igst_amount)

    def get_gst_breakdown(self, obj):
        breakdown = []
        if obj.cgst_amount > 0:
            breakdown.append({'type': 'CGST', 'percentage': float(obj.cgst_percentage), 'amount': float(obj.cgst_amount)})
        if obj.sgst_amount > 0:
            breakdown.append({'type': 'SGST', 'percentage': float(obj.sgst_percentage), 'amount': float(obj.sgst_amount)})
        if obj.igst_amount > 0:
            breakdown.append({'type': 'IGST', 'percentage': float(obj.igst_percentage), 'amount': float(obj.igst_amount)})
        return breakdown

    # ── core update logic ─────────────────────────────────────────────────────
    def update(self, instance, validated_data):
        items_data = validated_data.pop('items', None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        # 2. Sync items only when the key is present in the payload
        if items_data is not None:
            existing_ids = set(
                instance.items.values_list('id', flat=True)
            )
            touched_ids = set()

            for item_data in items_data:
                # `id` is an extra field not on the model; pop it before save
                item_id = item_data.pop('id', None)

                if item_id and instance.items.filter(id=item_id).exists():
                    # ── UPDATE existing item ───────────────────────────────────
                    item = SalesQuotationItem.objects.get(id=item_id)
                    for attr, value in item_data.items():
                        setattr(item, attr, value)
                    item.save()
                    touched_ids.add(item_id)
                else:
                    # ── CREATE new item ───────────────────────────────────────
                    new_item = SalesQuotationItem.objects.create(
                        quotation=instance, **item_data
                    )
                    touched_ids.add(new_item.id)

            # 3. DELETE items that were omitted from the payload
            ids_to_delete = existing_ids - touched_ids
            if ids_to_delete:
                SalesQuotationItem.objects.filter(id__in=ids_to_delete).delete()

        # 4. Recalculate subtotal + tax amounts from the current item set
        instance.calculate_totals()
        return instance

    def to_representation(self, instance):
        """Return the standard read serializer shape after write."""
        return SalesQuotationSerializer(instance, context=self.context).data


# ─────────────────────────────────────────────────────────────────────────────
# Creation serializer (unchanged)
# ─────────────────────────────────────────────────────────────────────────────

class SalesQuotationCreateSerializer(serializers.Serializer):
    """Serializer for creating a new sales quotation"""
    client_query    = serializers.UUIDField()
    quotation_date  = serializers.DateField(input_formats=['%Y-%m-%d', '%d-%m-%Y'])
    validity_date   = serializers.DateField(required=False, allow_null=True, input_formats=['%Y-%m-%d', '%d-%m-%Y'])
    payment_terms   = serializers.CharField(required=False, allow_blank=True)
    delivery_terms  = serializers.CharField(required=False, allow_blank=True)
    remarks         = serializers.CharField(required=False, allow_blank=True)
    currency        = serializers.ChoiceField(
        choices=['INR', 'USD'], required=False,
        help_text="Currency for this quotation. If not provided, inherits from client query."
    )
    cgst_percentage = serializers.DecimalField(max_digits=5, decimal_places=2, default=0)
    sgst_percentage = serializers.DecimalField(max_digits=5, decimal_places=2, default=0)
    igst_percentage = serializers.DecimalField(max_digits=5, decimal_places=2, default=0)
    items = serializers.ListField(
        child=serializers.DictField(),
        help_text="List of items (from stock or manual entry)"
    )

    def validate_client_query(self, value):
        try:
            ClientQuery.objects.get(id=value)
        except ClientQuery.DoesNotExist:
            raise serializers.ValidationError("Client query not found")
        return value

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("At least one item is required")
        for item in value:
            product_id = item.get('product')
            if product_id:
                try:
                    Product.objects.get(id=product_id)
                except Product.DoesNotExist:
                    raise serializers.ValidationError(f"Product {product_id} not found")
            else:
                if not item.get('item_code'):
                    raise serializers.ValidationError("item_code required for manual entry")
                if not item.get('item_name'):
                    raise serializers.ValidationError("item_name required for manual entry")
                if not item.get('rate'):
                    raise serializers.ValidationError("rate required for manual entry")
            if not item.get('quantity'):
                raise serializers.ValidationError("quantity is required")
        return value

    def create(self, validated_data):
        items_data   = validated_data.pop('items')
        client_query = ClientQuery.objects.get(id=validated_data.pop('client_query'))
        created_by   = validated_data.pop('created_by')
        currency     = validated_data.pop('currency', None) or client_query.currency

        quotation = SalesQuotation.objects.create(
            client_query    = client_query,
            quotation_date  = validated_data['quotation_date'],
            validity_date   = validated_data.get('validity_date'),
            payment_terms   = validated_data.get('payment_terms', ''),
            delivery_terms  = validated_data.get('delivery_terms', ''),
            remarks         = validated_data.get('remarks', ''),
            currency        = currency,
            cgst_percentage = validated_data.get('cgst_percentage', 0),
            sgst_percentage = validated_data.get('sgst_percentage', 0),
            igst_percentage = validated_data.get('igst_percentage', 0),
            created_by      = created_by
        )

        for item_data in items_data:
            product_id = item_data.get('product')
            product = Product.objects.get(id=product_id) if product_id else None
            item_rate = item_data.get('rate', 0)

            SalesQuotationItem.objects.create(
                quotation    = quotation,
                product      = product,
                item_code    = item_data.get('item_code', ''),
                item_name    = item_data.get('item_name', ''),
                description  = item_data.get('description', ''),
                hsn_code     = item_data.get('hsn_code', ''),
                unit         = item_data.get('unit', 'PCS'),
                quantity     = item_data['quantity'],
                rate         = item_rate,
                remarks      = item_data.get('remarks', '')
            )

        quotation.calculate_totals()
        client_query.status = 'QUOTATION_SENT'
        client_query.save()
        return quotation

    def to_representation(self, instance):
        return SalesQuotationSerializer(instance).data


# ─────────────────────────────────────────────────────────────────────────────
# Helper serializers (unchanged)
# ─────────────────────────────────────────────────────────────────────────────

class QuotationItemInputSerializer(serializers.Serializer):
    """Helper serializer for item input in quotation"""
    product     = serializers.UUIDField(required=False, allow_null=True)
    item_code   = serializers.CharField(required=False, allow_blank=True)
    item_name   = serializers.CharField(required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)
    hsn_code    = serializers.CharField(required=False, allow_blank=True)
    unit        = serializers.CharField(default='PCS')
    quantity    = serializers.DecimalField(max_digits=10, decimal_places=2)
    rate        = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)
    remarks     = serializers.CharField(required=False, allow_blank=True)


# ═════════════════════════════════════════════════════════════════════════════
# Proforma Invoice Serializers
# ═════════════════════════════════════════════════════════════════════════════

class PIItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.item_name', read_only=True)
    product_code = serializers.CharField(source='product.item_code', read_only=True)
    unit         = serializers.CharField(source='product.unit', read_only=True)
    purchase_status = serializers.SerializerMethodField()

    class Meta:
        model  = ProformaInvoiceItem
        fields = [
            'id', 'product', 'product_name', 'product_code', 'unit',
            'requisition_item', 'hsn_code', 'quantity', 'unit_price', 'amount',
            'purchase_status',
        ]
        read_only_fields = ['id', 'amount']

    def get_purchase_status(self, obj):
        from purchase_orders.models import PurchaseOrderItem
        pi = obj.proforma_invoice
        po_item = PurchaseOrderItem.objects.filter(
            po__requisition=pi.requisition,
            product=obj.product,
        ).first()
        if not po_item:
            return 'PENDING'
        return 'COMPLETED' if po_item.is_received else 'PO_CREATED'


class ProformaInvoiceSerializer(serializers.ModelSerializer):
    items              = PIItemSerializer(many=True, read_only=True)
    requisition_number = serializers.CharField(source='requisition.requisition_number', read_only=True)
    created_by_name    = serializers.CharField(source='created_by.get_full_name', read_only=True)
    locked_by_name     = serializers.SerializerMethodField()

    class Meta:
        model  = ProformaInvoice
        fields = [
            'id', 'pi_number', 'requisition', 'requisition_number',
            'pi_date', 'currency', 'conversion_rate', 'payment_due_date',
            'lc_number', 'exporter_beneficiary', 'exporter_reference',
            'gst_number', 'consignee', 'applicant_importer',
            'pre_carriage_by', 'country_of_origin', 'final_destination',
            'place_of_receipt', 'port_of_loading', 'port_of_discharge',
            'terms_of_delivery', 'terms_of_payment',
            'grand_total',
            'amount_received', 'balance',
            'terms_and_conditions', 'notes',
            'revision_number', 'is_revised',
            'locked_by', 'locked_by_name', 'locked_at',
            'status',
            'created_by', 'created_by_name', 'items',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'pi_number', 'grand_total',
            'amount_received', 'balance',
            'revision_number', 'is_revised',
            'locked_by', 'locked_at',
            'created_at', 'updated_at',
        ]

    def get_locked_by_name(self, obj):
        if obj.locked_by:
            return obj.locked_by.get_full_name()
        return None


# ── Create ────────────────────────────────────────────────────────────────

class PIItemCreateSerializer(serializers.Serializer):
    product    = serializers.UUIDField()
    hsn_code   = serializers.CharField(required=False, allow_blank=True, default='')
    quantity   = serializers.DecimalField(max_digits=10, decimal_places=2)
    unit_price = serializers.DecimalField(max_digits=10, decimal_places=2)


class ProformaInvoiceCreateSerializer(serializers.Serializer):
    requisition = serializers.UUIDField()
    pi_date     = serializers.DateField()
    currency    = serializers.CharField(default='INR')
    conversion_rate = serializers.DecimalField(max_digits=10, decimal_places=4, required=False, allow_null=True)
    payment_due_date = serializers.DateField(required=False, allow_null=True)
    items       = PIItemCreateSerializer(many=True)

    lc_number            = serializers.CharField(required=False, allow_blank=True, default='')
    exporter_beneficiary = serializers.CharField(required=False, allow_blank=True, default='')
    exporter_reference   = serializers.CharField(required=False, allow_blank=True, default='')
    gst_number           = serializers.CharField(required=False, allow_blank=True, default='')
    consignee            = serializers.CharField(required=False, allow_blank=True, default='')
    applicant_importer   = serializers.CharField(required=False, allow_blank=True, default='')
    pre_carriage_by      = serializers.CharField(required=False, allow_blank=True, default='')
    country_of_origin    = serializers.CharField(required=False, allow_blank=True, default='')
    final_destination    = serializers.CharField(required=False, allow_blank=True, default='')
    place_of_receipt     = serializers.CharField(required=False, allow_blank=True, default='')
    port_of_loading      = serializers.CharField(required=False, allow_blank=True, default='')
    port_of_discharge    = serializers.CharField(required=False, allow_blank=True, default='')
    terms_of_delivery    = serializers.CharField(required=False, allow_blank=True, default='')
    terms_of_payment     = serializers.CharField(required=False, allow_blank=True, default='')
    terms_and_conditions = serializers.ListField(child=serializers.JSONField(), required=False, default=list)
    notes                = serializers.CharField(required=False, allow_blank=True, default='')

    def validate_requisition(self, value):
        try:
            requisition = Requisition.objects.get(id=value)
        except Requisition.DoesNotExist:
            raise serializers.ValidationError("Requisition not found")

        from purchase_orders.models import PurchaseOrderItem
        pending_items = []
        for ri in requisition.items.select_related('product').all():
            has_po = PurchaseOrderItem.objects.filter(
                po__requisition=requisition, product=ri.product,
            ).exclude(po__status='CANCELLED').exists()
            if not has_po:
                pending_items.append(ri.product.item_name)

        if pending_items:
            raise serializers.ValidationError(
                f"PO not generated for: {', '.join(pending_items)}. "
                "All requisition items must have a PO before creating PI."
            )

        return value

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("At least one item is required")
        for item in value:
            try:
                Product.objects.get(id=item['product'])
            except Product.DoesNotExist:
                raise serializers.ValidationError(f"Product {item['product']} not found")
        return value

    def create(self, validated_data):
        from datetime import date

        items_data  = validated_data.pop('items')
        requisition = Requisition.objects.get(id=validated_data.pop('requisition'))
        created_by  = validated_data.pop('created_by')

        with transaction.atomic():
            pi = ProformaInvoice.objects.create(
                requisition=requisition,
                created_by=created_by,
                **validated_data,
            )

            for item_data in items_data:
                product = Product.objects.get(id=item_data['product'])
                req_item = RequisitionItem.objects.filter(
                    requisition=requisition, product=product
                ).first()

                ProformaInvoiceItem.objects.create(
                    proforma_invoice=pi,
                    requisition_item=req_item,
                    product=product,
                    hsn_code=item_data.get('hsn_code', product.hsn_code or ''),
                    quantity=item_data['quantity'],
                    unit_price=item_data['unit_price'],
                )

                product.sale_count += 1
                product.total_sold_qty += item_data['quantity']
                product.last_sale_date = date.today()
                product.save()

            pi.calculate_total()

        return pi

    def to_representation(self, instance):
        return ProformaInvoiceSerializer(instance).data


# ── Update ────────────────────────────────────────────────────────────────

class PIItemUpdateSerializer(serializers.Serializer):
    id         = serializers.UUIDField(required=False, allow_null=True)
    product    = serializers.UUIDField()
    hsn_code   = serializers.CharField(required=False, allow_blank=True, default='')
    quantity   = serializers.DecimalField(max_digits=10, decimal_places=2)
    unit_price = serializers.DecimalField(max_digits=10, decimal_places=2)


class ProformaInvoiceUpdateSerializer(serializers.ModelSerializer):
    items = PIItemUpdateSerializer(many=True, required=False)

    class Meta:
        model  = ProformaInvoice
        fields = [
            'pi_date', 'currency', 'conversion_rate', 'payment_due_date',
            'lc_number', 'exporter_beneficiary', 'exporter_reference',
            'gst_number', 'consignee', 'applicant_importer',
            'pre_carriage_by', 'country_of_origin', 'final_destination',
            'place_of_receipt', 'port_of_loading', 'port_of_discharge',
            'terms_of_delivery', 'terms_of_payment',
            'terms_and_conditions', 'notes', 'status',
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
                        item.product    = product
                        item.hsn_code   = item_data.get('hsn_code', '')
                        item.quantity   = item_data['quantity']
                        item.unit_price = item_data['unit_price']
                        item.save()
                        submitted_ids.add(str(item_id))
                    else:
                        req_item = RequisitionItem.objects.filter(
                            requisition=instance.requisition, product=product
                        ).first()
                        new_item = ProformaInvoiceItem.objects.create(
                            proforma_invoice=instance,
                            requisition_item=req_item,
                            product=product,
                            hsn_code=item_data.get('hsn_code', ''),
                            quantity=item_data['quantity'],
                            unit_price=item_data['unit_price'],
                        )
                        submitted_ids.add(str(new_item.id))

                for item_id in existing_items:
                    if item_id not in submitted_ids:
                        existing_items[item_id].delete()

            instance.calculate_total()

        return instance

    def to_representation(self, instance):
        return ProformaInvoiceSerializer(instance).data
