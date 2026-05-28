from rest_framework import generics, filters
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend

from .models import AuditLog
from .serializers import AuditLogSerializer


class AuditLogListView(generics.ListAPIView):
    """
    GET /api/audit-logs — list all audit logs (newest first).

    Query params:
        model_name   — filter by model (e.g. PurchaseOrder)
        object_id    — filter by specific object
        user         — filter by user ID
        action       — CREATE / UPDATE / DELETE
        search       — search object_repr, user_name
    """
    permission_classes = [IsAuthenticated]
    serializer_class = AuditLogSerializer
    queryset = AuditLog.objects.all().select_related('user')
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['model_name', 'object_id', 'user', 'action']
    search_fields = ['object_repr', 'user_name']
    ordering_fields = ['timestamp']
    ordering = ['-timestamp']


class AuditLogByObjectView(generics.ListAPIView):
    """
    GET /api/audit-logs/<model_name>/<object_id> — history for one object.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = AuditLogSerializer

    def get_queryset(self):
        return AuditLog.objects.filter(
            model_name=self.kwargs['model_name'],
            object_id=self.kwargs['object_id'],
        ).select_related('user')
