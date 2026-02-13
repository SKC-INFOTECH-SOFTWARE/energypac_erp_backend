from rest_framework import serializers
from .models import Bill, BillItem
from work_orders.models import WorkOrder, WorkOrderItem
from decimal import Decimal


class BillItemSerializer(serializers.ModelSerializer):
    """Serializer for bill items"""

    class Meta:
        model = BillItem
        fields = [
            'id', 'work_order_item', 'product', 'item_code', 'item_name',
            'description', 'hsn_code', 'unit', 'ordered_quantity',
            'previously_delivered_quantity', 'delivered_quantity',
            'pending_quantity', 'rate', 'amount', 'remarks'
        ]
        read_only_fields = [
            'id', 'product', 'item_code', 'item_name', 'description',
            'hsn_code', 'unit', 'ordered_quantity',
            'previously_delivered_quantity', 'pending_quantity',
            'rate', 'amount'
        ]


class BillSerializer(serializers.ModelSerializer):
    """Serializer for viewing bills"""
    items = BillItemSerializer(many=True, read_only=True)
    wo_number = serializers.CharField(source='work_order.wo_number', read_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    total_items = serializers.SerializerMethodField()
    total_gst = serializers.SerializerMethodField()

    class Meta:
        model = Bill
        fields = [
            'id', 'bill_number', 'work_order', 'wo_number', 'bill_date',
            'client_name', 'contact_person', 'phone', 'email', 'address',
            'subtotal', 'cgst_percentage', 'sgst_percentage', 'igst_percentage',
            'cgst_amount', 'sgst_amount', 'igst_amount', 'total_gst',
            'total_amount', 'advance_deducted', 'net_payable',
            'amount_paid', 'balance', 'remarks', 'status',
            'created_by', 'created_by_name', 'total_items', 'items',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'bill_number', 'subtotal', 'cgst_amount', 'sgst_amount',
            'igst_amount', 'total_amount', 'advance_deducted', 'net_payable',
            'balance', 'created_at', 'updated_at'
        ]

    def get_total_items(self, obj):
        return obj.items.count()

    def get_total_gst(self, obj):
        return float(obj.cgst_amount + obj.sgst_amount + obj.igst_amount)


class BillItemInputSerializer(serializers.Serializer):
    """Input serializer for bill items during creation"""
    work_order_item = serializers.UUIDField(required=True)
    delivered_quantity = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=True,
        help_text="Quantity being delivered in THIS bill"
    )
    remarks = serializers.CharField(required=False, allow_blank=True)


class BillCreateSerializer(serializers.Serializer):
    """
    Serializer for creating bills from work order
    WITH AUTOMATIC STOCK DEDUCTION
    """
    work_order = serializers.UUIDField(help_text="Work Order ID")
    bill_date = serializers.DateField(input_formats=['%Y-%m-%d', '%d-%m-%Y'])
    remarks = serializers.CharField(required=False, allow_blank=True)
    items = serializers.ListField(
        child=BillItemInputSerializer(),
        help_text="List of items being delivered"
    )

    def validate_work_order(self, value):
        """Check if work order exists and is not completed"""
        try:
            work_order = WorkOrder.objects.get(id=value)
        except WorkOrder.DoesNotExist:
            raise serializers.ValidationError("Work order not found")

        if work_order.status == 'COMPLETED':
            raise serializers.ValidationError("Work order is already completed")

        return value

    def validate_items(self, value):
        """Validate items and check stock availability"""
        if not value:
            raise serializers.ValidationError("At least one item is required")

        for item_data in value:
            # Check work order item exists
            try:
                wo_item = WorkOrderItem.objects.get(id=item_data['work_order_item'])
            except WorkOrderItem.DoesNotExist:
                raise serializers.ValidationError(
                    f"Work order item {item_data['work_order_item']} not found"
                )

            # Check if quantity exceeds pending
            delivered_qty = item_data['delivered_quantity']
            if delivered_qty > wo_item.pending_quantity:
                raise serializers.ValidationError(
                    f"Cannot deliver {delivered_qty} of {wo_item.item_name}. "
                    f"Only {wo_item.pending_quantity} pending."
                )

            # CRITICAL: Check stock availability
            if wo_item.product:
                current_stock = wo_item.product.current_stock
                if current_stock < delivered_qty:
                    raise serializers.ValidationError(
                        f"Insufficient stock for {wo_item.item_name}. "
                        f"Available: {current_stock}, Requested: {delivered_qty}"
                    )

        return value

    def create(self, validated_data):
        items_data = validated_data.pop('items')
        work_order = WorkOrder.objects.get(id=validated_data.pop('work_order'))
        created_by = validated_data.pop('created_by')

        # Create bill
        bill = Bill.objects.create(
            work_order=work_order,
            bill_date=validated_data['bill_date'],
            client_name=work_order.client_name,
            contact_person=work_order.contact_person,
            phone=work_order.phone,
            email=work_order.email,
            address=work_order.address,
            remarks=validated_data.get('remarks', ''),
            created_by=created_by
        )

        # Create bill items
        for item_data in items_data:
            wo_item = WorkOrderItem.objects.get(id=item_data['work_order_item'])

            BillItem.objects.create(
                bill=bill,
                work_order_item=wo_item,
                delivered_quantity=item_data['delivered_quantity'],
                remarks=item_data.get('remarks', '')
            )

        # Calculate totals
        bill.calculate_totals()

        # Update work order advance
        bill.update_work_order_advance()

        # CRITICAL: Deduct stock automatically
        bill.deduct_stock()

        return bill

    def to_representation(self, instance):
        return BillSerializer(instance).data


class StockValidationSerializer(serializers.Serializer):
    """Serializer for pre-bill stock validation"""
    work_order = serializers.UUIDField()
    items = serializers.ListField(
        child=BillItemInputSerializer()
    )

    def validate_items(self, value):
        """Check stock for all items"""
        stock_issues = []

        for item_data in value:
            try:
                wo_item = WorkOrderItem.objects.get(id=item_data['work_order_item'])
                delivered_qty = item_data['delivered_quantity']

                # Check pending quantity
                if delivered_qty > wo_item.pending_quantity:
                    stock_issues.append({
                        'item_code': wo_item.item_code,
                        'item_name': wo_item.item_name,
                        'issue': 'EXCEEDS_PENDING',
                        'message': f"Delivery quantity {delivered_qty} exceeds pending {wo_item.pending_quantity}",
                        'requested': float(delivered_qty),
                        'pending': float(wo_item.pending_quantity)
                    })
                    continue

                # Check stock availability
                if wo_item.product:
                    current_stock = wo_item.product.current_stock
                    if current_stock < delivered_qty:
                        stock_issues.append({
                            'item_code': wo_item.item_code,
                            'item_name': wo_item.item_name,
                            'issue': 'INSUFFICIENT_STOCK',
                            'message': f"Insufficient stock. Available: {current_stock}, Requested: {delivered_qty}",
                            'available': float(current_stock),
                            'requested': float(delivered_qty)
                        })

            except WorkOrderItem.DoesNotExist:
                stock_issues.append({
                    'item_id': str(item_data['work_order_item']),
                    'issue': 'ITEM_NOT_FOUND',
                    'message': 'Work order item not found'
                })

        if stock_issues:
            raise serializers.ValidationError({
                'stock_validation_failed': True,
                'issues': stock_issues
            })

        return value
