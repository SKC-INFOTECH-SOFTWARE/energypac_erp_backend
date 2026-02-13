from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)
# Import views
from accounts.views import LoginView, ProfileView
from inventory.views import ProductViewSet
from vendors.views import VendorViewSet
from requisitions.views import RequisitionViewSet, VendorAssignmentViewSet
from requisitions.views import VendorQuotationViewSet
from purchase_orders.views import PurchaseOrderViewSet
from dashboard.views import DashboardStatsView
from work_orders.views import WorkOrderViewSet
from billing.views import BillViewSet
from reports.views import (
    # Requisition Reports
    RequisitionReportView,
    RequisitionDetailedReportView,

    # Vendor Reports
    VendorPerformanceReportView,
    VendorQuotationComparisonReportView,

    # Purchase Order Reports
    PurchaseOrderReportView,

    # Inventory Reports
    InventoryStockReportView,
    InventoryMovementReportView,

    # Financial Reports
    SpendingAnalysisReportView,
)
from sales.views import (
    ClientQueryViewSet,
    SalesQuotationViewSet,
    SalesQuotationItemViewSet
)
from sales.reports_views import (
    ClientQueryReportView,
    ClientQueryDetailedReportView,
    SalesQuotationReportView,
    QuotationItemsReportView,
    SalesAnalyticsView,
    SalesPerformanceView,
    SalesDashboardStatsView,
    ProductSalesAnalysisView,
)



# Create router
router = DefaultRouter(trailing_slash=False)
router.register(r'products', ProductViewSet, basename='product')
router.register(r'vendors', VendorViewSet, basename='vendor')
router.register(r'requisitions', RequisitionViewSet, basename='requisition')
router.register(r'vendor-assignments', VendorAssignmentViewSet, basename='vendor-assignment')
router.register(r'vendor-quotations', VendorQuotationViewSet, basename='vendor-quotation')
router.register(r'purchase-orders', PurchaseOrderViewSet, basename='purchase-order')
router.register(r'client-queries', ClientQueryViewSet, basename='client-query')
router.register(r'quotations', SalesQuotationViewSet, basename='sales-quotation')
router.register(r'quotation-items', SalesQuotationItemViewSet, basename='quotation-item')
router.register(r'work-orders', WorkOrderViewSet, basename='work-order')
router.register(r'bills', BillViewSet, basename='bill')
urlpatterns = [
    path('admin/', admin.site.urls),

    # Auth endpoints
    path('api/auth/login', LoginView.as_view(), name='login'),
    path('api/auth/refresh', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/auth/profile', ProfileView.as_view(), name='profile'),

    # All API endpoints
    path('api/', include(router.urls)),
    path('api/dashboard/stats', DashboardStatsView.as_view(), name='dashboard-stats'),
    path('api/sales/', include(router.urls)),

    # OpenAPI schema
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs', SpectacularSwaggerView.as_view(url_name='schema')),
    path('api/playground', SpectacularRedocView.as_view(url_name='schema')),

# ===== REQUISITION REPORTS =====
    path('api/reports/requisitions',
         RequisitionReportView.as_view(),
         name='report-requisitions'),

    path('api/reports/requisitions/<uuid:pk>/detailed',
         RequisitionDetailedReportView.as_view(),
         name='report-requisition-detailed'),

    # ===== VENDOR REPORTS =====
    path('api/reports/vendors/performance',
         VendorPerformanceReportView.as_view(),
         name='report-vendor-performance'),

    path('api/reports/vendors/quotation-comparison',
         VendorQuotationComparisonReportView.as_view(),
         name='report-quotation-comparison'),

    # ===== PURCHASE ORDER REPORTS =====
    path('api/reports/purchase-orders',
         PurchaseOrderReportView.as_view(),
         name='report-purchase-orders'),

    # ===== INVENTORY REPORTS =====
    path('api/reports/inventory/stock',
         InventoryStockReportView.as_view(),
         name='report-inventory-stock'),

    path('api/reports/inventory/movement',
         InventoryMovementReportView.as_view(),
         name='report-inventory-movement'),

    # ===== FINANCIAL REPORTS =====
    path('api/reports/financial/spending',
         SpendingAnalysisReportView.as_view(),
         name='report-spending-analysis'),

    # ===== SALES REPORTS =====
    path('api/reports/sales/client-queries',
        ClientQueryReportView.as_view(),
        name='report-sales-client-queries'),

    path('api/reports/sales/client-queries/<uuid:pk>/detailed',
        ClientQueryDetailedReportView.as_view(),
        name='report-sales-client-query-detailed'),

    path('api/reports/sales/quotations',
        SalesQuotationReportView.as_view(),
        name='report-sales-quotations'),

    path('api/reports/sales/quotation-items',
        QuotationItemsReportView.as_view(),
        name='report-sales-quotation-items'),

    path('api/reports/sales/analytics',
        SalesAnalyticsView.as_view(),
        name='report-sales-analytics'),

    path('api/reports/sales/performance',
        SalesPerformanceView.as_view(),
        name='report-sales-performance'),

    path('api/reports/sales/products',
        ProductSalesAnalysisView.as_view(),
        name='report-sales-products'),

    path('api/dashboard/sales/stats',
        SalesDashboardStatsView.as_view(),
        name='dashboard-sales-stats'),
]
