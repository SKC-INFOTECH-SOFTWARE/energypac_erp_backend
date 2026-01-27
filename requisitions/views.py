# requisitions/views.py
from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from .models import (Requisition, VendorRequisitionAssignment, VendorQuotation)
from .serializers import (
    RequisitionSerializer,
    RequisitionCreateSerializer,
    VendorRequisitionAssignmentSerializer,
    VendorAssignmentCreateSerializer,
    VendorQuotationSerializer,
    VendorQuotationCreateSerializer,
    RequisitionFlowSerializer,
    QuotationItemsForEntrySerializer,
)


# ====================== RequisitionViewSet ======================
class RequisitionViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Requisition CRUD
    """
    queryset = Requisition.objects.all().select_related('created_by').prefetch_related('items__product')
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['is_assigned', 'requisition_date', 'created_by']
    search_fields = ['requisition_number', 'remarks']
    ordering_fields = ['requisition_date', 'created_at', 'requisition_number']
    ordering = ['-requisition_number']

    def get_serializer_class(self):
        if self.action == 'create':
            return RequisitionCreateSerializer
        return RequisitionSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def destroy(self, request, *args, **kwargs):
        return Response(
            {
                'error': 'Requisitions cannot be deleted',
                'message': 'Once created, requisitions are permanent for audit purposes'
            },
            status=status.HTTP_403_FORBIDDEN
        )

    @action(detail=True, methods=['get'])
    def items(self, request, pk=None):
        """Get all items for a specific requisition"""
        requisition = self.get_object()
        from .serializers import RequisitionItemSerializer
        items = requisition.items.all()
        serializer = RequisitionItemSerializer(items, many=True)
        return Response({
            'requisition_number': requisition.requisition_number,
            'total_items': items.count(),
            'items': serializer.data
        })

    @action(detail=True, methods=['get'])
    def assignments(self, request, pk=None):
        """Get all vendor assignments for a requisition"""
        requisition = self.get_object()
        assignments = VendorRequisitionAssignment.objects.filter(
            requisition=requisition
        ).select_related('vendor', 'assigned_by').prefetch_related('items')
        serializer = VendorRequisitionAssignmentSerializer(assignments, many=True)
        return Response({
            'requisition_number': requisition.requisition_number,
            'total_assignments': assignments.count(),
            'assignments': serializer.data
        })

    @action(detail=True, methods=['get'])
    def flow(self, request, pk=None):
        """Get complete flow: Requisition → Vendors → Quotations"""
        requisition = self.get_object()
        serializer = RequisitionFlowSerializer(requisition)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def comparison(self, request, pk=None):
        """Compare all vendor quotations for this requisition"""
        requisition = self.get_object()
        assignments = VendorRequisitionAssignment.objects.filter(
            requisition=requisition
        ).select_related('vendor').prefetch_related(
            'quotations__items__product'
        )
        comparison_data = {
            'requisition_number': requisition.requisition_number,
            'requisition_date': requisition.requisition_date,
            'vendors': []
        }
        for assignment in assignments:
            vendor_info = {
                'vendor_name': assignment.vendor.vendor_name,
                'vendor_code': assignment.vendor.vendor_code,
                'quotations': []
            }
            for quotation in assignment.quotations.all():
                quotation_info = {
                    'quotation_number': quotation.quotation_number,
                    'quotation_date': quotation.quotation_date,
                    'total_amount': quotation.total_amount,
                    'is_selected': quotation.is_selected,
                    'items': []
                }
                for item in quotation.items.all():
                    quotation_info['items'].append({
                        'product_code': item.product.item_code,
                        'product_name': item.product.item_name,
                        'quantity': item.quantity,
                        'unit': item.product.unit,
                        'quoted_rate': item.quoted_rate,
                        'amount': item.final_amount   # Changed as per your request
                    })
                vendor_info['quotations'].append(quotation_info)
            comparison_data['vendors'].append(vendor_info)
        return Response(comparison_data)


# ====================== VendorAssignmentViewSet ======================
class VendorAssignmentViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Vendor Assignment CRUD
    """
    queryset = VendorRequisitionAssignment.objects.all().select_related(
        'requisition', 'vendor', 'assigned_by'
    ).prefetch_related('items__product')
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['requisition', 'vendor', 'assignment_date']
    search_fields = ['requisition__requisition_number', 'vendor__vendor_name']
    ordering_fields = ['assignment_date', 'created_at']
    ordering = ['-created_at']

    def get_serializer_class(self):
        if self.action == 'create':
            return VendorAssignmentCreateSerializer
        return VendorRequisitionAssignmentSerializer

    def perform_create(self, serializer):
        serializer.save(assigned_by=self.request.user)

    def destroy(self, request, *args, **kwargs):
        return Response(
            {
                'error': 'Vendor assignments cannot be deleted',
                'message': 'Assignments are permanent for audit trail'
            },
            status=status.HTTP_403_FORBIDDEN
        )

    @action(detail=True, methods=['get'])
    def items_for_quotation(self, request, pk=None):
        """Get all items for quotation entry (product + quantity)"""
        assignment = self.get_object()
        items = assignment.items.all().select_related('product', 'requisition_item')
        serializer = QuotationItemsForEntrySerializer(items, many=True)
        return Response({
            'assignment_id': assignment.id,
            'requisition_number': assignment.requisition.requisition_number,
            'vendor_name': assignment.vendor.vendor_name,
            'vendor_code': assignment.vendor.vendor_code,
            'items': serializer.data
        })


# ====================== VendorQuotationViewSet ======================
class VendorQuotationViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Vendor Quotation CRUD
    """
    queryset = VendorQuotation.objects.all().select_related(
        'assignment__vendor', 'assignment__requisition', 'created_by'
    ).prefetch_related('items__product')
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['assignment', 'assignment__vendor', 'assignment__requisition',
                        'is_selected', 'quotation_date']
    search_fields = ['quotation_number', 'reference_number']
    ordering_fields = ['quotation_date', 'created_at', 'total_amount']
    ordering = ['-quotation_number']

    def get_serializer_class(self):
        if self.action == 'create':
            return VendorQuotationCreateSerializer
        return VendorQuotationSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def destroy(self, request, *args, **kwargs):
        return Response(
            {
                'error': 'Quotations cannot be deleted',
                'message': 'Quotations are permanent for audit purposes'
            },
            status=status.HTTP_403_FORBIDDEN
        )

    @action(detail=True, methods=['post'])
    def select(self, request, pk=None):
        """Mark this quotation as selected for PO"""
        quotation = self.get_object()
        VendorQuotation.objects.filter(
            assignment__requisition=quotation.assignment.requisition
        ).update(is_selected=False)
        quotation.is_selected = True
        quotation.save()
        serializer = self.get_serializer(quotation)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def by_vendor(self, request):
        """Get quotations by vendor"""
        vendor_id = request.query_params.get('vendor')
        if not vendor_id:
            return Response({'error': 'vendor parameter is required'}, status=status.HTTP_400_BAD_REQUEST)
        quotations = self.queryset.filter(assignment__vendor_id=vendor_id)
        serializer = self.get_serializer(quotations, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def by_requisition(self, request):
        """Get all quotations for a requisition"""
        requisition_id = request.query_params.get('requisition')
        if not requisition_id:
            return Response({'error': 'requisition parameter is required'}, status=status.HTTP_400_BAD_REQUEST)
        quotations = self.queryset.filter(assignment__requisition_id=requisition_id)
        serializer = self.get_serializer(quotations, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def by_requisition_vendor(self, request):
        """Get items for quotation entry using requisition + vendor"""
        requisition_id = request.query_params.get('requisition')
        vendor_id = request.query_params.get('vendor')

        if not requisition_id or not vendor_id:
            return Response(
                {'error': 'Both requisition and vendor parameters are required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            assignment = VendorRequisitionAssignment.objects.get(
                requisition_id=requisition_id,
                vendor_id=vendor_id
            )
        except VendorRequisitionAssignment.DoesNotExist:
            return Response(
                {'error': 'No assignment found for this requisition and vendor'},
                status=status.HTTP_404_NOT_FOUND
            )

        items = assignment.items.all().select_related('product', 'requisition_item')
        serializer = QuotationItemsForEntrySerializer(items, many=True)

        return Response({
            'assignment_id': assignment.id,
            'requisition_number': assignment.requisition.requisition_number,
            'vendor_name': assignment.vendor.vendor_name,
            'vendor_code': assignment.vendor.vendor_code,
            'items': serializer.data
        })
