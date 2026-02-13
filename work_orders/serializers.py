from rest_framework import serializers
from .models import WorkOrder, WorkOrderItem
from sales.models import SalesQuotation, SalesQuotationItem
from inventory.models import Product
from decimal import Decimal


class WorkOrderItemSerializer(serializers.ModelSerializer):
    """Serializer for work order items"""
    stock_status = serializers.SerializerMethodField()

    class Meta:
        model = WorkOrderItem
        fields = [
            'id', 'product', 'item_code', 'item_name', 'description',
            'hsn_code', 'unit', 'ordered_quantity', 'delivered_quantity',
            'pending_quantity', 'rate', 'amount', 'stock_available',
            'stock_quantity', 'stock_status', 'remarks'
        ]
        read_only_fields = ['id', 'delivered_quantity', 'pending_quantity', 'amount']

    def get_stock_status(self, obj):
        return obj.get_stock_status()


class WorkOrderSerializer(serializers.ModelSerializer):
    """Serializer for viewing work orders"""
    items = WorkOrderItemSerializer(many=True, read_only=True)
    quotation_number = serializers.CharField(source='sales_quotation.quotation_number', read_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    total_items = serializers.SerializerMethodField()
    completion_percentage = serializers.SerializerMethodField()

    class Meta:
        model = WorkOrder
        fields = [
            'id', 'wo_number', 'sales_quotation', 'quotation_number', 'wo_date',
            'client_name', 'contact_person', 'phone', 'email', 'address',
            'subtotal', 'cgst_percentage', 'sgst_percentage', 'igst_percentage',
            'cgst_amount', 'sgst_amount', 'igst_amount', 'total_amount',
            'advance_amount', 'advance_deducted', 'advance_remaining',
            'total_delivered_value', 'remarks', 'status', 'created_by',
            'created_by_name', 'total_items', 'completion_percentage',
            'items', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'wo_number', 'subtotal', 'cgst_amount', 'sgst_amount',
            'igst_amount', 'total_amount', 'advance_deducted',
            'advance_remaining', 'total_delivered_value', 'created_at', 'updated_at'
        ]

    def get_total_items(self, obj):
        return obj.items.count()

    def get_completion_percentage(self, obj):
        items = obj.items.all()
        if not items:
            return 0

        total_ordered = sum(item.ordered_quantity for item in items)
        total_delivered = sum(item.delivered_quantity for item in items)

        if total_ordered == 0:
            return 0

        return round((total_delivered / total_ordered) * 100, 2)


class WorkOrderItemInputSerializer(serializers.Serializer):
    """Input serializer for WO items during creation"""
    quotation_item = serializers.UUIDField(
        required=True,
        help_text="SalesQuotationItem ID"
    )
    ordered_quantity = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        help_text="Override quantity (optional)"
    )
    rate = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        help_text="Override rate (optional)"
    )
    remarks = serializers.CharField(
        required=False,
        allow_blank=True
    )


class WorkOrderCreateSerializer(serializers.Serializer):
    """
    Serializer for creating work orders from quotation
    """
    sales_quotation = serializers.UUIDField(help_text="Sales Quotation ID")
    wo_number = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Manual WO number (optional - will auto-generate if not provided)"
    )
    wo_date = serializers.DateField(input_formats=['%Y-%m-%d', '%d-%m-%Y'])
    advance_amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Advance payment received"
    )
    remarks = serializers.CharField(required=False, allow_blank=True)
    items = serializers.ListField(
        child=WorkOrderItemInputSerializer(),
        help_text="List of items with optional quantity/rate overrides"
    )

    def validate_sales_quotation(self, value):
        """Check if quotation exists and doesn't have WO already"""
        try:
            quotation = SalesQuotation.objects.get(id=value)
        except SalesQuotation.DoesNotExist:
            raise serializers.ValidationError("Sales quotation not found")

        # Check if WO already exists for this quotation
        if hasattr(quotation, 'work_order'):
            raise serializers.ValidationError(
                f"Work order already exists for this quotation: {quotation.work_order.wo_number}"
            )

        return value

    def validate_wo_number(self, value):
        """Check if manual WO number is unique"""
        if value and WorkOrder.objects.filter(wo_number=value).exists():
            raise serializers.ValidationError("Work order number already exists")
        return value

    def validate_items(self, value):
        """Validate items"""
        if not value:
            raise serializers.ValidationError("At least one item is required")

        # Validate each quotation item exists
        for item_data in value:
            try:
                SalesQuotationItem.objects.get(id=item_data['quotation_item'])
            except SalesQuotationItem.DoesNotExist:
                raise serializers.ValidationError(
                    f"Quotation item {item_data['quotation_item']} not found"
                )

        return value

    def create(self, validated_data):
        items_data = validated_data.pop('items')
        quotation = SalesQuotation.objects.get(id=validated_data.pop('sales_quotation'))
        created_by = validated_data.pop('created_by')
        wo_number = validated_data.pop('wo_number', '')

        # Create work order
        work_order = WorkOrder.objects.create(
            wo_number=wo_number or '',  # Will auto-generate in save()
            sales_quotation=quotation,
            wo_date=validated_data['wo_date'],
            client_name=quotation.client_query.client_name,
            contact_person=quotation.client_query.contact_person,
            phone=quotation.client_query.phone,
            email=quotation.client_query.email,
            address=quotation.client_query.address,
            cgst_percentage=quotation.cgst_percentage,
            sgst_percentage=quotation.sgst_percentage,
            igst_percentage=quotation.igst_percentage,
            advance_amount=validated_data['advance_amount'],
            remarks=validated_data.get('remarks', ''),
            created_by=created_by
        )

        # Create work order items
        total_subtotal = Decimal('0')

        for item_data in items_data:
            q_item = SalesQuotationItem.objects.get(id=item_data['quotation_item'])

            # Use override values if provided, otherwise use quotation values
            ordered_qty = item_data.get('ordered_quantity', q_item.quantity)
            rate = item_data.get('rate', q_item.rate)

            WorkOrderItem.objects.create(
                work_order=work_order,
                product=q_item.product,
                item_code=q_item.item_code,
                item_name=q_item.item_name,
                description=q_item.description,
                hsn_code=q_item.hsn_code,
                unit=q_item.unit,
                ordered_quantity=ordered_qty,
                rate=rate,
                remarks=item_data.get('remarks', '')
            )

            total_subtotal += ordered_qty * rate

        # Calculate totals
        work_order.subtotal = total_subtotal
        work_order.cgst_amount = (total_subtotal * work_order.cgst_percentage) / 100
        work_order.sgst_amount = (total_subtotal * work_order.sgst_percentage) / 100
        work_order.igst_amount = (total_subtotal * work_order.igst_percentage) / 100
        work_order.total_amount = (
            total_subtotal +
            work_order.cgst_amount +
            work_order.sgst_amount +
            work_order.igst_amount
        )
        work_order.save()

        return work_order

    def to_representation(self, instance):
        return WorkOrderSerializer(instance).data


class StockAvailabilitySerializer(serializers.Serializer):
    """Serializer for stock availability check"""
    item_id = serializers.UUIDField()
    item_code = serializers.CharField()
    item_name = serializers.CharField()
    pending_quantity = serializers.DecimalField(max_digits=10, decimal_places=2)
    current_stock = serializers.DecimalField(max_digits=10, decimal_places=2)
    status = serializers.CharField()
    message = serializers.CharField()


class FinancialSummarySerializer(serializers.Serializer):
    """Serializer for financial summary"""
    total_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    advance_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    advance_deducted = serializers.DecimalField(max_digits=12, decimal_places=2)
    advance_remaining = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_delivered_value = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_pending_value = serializers.DecimalField(max_digits=12, decimal_places=2)


class DeliverySummarySerializer(serializers.Serializer):
    """Serializer for delivery summary"""
    total_items = serializers.IntegerField()
    fully_delivered_items = serializers.IntegerField()
    partially_delivered_items = serializers.IntegerField()
    pending_items = serializers.IntegerField()
    completion_percentage = serializers.DecimalField(max_digits=5, decimal_places=2)
