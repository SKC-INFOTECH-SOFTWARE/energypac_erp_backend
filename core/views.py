from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import viewsets, status, filters
from django_filters.rest_framework import DjangoFilterBackend
from .models import Currency, ExchangeRate
from .serializers import CurrencySerializer, ExchangeRateSerializer, ExchangeRateCreateUpdateSerializer
from .permissions import IsAdmin


class CurrencyViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    queryset = Currency.objects.all()
    serializer_class = CurrencySerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['is_active']
    search_fields = ['code', 'name']
    ordering = ['code']


class CurrentExchangeRateView(APIView):
    """GET /api/exchange-rate — returns the current active USD to INR rate."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            rate = ExchangeRate.get_current_rate()
            obj = ExchangeRate.objects.filter(is_active=True).order_by(
                '-effective_date', '-created_at'
            ).first()
            return Response({
                'currency_from': 'USD',
                'currency_to': 'INR',
                'rate': float(rate),
                'effective_date': obj.effective_date.isoformat(),
                'updated_at': obj.updated_at.isoformat(),
            })
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_404_NOT_FOUND)


class ExchangeRateListCreateView(APIView):
    """
    Currency Master API for exchange rates.

    GET  /api/admin/exchange-rates       — List all exchange rates (history)
    POST /api/admin/exchange-rates       — Create a new exchange rate
    """
    permission_classes = [IsAdmin]

    def get(self, request):
        rates = ExchangeRate.objects.all().order_by('-effective_date', '-created_at')
        serializer = ExchangeRateSerializer(rates, many=True)
        return Response({
            'count': rates.count(),
            'results': serializer.data,
        })

    def post(self, request):
        serializer = ExchangeRateCreateUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        rate_obj = serializer.save(updated_by=request.user)
        return Response(
            ExchangeRateSerializer(rate_obj).data,
            status=status.HTTP_201_CREATED
        )


class ExchangeRateDetailView(APIView):
    """
    Currency Master API for single exchange rate.

    GET    /api/admin/exchange-rates/{id}   — Get details
    PUT    /api/admin/exchange-rates/{id}   — Full update
    PATCH  /api/admin/exchange-rates/{id}   — Partial update
    DELETE /api/admin/exchange-rates/{id}   — Delete (only if not active)
    """
    permission_classes = [IsAdmin]

    def get_object(self, pk):
        try:
            return ExchangeRate.objects.get(pk=pk)
        except ExchangeRate.DoesNotExist:
            return None

    def get(self, request, pk):
        obj = self.get_object(pk)
        if not obj:
            return Response({'error': 'Exchange rate not found'}, status=status.HTTP_404_NOT_FOUND)
        return Response(ExchangeRateSerializer(obj).data)

    def put(self, request, pk):
        obj = self.get_object(pk)
        if not obj:
            return Response({'error': 'Exchange rate not found'}, status=status.HTTP_404_NOT_FOUND)

        serializer = ExchangeRateCreateUpdateSerializer(obj, data=request.data)
        serializer.is_valid(raise_exception=True)
        rate_obj = serializer.save(updated_by=request.user)
        return Response(ExchangeRateSerializer(rate_obj).data)

    def patch(self, request, pk):
        obj = self.get_object(pk)
        if not obj:
            return Response({'error': 'Exchange rate not found'}, status=status.HTTP_404_NOT_FOUND)

        serializer = ExchangeRateCreateUpdateSerializer(obj, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        rate_obj = serializer.save(updated_by=request.user)
        return Response(ExchangeRateSerializer(rate_obj).data)

    def delete(self, request, pk):
        obj = self.get_object(pk)
        if not obj:
            return Response({'error': 'Exchange rate not found'}, status=status.HTTP_404_NOT_FOUND)

        if obj.is_active:
            return Response(
                {'error': 'Cannot delete the active exchange rate. Deactivate it first or set another rate as active.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        obj.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
