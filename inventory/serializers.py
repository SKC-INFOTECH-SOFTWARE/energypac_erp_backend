# inventory/serializers.py

from rest_framework import serializers
from .models import Product


class ProductSerializer(serializers.ModelSerializer):

    class Meta:
        model  = Product
        fields = [
            'id', 'item_code', 'item_name', 'description', 'hsn_code',
            'unit', 'current_stock', 'reorder_level', 'rate',
            'requisition_number', 'purchase_count', 'total_purchased_qty',
            'sale_count', 'total_sold_qty',
            'last_purchase_date', 'last_sale_date',
            'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'item_code', 'purchase_count', 'total_purchased_qty',
            'sale_count', 'total_sold_qty',
            'last_purchase_date', 'last_sale_date', 'requisition_number',
            'created_at', 'updated_at'
        ]
