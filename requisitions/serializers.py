from rest_framework import serializers
from django.db import transaction
from decimal import Decimal
from .models import (Requisition, RequisitionItem,
                     VendorRequisitionAssignment, VendorRequisitionItem,
                     VendorQuotation, VendorQuotationItem)
from inventory.serializers import ProductSerializer
from vendors.serializers import VendorSerializer
from vendors.models import Vendor

class RequisitionItemSerializer(serializers.ModelSerializer):
    """Serializer for requisition items"""
    product_details = ProductSerializer(source='product', read_only=True)
    product_name = serializers.CharField(source='product.item_name', read_only=True)
    product_code = serializers.CharField(source='product.item_code', read_only=True)
    unit = serializers.CharField(source='product.unit', read_only=True)

    class Meta:
        model = RequisitionItem
        fields = ['id', 'product', 'product_name', 'product_code', 'unit',
                  'product_details', 'quantity', 'remarks', 'created_at']
        read_only_fields = ['id', 'created_at']

class RequisitionSerializer(serializers.ModelSerializer):
    """Serializer for viewing requisitions"""
    items = RequisitionItemSerializer(many=True, read_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    created_by_code = serializers.CharField(source='created_by.employee_code', read_only=True)
    total_items = serializers.SerializerMethodField()

    class Meta:
        model = Requisition
        fields = ['id', 'requisition_number', 'requisition_date', 'remarks',
                  'created_by', 'created_by_name', 'created_by_code',
                  'is_assigned', 'total_items', 'items', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_by',
                           'is_assigned', 'created_at', 'updated_at']

    def get_total_items(self, obj):
        return obj.items.count()

class RequisitionCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating requisitions"""
    items = RequisitionItemSerializer(many=True)
    requisition_number = serializers.CharField(
        required=False, allow_blank=True,
        help_text="Optional manual PR reference. Auto-generated if not provided."
    )

    class Meta:
        model = Requisition
        fields = ['requisition_number', 'requisition_date', 'remarks', 'items']

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("At least one item is required")
        return value

    def validate_requisition_number(self, value):
        if value and Requisition.objects.filter(requisition_number=value).exists():
            raise serializers.ValidationError("This requisition number already exists.")
        return value

    def create(self, validated_data):
        items_data = validated_data.pop('items')
        req_number = validated_data.pop('requisition_number', None)
        if req_number:
            validated_data['requisition_number'] = req_number
        requisition = Requisition.objects.create(**validated_data)

        for item_data in items_data:
            RequisitionItem.objects.create(requisition=requisition, **item_data)

        return requisition


# ── NEW: Item serializer for updates (id is writable so we can match existing items) ──

class RequisitionItemUpdateSerializer(serializers.ModelSerializer):
    """Used during update — id must be writable to identify existing items"""
    id = serializers.UUIDField(required=False, allow_null=True)   # ← writable
    product_name = serializers.CharField(source='product.item_name', read_only=True)
    product_code = serializers.CharField(source='product.item_code', read_only=True)
    unit = serializers.CharField(source='product.unit', read_only=True)

    class Meta:
        model = RequisitionItem
        fields = ['id', 'product', 'product_name', 'product_code', 'unit',
                  'quantity', 'remarks']


# ── NEW: Update serializer with proper update() logic ──

class RequisitionUpdateSerializer(serializers.ModelSerializer):
    """
    PUT / PATCH on a requisition — keeps the vendor side in step.

    A requisition can be edited even after it is assigned, but then every change
    must flow down to the vendors, otherwise the assignment (and any quotation
    already entered against it) would describe a requisition that no longer exists:

        item added    → added to every vendor assignment of this requisition, and
                        to any quotation already entered (rate 0 = "rate pending")
        item removed  → removed from every assignment and quotation
        qty changed   → assignment + quotation quantities follow; the vendor's rate
                        is kept and the amount is recalculated

    An item that a Purchase Order was already raised against cannot be removed —
    that PO is a real commitment.
    """
    items = RequisitionItemUpdateSerializer(many=True, required=False)
    requisition_number = serializers.CharField(
        required=False, allow_blank=True, max_length=50,
        help_text="Leave blank to keep the current number, or type your own (must be unique).",
    )

    class Meta:
        model = Requisition
        fields = ['requisition_number', 'requisition_date', 'remarks', 'items']

    def validate_requisition_number(self, value):
        value = (value or '').strip()
        if not value:
            return ''   # blank = keep the existing number
        clash = Requisition.objects.filter(requisition_number=value)
        if self.instance:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError(
                f'Requisition number "{value}" is already used by another requisition.'
            )
        return value

    # ── vendor-side cascade helpers ──────────────────────────────────────────

    @staticmethod
    def _recompute_quotation_totals(quotation_ids):
        from django.db.models import Sum
        for quotation in VendorQuotation.objects.filter(id__in=set(quotation_ids)):
            total = quotation.items.aggregate(t=Sum('amount'))['t'] or Decimal('0')
            quotation.total_amount = total
            quotation.save(update_fields=['total_amount'])

    def _mirror_new_item_to_vendors(self, requisition, req_item):
        """A new requisition item must reach every vendor already working on it."""
        assignments = VendorRequisitionAssignment.objects.filter(
            requisition=requisition
        ).prefetch_related('quotations')

        touched_quotations = []
        for assignment in assignments:
            vendor_item, _ = VendorRequisitionItem.objects.get_or_create(
                assignment=assignment,
                requisition_item=req_item,
                defaults={'product': req_item.product, 'quantity': req_item.quantity},
            )

            # If the vendor has already submitted a quotation, the item would be
            # unquotable (the quotation editor only edits existing lines), so add
            # it there too with a zero rate for the buyer to fill in.
            for quotation in assignment.quotations.all():
                if not VendorQuotationItem.objects.filter(
                    quotation=quotation, vendor_item=vendor_item
                ).exists():
                    VendorQuotationItem.objects.create(
                        quotation=quotation,
                        vendor_item=vendor_item,
                        product=req_item.product,
                        quantity=req_item.quantity,
                        quoted_rate=Decimal('0'),
                        remarks='Added after quotation — rate pending',
                    )
                    touched_quotations.append(quotation.id)

        self._recompute_quotation_totals(touched_quotations)

    def _remove_item_from_vendors(self, req_item):
        """Drop the item from every assignment/quotation, unless a PO exists."""
        from purchase_orders.models import PurchaseOrderItem

        vendor_items = VendorRequisitionItem.objects.filter(requisition_item=req_item)
        if not vendor_items.exists():
            return

        quotation_items = VendorQuotationItem.objects.filter(vendor_item__in=vendor_items)

        # PurchaseOrderItem.quotation_item is PROTECTed — and a raised PO is a real
        # commitment, so removing the item is genuinely not allowed here.
        po_lines = PurchaseOrderItem.objects.filter(
            quotation_item__in=quotation_items
        ).select_related('po')
        if po_lines.exists():
            po_numbers = sorted({p.po.po_number for p in po_lines})
            raise serializers.ValidationError({
                'items': (
                    f'Cannot remove "{req_item.product.item_name}" — a purchase order '
                    f'({", ".join(po_numbers)}) has already been raised for it. '
                    'Cancel that PO first.'
                )
            })

        touched_quotations = list(quotation_items.values_list('quotation_id', flat=True))
        quotation_items.delete()
        vendor_items.delete()
        self._recompute_quotation_totals(touched_quotations)

    def _sync_quantity_to_vendors(self, req_item):
        """Assignment + quotation quantities follow the requisition; rates stay."""
        VendorRequisitionItem.objects.filter(
            requisition_item=req_item
        ).update(quantity=req_item.quantity)

        touched_quotations = []
        for q_item in VendorQuotationItem.objects.filter(
            vendor_item__requisition_item=req_item
        ):
            q_item.quantity = req_item.quantity
            q_item.save()  # recomputes amount = quantity × quoted_rate
            touched_quotations.append(q_item.quotation_id)

        self._recompute_quotation_totals(touched_quotations)

    # ── update ───────────────────────────────────────────────────────────────

    def update(self, instance, validated_data):
        items_data = validated_data.pop('items', None)

        # An empty string means "keep the current number" — never blank it out.
        if not validated_data.get('requisition_number'):
            validated_data.pop('requisition_number', None)

        with transaction.atomic():
            for attr, value in validated_data.items():
                setattr(instance, attr, value)
            instance.save()

            if items_data is not None:
                existing_items = {str(item.id): item for item in instance.items.all()}
                submitted_ids = set()

                for item_data in items_data:
                    item_id = item_data.pop('id', None)

                    if item_id and str(item_id) in existing_items:
                        item = existing_items[str(item_id)]
                        old_product_id = item.product_id
                        old_quantity = item.quantity

                        for attr, value in item_data.items():
                            setattr(item, attr, value)
                        item.save()
                        submitted_ids.add(str(item_id))

                        # Swapping the product on an assigned line is really a
                        # remove + add, so treat it as one.
                        if item.product_id != old_product_id:
                            stale = RequisitionItem(
                                id=item.id, requisition=instance,
                                product_id=old_product_id, quantity=old_quantity,
                            )
                            self._remove_item_from_vendors(stale)
                            self._mirror_new_item_to_vendors(instance, item)
                        elif item.quantity != old_quantity:
                            self._sync_quantity_to_vendors(item)
                    else:
                        new_item = RequisitionItem.objects.create(
                            requisition=instance, **item_data
                        )
                        submitted_ids.add(str(new_item.id))
                        self._mirror_new_item_to_vendors(instance, new_item)

                for item_id, item in existing_items.items():
                    if item_id not in submitted_ids:
                        self._remove_item_from_vendors(item)
                        item.delete()

        return instance

    def to_representation(self, instance):
        return RequisitionSerializer(instance).data


class VendorRequisitionItemSerializer(serializers.ModelSerializer):
    """Serializer for vendor assigned items"""
    product_name = serializers.CharField(source='product.item_name', read_only=True)
    product_code = serializers.CharField(source='product.item_code', read_only=True)
    unit = serializers.CharField(source='product.unit', read_only=True)

    class Meta:
        model = VendorRequisitionItem
        fields = ['id', 'requisition_item', 'product', 'product_name',
                  'product_code', 'unit', 'quantity']
        read_only_fields = ['id']

class VendorRequisitionAssignmentSerializer(serializers.ModelSerializer):
    """Serializer for viewing vendor assignments"""
    items = VendorRequisitionItemSerializer(many=True, read_only=True)
    vendor_details = VendorSerializer(source='vendor', read_only=True)
    requisition_number = serializers.CharField(source='requisition.requisition_number',
                                                read_only=True)
    assigned_by_name = serializers.CharField(source='assigned_by.get_full_name',
                                              read_only=True)
    total_items = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()

    class Meta:
        model = VendorRequisitionAssignment
        fields = ['id', 'requisition', 'requisition_number', 'vendor',
                  'vendor_details', 'assignment_date', 'remarks', 'assigned_by',
                  'assigned_by_name', 'status', 'total_items', 'items', 'created_at']
        read_only_fields = ['id', 'assignment_date', 'assigned_by', 'created_at']

    def get_total_items(self, obj):
        return obj.items.count()

    def get_status(self, obj):
        if obj.quotations.exists():
            return 'Completed'
        return 'Pending'

class VendorAssignmentCreateSerializer(serializers.Serializer):
    """Serializer for creating vendor assignments"""
    requisition = serializers.UUIDField()
    vendor = serializers.UUIDField()
    remarks = serializers.CharField(required=False, allow_blank=True)
    items = serializers.ListField(
        child=serializers.DictField(),
        help_text="List of items with requisition_item and quantity"
    )

    def to_representation(self, instance):
        """Return the created assignment using VendorRequisitionAssignmentSerializer"""
        return VendorRequisitionAssignmentSerializer(instance).data

    def validate_requisition(self, value):
        try:
            Requisition.objects.get(id=value)
        except Requisition.DoesNotExist:
            raise serializers.ValidationError("Requisition not found")
        return value

    def validate_vendor(self, value):
        try:
            Vendor.objects.get(id=value)
        except Vendor.DoesNotExist:
            raise serializers.ValidationError("Vendor not found")
        return value

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("At least one item is required")
        return value

    def validate(self, data):
        if VendorRequisitionAssignment.objects.filter(
            requisition_id=data['requisition'],
            vendor_id=data['vendor']
        ).exists():
            raise serializers.ValidationError(
                "This vendor is already assigned to this requisition."
            )
        return data

    def create(self, validated_data):
        items_data = validated_data.pop('items')
        requisition = Requisition.objects.get(id=validated_data['requisition'])
        vendor = Vendor.objects.get(id=validated_data['vendor'])
        assigned_by = validated_data['assigned_by']
        remarks = validated_data.get('remarks', '')
        assignment = VendorRequisitionAssignment.objects.create(
            requisition=requisition,
            vendor=vendor,
            assigned_by=assigned_by,
            remarks=remarks
        )
        for item_data in items_data:
            req_item = RequisitionItem.objects.get(id=item_data['requisition_item'])
            VendorRequisitionItem.objects.create(
                assignment=assignment,
                requisition_item=req_item,
                product=req_item.product,
                quantity=item_data['quantity']
            )
        requisition.is_assigned = True
        requisition.save()
        return assignment

class VendorQuotationItemSerializer(serializers.ModelSerializer):
    """Serializer for quotation items"""
    product_name = serializers.CharField(source='product.item_name', read_only=True)
    product_code = serializers.CharField(source='product.item_code', read_only=True)
    unit = serializers.CharField(source='product.unit', read_only=True)

    class Meta:
        model = VendorQuotationItem
        fields = [
            'id', 'vendor_item', 'product', 'product_name', 'product_code',
            'unit', 'quantity', 'quoted_rate', 'amount',
            'remarks'
        ]
        read_only_fields = ['id', 'amount']

class VendorQuotationSerializer(serializers.ModelSerializer):
    """Serializer for viewing quotations"""
    items = VendorQuotationItemSerializer(many=True, read_only=True)
    vendor_name = serializers.CharField(source='assignment.vendor.vendor_name', read_only=True)
    vendor_code = serializers.CharField(source='assignment.vendor.vendor_code', read_only=True)
    # The quotation screens showed GST / PAN / bank fields that were never sent —
    # they always rendered blank. Expose them.
    gst_number = serializers.CharField(source='assignment.vendor.gst_number', read_only=True)
    pan_number = serializers.CharField(source='assignment.vendor.pan_number', read_only=True)
    bank_name = serializers.CharField(source='assignment.vendor.bank_name', read_only=True)
    bank_account_number = serializers.CharField(source='assignment.vendor.bank_account_number', read_only=True)
    ifsc_code = serializers.CharField(source='assignment.vendor.ifsc_code', read_only=True)
    requisition_number = serializers.CharField(source='assignment.requisition.requisition_number', read_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    total_items = serializers.SerializerMethodField()

    class Meta:
        model = VendorQuotation
        fields = [
            'id', 'quotation_number', 'assignment', 'vendor_name', 'vendor_code',
            'gst_number', 'pan_number', 'bank_name', 'bank_account_number', 'ifsc_code',
            'requisition_number', 'quotation_date', 'reference_number',
            'validity_date', 'payment_terms', 'delivery_terms', 'remarks',
            'currency', 'total_amount',
            'is_selected', 'created_by', 'created_by_name',
            'total_items', 'items', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'quotation_number', 'quotation_date', 'created_by',
            'total_amount', 'created_at', 'updated_at'
        ]

    def get_total_items(self, obj):
        return obj.items.count()

class QuotationItemInputSerializer(serializers.Serializer):
    vendor_item = serializers.UUIDField(required=True)
    quoted_rate = serializers.DecimalField(
        max_digits=10, decimal_places=4, required=True,
        help_text="Rate quoted by vendor per unit"
    )
    tax_percentage = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False, default=0,
        help_text="GST/Tax percentage"
    )

class VendorQuotationCreateSerializer(serializers.Serializer):
    requisition = serializers.UUIDField(help_text="Requisition ID")
    vendor = serializers.UUIDField(help_text="Vendor ID")
    reference_number = serializers.CharField(required=False, allow_blank=True)
    validity_date = serializers.DateField(required=False, allow_null=True)
    payment_terms = serializers.CharField(required=False, allow_blank=True)
    delivery_terms = serializers.CharField(required=False, allow_blank=True)
    remarks = serializers.CharField(required=False, allow_blank=True)
    currency = serializers.ChoiceField(
        choices=['INR', 'USD'], default='INR',
        help_text="Currency of the quotation (INR or USD)"
    )
    items = serializers.ListField(
        child=serializers.DictField(),
        help_text="List of items with vendor_item and quoted_rate"
    )

    def validate(self, data):
        try:
            assignment = VendorRequisitionAssignment.objects.get(
                requisition_id=data['requisition'],
                vendor_id=data['vendor']
            )
            data['assignment'] = assignment
        except VendorRequisitionAssignment.DoesNotExist:
            raise serializers.ValidationError(
                "Vendor is not assigned to this requisition."
            )
        if VendorQuotation.objects.filter(assignment=assignment).exists():
            raise serializers.ValidationError(
                "Quotation already exists for this vendor under this requisition."
            )
        return data

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("At least one item is required")
        for item in value:
            if 'vendor_item' not in item:
                raise serializers.ValidationError("vendor_item is required for each item")
            if 'quoted_rate' not in item:
                raise serializers.ValidationError("quoted_rate is required for each item")
            try:
                VendorRequisitionItem.objects.get(id=item['vendor_item'])
            except VendorRequisitionItem.DoesNotExist:
                raise serializers.ValidationError(f"Vendor item {item['vendor_item']} not found")
        return value

    def create(self, validated_data):
        items_data = validated_data.pop('items')
        assignment = validated_data.pop('assignment')
        currency = validated_data.pop('currency', 'INR')

        quotation = VendorQuotation.objects.create(
            assignment=assignment,
            currency=currency,
            reference_number=validated_data.get('reference_number', ''),
            validity_date=validated_data.get('validity_date'),
            payment_terms=validated_data.get('payment_terms', ''),
            delivery_terms=validated_data.get('delivery_terms', ''),
            remarks=validated_data.get('remarks', ''),
            created_by=validated_data['created_by']
        )

        total_amount = 0
        for item_data in items_data:
            try:
                vendor_item = VendorRequisitionItem.objects.get(id=item_data['vendor_item'])
            except VendorRequisitionItem.DoesNotExist:
                raise serializers.ValidationError({
                    'items': f"Vendor item {item_data['vendor_item']} not found"
                })

            quoted_rate = item_data['quoted_rate']

            try:
                quotation_item = VendorQuotationItem.objects.create(
                    quotation=quotation,
                    vendor_item=vendor_item,
                    product=vendor_item.product,
                    quantity=vendor_item.quantity,
                    quoted_rate=quoted_rate,
                    remarks=item_data.get('remarks', '')
                )
                total_amount += quotation_item.amount
            except Exception as e:
                raise serializers.ValidationError({
                    'items': f"Error creating item: {str(e)}"
                })

        quotation.total_amount = total_amount
        quotation.save()
        return quotation

    def to_representation(self, instance):
        return VendorQuotationSerializer(instance).data


# ─────────────────────────────────────────────────────────────────────────────
# Vendor Quotation Update — edit item rates (and header details); recalcs total
# ─────────────────────────────────────────────────────────────────────────────

class VendorQuotationItemUpdateSerializer(serializers.Serializer):
    id          = serializers.UUIDField(required=True)
    quoted_rate = serializers.DecimalField(
        max_digits=10, decimal_places=4, required=True,
        help_text="Updated rate quoted by vendor per unit"
    )
    remarks     = serializers.CharField(required=False, allow_blank=True)

    def validate_quoted_rate(self, value):
        if value is None or value < 0:
            raise serializers.ValidationError("Quoted rate must be zero or a positive number.")
        return value


class VendorQuotationUpdateSerializer(serializers.ModelSerializer):
    """
    Update a vendor quotation: header fields and per-item quoted rates.
    Item amounts and the quotation total are recalculated on save.
    """
    items = VendorQuotationItemUpdateSerializer(many=True, required=False)

    class Meta:
        model  = VendorQuotation
        fields = [
            'reference_number', 'validity_date', 'payment_terms',
            'delivery_terms', 'remarks', 'currency', 'items',
        ]

    def validate_items(self, value):
        quotation = self.instance
        valid_ids = set(str(i) for i in quotation.items.values_list('id', flat=True))
        for item in value:
            if str(item['id']) not in valid_ids:
                raise serializers.ValidationError(
                    f"Quotation item {item['id']} does not belong to this quotation."
                )
        return value

    def update(self, instance, validated_data):
        items_data = validated_data.pop('items', None)

        with transaction.atomic():
            for attr, value in validated_data.items():
                setattr(instance, attr, value)

            if items_data is not None:
                item_map = {str(i.id): i for i in instance.items.all()}
                for item_data in items_data:
                    item = item_map.get(str(item_data['id']))
                    if not item:
                        continue
                    item.quoted_rate = item_data['quoted_rate']
                    if 'remarks' in item_data:
                        item.remarks = item_data['remarks']
                    item.save()  # recalculates amount = quantity × quoted_rate

            # Recompute quotation total from current item amounts
            instance.total_amount = sum(
                (i.amount or Decimal('0') for i in instance.items.all()),
                Decimal('0')
            )
            instance.save()

        return instance

    def to_representation(self, instance):
        return VendorQuotationSerializer(instance).data


class QuotationItemsForEntrySerializer(serializers.Serializer):
    vendor_item_id = serializers.UUIDField(source='id')
    product_id = serializers.UUIDField(source='product.id')
    product_code = serializers.CharField(source='product.item_code')
    product_name = serializers.CharField(source='product.item_name')
    unit = serializers.CharField(source='product.unit')
    quantity = serializers.DecimalField(max_digits=10, decimal_places=2)
    remarks = serializers.CharField(source='requisition_item.remarks', allow_blank=True)


class RequisitionFlowSerializer(serializers.Serializer):
    """Complete flow: Requisition → Vendors → Quotations"""
    requisition = RequisitionSerializer(source='*')
    vendor_assignments = serializers.SerializerMethodField()

    def get_vendor_assignments(self, obj):
        assignments = VendorRequisitionAssignment.objects.filter(
            requisition=obj
        ).select_related('vendor', 'assigned_by').prefetch_related(
            'items__product', 'quotations__items__product'
        )

        flow_data = []
        for assignment in assignments:
            vendor_data = {
                'assignment_id': assignment.id,
                'vendor': VendorSerializer(assignment.vendor).data,
                'assignment_date': assignment.assignment_date,
                'assigned_items': [],
                'quotations': []
            }

            for item in assignment.items.all():
                vendor_data['assigned_items'].append({
                    'id': item.id,
                    'product': {
                        'id': item.product.id,
                        'item_code': item.product.item_code,
                        'item_name': item.product.item_name,
                        'unit': item.product.unit
                    },
                    'quantity': item.quantity
                })

            for quotation in assignment.quotations.all():
                quotation_data = {
                    'quotation_number': quotation.quotation_number,
                    'quotation_date': quotation.quotation_date,
                    'currency': quotation.currency,
                    'total_amount': quotation.total_amount,
                    'is_selected': quotation.is_selected,
                    'items': []
                }

                for q_item in quotation.items.all():
                    quotation_data['items'].append({
                        'product_code': q_item.product.item_code,
                        'product_name': q_item.product.item_name,
                        'quantity': q_item.quantity,
                        'quoted_rate': q_item.quoted_rate,
                        'amount': q_item.amount,
                    })

                vendor_data['quotations'].append(quotation_data)

            flow_data.append(vendor_data)

        return flow_data
