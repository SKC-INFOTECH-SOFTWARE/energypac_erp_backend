from rest_framework import serializers
from .models import Currency, ExchangeRate


class CurrencySerializer(serializers.ModelSerializer):
    class Meta:
        model = Currency
        fields = ['id', 'code', 'name', 'symbol', 'is_active', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_code(self, value):
        return value.upper().strip()


class ExchangeRateSerializer(serializers.ModelSerializer):
    updated_by_name = serializers.CharField(
        source='updated_by.get_full_name', read_only=True
    )

    class Meta:
        model = ExchangeRate
        fields = [
            'id', 'rate', 'effective_date', 'is_active',
            'remarks', 'updated_by', 'updated_by_name',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'updated_by', 'created_at', 'updated_at']


class ExchangeRateCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExchangeRate
        fields = ['rate', 'effective_date', 'is_active', 'remarks']

    def validate_rate(self, value):
        if value <= 0:
            raise serializers.ValidationError("Exchange rate must be greater than 0")
        return value
