# requisitions/serializers.py
from rest_framework import serializers
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
        read_only_fields = ['id', 'requisition_number', 'created_by',
                           'is_assigned', 'created_at', 'updated_at']

    def get_total_items(self, obj):
        return obj.items.count()

class RequisitionCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating requisitions"""
    items = RequisitionItemSerializer(many=True)

    class Meta:
        model = Requisition
        fields = ['requisition_date', 'remarks', 'items']

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("At least one item is required")
        return value

    def create(self, validated_data):
        items_data = validated_data.pop('items')
        requisition = Requisition.objects.create(**validated_data)
        for item_data in items_data:
            RequisitionItem.objects.create(requisition=requisition, **item_data)
        return requisition

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

    class Meta:
        model = VendorRequisitionAssignment
        fields = ['id', 'requisition', 'requisition_number', 'vendor',
                  'vendor_details', 'assignment_date', 'remarks', 'assigned_by',
                  'assigned_by_name', 'total_items', 'items', 'created_at']
        read_only_fields = ['id', 'assignment_date', 'assigned_by', 'created_at']

    def get_total_items(self, obj):
        return obj.items.count()

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

    def create(self, validated_data):
        items_data = validated_data.pop('items')
        # Get the actual model instances from UUIDs
        requisition = Requisition.objects.get(id=validated_data['requisition'])
        vendor = Vendor.objects.get(id=validated_data['vendor'])
        assigned_by = validated_data['assigned_by']
        remarks = validated_data.get('remarks', '')
        # Create assignment with actual instances
        assignment = VendorRequisitionAssignment.objects.create(
            requisition=requisition,
            vendor=vendor,
            assigned_by=assigned_by,
            remarks=remarks
        )
        # Create vendor items
        for item_data in items_data:
            req_item = RequisitionItem.objects.get(id=item_data['requisition_item'])
            VendorRequisitionItem.objects.create(
                assignment=assignment,
                requisition_item=req_item,
                product=req_item.product,
                quantity=item_data['quantity']
            )
        # Mark requisition as assigned
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
            'unit', 'quantity', 'quoted_rate', 'amount', 'remarks'
        ]
        read_only_fields = ['id', 'amount']

class VendorQuotationSerializer(serializers.ModelSerializer):
    """Serializer for viewing quotations"""
    items = VendorQuotationItemSerializer(many=True, read_only=True)
    vendor_name = serializers.CharField(source='assignment.vendor.vendor_name', read_only=True)
    vendor_code = serializers.CharField(source='assignment.vendor.vendor_code', read_only=True)
    requisition_number = serializers.CharField(source='assignment.requisition.requisition_number', read_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    total_items = serializers.SerializerMethodField()

    class Meta:
        model = VendorQuotation
        fields = [
            'id', 'quotation_number', 'assignment', 'vendor_name', 'vendor_code',
            'requisition_number', 'quotation_date', 'reference_number',
            'validity_date', 'payment_terms', 'delivery_terms', 'remarks',
            'total_amount', 'is_selected', 'created_by', 'created_by_name',
            'total_items', 'items', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'quotation_number', 'quotation_date', 'created_by',
            'created_at', 'updated_at'
        ]

    def get_total_items(self, obj):
        return obj.items.count()

class QuotationItemInputSerializer(serializers.Serializer):
    vendor_item = serializers.UUIDField(required=True)
    quoted_rate = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=True,
        help_text="Rate quoted by vendor per unit"
    )
    tax_percentage = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False, default=0,
        help_text="GST/Tax percentage"
    )

class VendorQuotationCreateSerializer(serializers.Serializer):
    """
    Serializer for creating vendor quotations

    User provides: requisition_id + vendor_id
    System shows: All items from that requisition
    User enters: quoted_rate for each item
    """
    requisition = serializers.UUIDField(help_text="Requisition ID")
    vendor = serializers.UUIDField(help_text="Vendor ID")
    reference_number = serializers.CharField(required=False, allow_blank=True)
    validity_date = serializers.DateField(required=False, allow_null=True)
    payment_terms = serializers.CharField(required=False, allow_blank=True)
    delivery_terms = serializers.CharField(required=False, allow_blank=True)
    remarks = serializers.CharField(required=False, allow_blank=True)
    items = serializers.ListField(
        child=serializers.DictField(),
        help_text="List of items with vendor_item and quoted_rate"
    )

    def validate(self, data):
        """Validate that assignment exists for this requisition + vendor combination"""
        try:
            assignment = VendorRequisitionAssignment.objects.get(
                requisition_id=data['requisition'],
                vendor_id=data['vendor']
            )
            data['assignment'] = assignment
        except VendorRequisitionAssignment.DoesNotExist:
            raise serializers.ValidationError(
                "No vendor assignment found for this requisition and vendor combination. "
                "Please assign the vendor to the requisition first."
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

            # Validate vendor_item exists
            try:
                VendorRequisitionItem.objects.get(id=item['vendor_item'])
            except VendorRequisitionItem.DoesNotExist:
                raise serializers.ValidationError(f"Vendor item {item['vendor_item']} not found")

        return value

    def create(self, validated_data):
        items_data = validated_data.pop('items')
        assignment = validated_data.pop('assignment')

        # Create quotation
        quotation = VendorQuotation.objects.create(
            assignment=assignment,
            reference_number=validated_data.get('reference_number', ''),
            validity_date=validated_data.get('validity_date'),
            payment_terms=validated_data.get('payment_terms', ''),
            delivery_terms=validated_data.get('delivery_terms', ''),
            remarks=validated_data.get('remarks', ''),
            created_by=validated_data['created_by']
        )

        total_amount = 0

        # Create quotation items
        for item_data in items_data:
            vendor_item = VendorRequisitionItem.objects.get(
                id=item_data['vendor_item']
            )

            quotation_item = VendorQuotationItem.objects.create(
                quotation=quotation,
                vendor_item=vendor_item,
                product=vendor_item.product,
                quantity=vendor_item.quantity,
                quoted_rate=item_data['quoted_rate'],
                remarks=item_data.get('remarks', '')
            )

            total_amount += quotation_item.amount

        # Update quotation total
        quotation.total_amount = total_amount
        quotation.save()

        return quotation

    def to_representation(self, instance):
        return VendorQuotationSerializer(instance).data


class QuotationItemsForEntrySerializer(serializers.Serializer):
    """
    Helper serializer to show items that need quotation entry
    GET /api/vendor-assignments/{id}/items-for-quotation
    """
    vendor_item_id = serializers.UUIDField(source='id')
    product_id = serializers.UUIDField(source='product.id')
    product_code = serializers.CharField(source='product.item_code')
    product_name = serializers.CharField(source='product.item_name')
    unit = serializers.CharField(source='product.unit')
    quantity = serializers.DecimalField(max_digits=10, decimal_places=2)
    remarks = serializers.CharField(source='requisition_item.remarks', allow_blank=True)


class RequisitionFlowSerializer(serializers.Serializer):
    """Complete flow: Requisition → Vendors → Quotations"""
    requisition = RequisitionSerializer()
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

            # Get assigned items
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

            # Get quotations
            for quotation in assignment.quotations.all():
                quotation_data = {
                    'quotation_number': quotation.quotation_number,
                    'quotation_date': quotation.quotation_date,
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
                        'amount': q_item.amount
                    })

                vendor_data['quotations'].append(quotation_data)

            flow_data.append(vendor_data)

        return flow_data
