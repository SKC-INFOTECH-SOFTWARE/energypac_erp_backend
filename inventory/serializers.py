# inventory/serializers.py

from rest_framework import serializers
from .models import Product


class ProductSerializer(serializers.ModelSerializer):

    class Meta:
        model  = Product
        fields = [
            'id', 'item_code', 'item_name', 'description', 'hsn_code',
            'unit', 'current_stock', 'reorder_level', 'rate', 'is_active',
            'created_at', 'updated_at'
        ]
        # item_code is auto-generated — never writable from API
        read_only_fields = ['id', 'item_code', 'created_at', 'updated_at']
