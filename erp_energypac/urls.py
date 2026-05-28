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
from accounts.views import (
    LoginView, ProfileView, AdminUserViewSet,
    ForgotPasswordView, VerifyOTPView, ResetPasswordView,
)
from inventory.views import ProductViewSet
from vendors.views import VendorViewSet
from requisitions.views import RequisitionViewSet, VendorAssignmentViewSet
from requisitions.views import VendorQuotationViewSet
from purchase_orders.views import PurchaseOrderViewSet
from dashboard.views import DashboardStatsView
from billing.views import PIBillViewSet
from inventory.views_bulk_upload import ProductBulkUploadView, ProductBulkUploadTemplateView
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
    SalesQuotationItemViewSet,
    ProformaInvoiceViewSet,
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


# Finance app imports
from finance.views import (
    PurchaseOrderFinanceViewSet,
    PIFinanceViewSet,
    AdvancePaymentViewSet,
    AllPurchasePaymentsListView,
    AllPIPaymentsListView,
    FinanceDashboardView,
    ProfitLossReportView,
    ProfitLossItemReportView,
    ProfitPreviewView,
    ItemAnalyticsView,
    ItemInsightsView,
    InventoryAgingView,
    DueDateTrackingView,
    ReconciliationView,
    FinanceValidationView,
)

# Core
from core.views import (
    CurrencyViewSet,
    CurrentExchangeRateView,
    ExchangeRateListCreateView,
    ExchangeRateDetailView,
)

# Audit Logs
from audit_logs.views import AuditLogListView, AuditLogByObjectView

# Transport
from transport.views import (
    TransportEntryViewSet,
    TransportCostByPOReportView,
    TransportCostByVendorReportView,
    TransportCostBreakdownReportView,
    LandedCostReportView,
    TransportDashboardView,
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
router.register(r'pi-bills', PIBillViewSet, basename='pi-bill')
router.register(r'transport', TransportEntryViewSet, basename='transport')
router.register(r'currencies', CurrencyViewSet, basename='currency')
router.register(r'proforma-invoices', ProformaInvoiceViewSet, basename='proforma-invoice')

# Admin router
admin_router = DefaultRouter(trailing_slash=False)
admin_router.register(r'users', AdminUserViewSet, basename='admin-user')

# Finance router
finance_router = DefaultRouter(trailing_slash=False)
finance_router.register(r'purchase-orders', PurchaseOrderFinanceViewSet, basename='finance-purchase-order')
finance_router.register(r'proforma-invoices', PIFinanceViewSet, basename='finance-pi')
finance_router.register(r'advance-payments', AdvancePaymentViewSet, basename='finance-advance')

urlpatterns = [
    path('admin/', admin.site.urls),

    # Auth endpoints
    path('api/auth/login', LoginView.as_view(), name='login'),
    path('api/auth/refresh', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/auth/profile', ProfileView.as_view(), name='profile'),
    path('api/auth/forgot-password', ForgotPasswordView.as_view(), name='forgot-password'),
    path('api/auth/verify-otp', VerifyOTPView.as_view(), name='verify-otp'),
    path('api/auth/reset-password', ResetPasswordView.as_view(), name='reset-password'),

    # Admin endpoints
    path('api/admin/', include(admin_router.urls)),

    
    path('api/products/bulk-upload',ProductBulkUploadView.as_view(), name='product-bulk-upload'),
    path('api/products/bulk-upload-template', ProductBulkUploadTemplateView.as_view(), name='product-bulk-upload-template') ,
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



    # ===== EXCHANGE RATE =====
    path('api/exchange-rate',
        CurrentExchangeRateView.as_view(),
        name='current-exchange-rate'),

    # Admin: Exchange Rate CRUD
    path('api/admin/exchange-rates',
        ExchangeRateListCreateView.as_view(),
        name='admin-exchange-rate-list'),

    path('api/admin/exchange-rates/<uuid:pk>',
        ExchangeRateDetailView.as_view(),
        name='admin-exchange-rate-detail'),

    # ===== AUDIT LOGS =====
    path('api/audit-logs',
        AuditLogListView.as_view(),
        name='audit-log-list'),

    path('api/audit-logs/<str:model_name>/<str:object_id>',
        AuditLogByObjectView.as_view(),
        name='audit-log-by-object'),

    # ===== FINANCE / ACCOUNTS =====
    path('api/finance/', include(finance_router.urls)),

    # Flat payment lists
    path('api/finance/all-purchase-payments',
        AllPurchasePaymentsListView.as_view(),
        name='finance-all-purchase-payments'),

    # Finance dashboard
    path('api/finance/dashboard',
        FinanceDashboardView.as_view(),
        name='finance-dashboard'),

    # PI payments list
    path('api/finance/all-pi-payments',
        AllPIPaymentsListView.as_view(),
        name='finance-all-pi-payments'),

    # Profit & Loss
    path('api/finance/profit-loss',
        ProfitLossReportView.as_view(),
        name='finance-profit-loss'),

    path('api/finance/profit-loss/items',
        ProfitLossItemReportView.as_view(),
        name='finance-profit-loss-items'),

    path('api/finance/profit-preview',
        ProfitPreviewView.as_view(),
        name='finance-profit-preview'),

    # Item Analytics
    path('api/finance/items/analytics',
        ItemAnalyticsView.as_view(),
        name='finance-item-analytics'),

    path('api/finance/items/insights',
        ItemInsightsView.as_view(),
        name='finance-item-insights'),

    path('api/finance/items/aging',
        InventoryAgingView.as_view(),
        name='finance-inventory-aging'),

    # Due dates & Reconciliation
    path('api/finance/due-dates',
        DueDateTrackingView.as_view(),
        name='finance-due-dates'),

    path('api/finance/reconciliation',
        ReconciliationView.as_view(),
        name='finance-reconciliation'),

    path('api/finance/validation',
        FinanceValidationView.as_view(),
        name='finance-validation'),

    # ===== TRANSPORT REPORTS =====
    path('api/reports/transport/by-po',
        TransportCostByPOReportView.as_view(),
        name='report-transport-by-po'),

    path('api/reports/transport/by-vendor',
        TransportCostByVendorReportView.as_view(),
        name='report-transport-by-vendor'),

    path('api/reports/transport/cost-breakdown',
        TransportCostBreakdownReportView.as_view(),
        name='report-transport-cost-breakdown'),

    path('api/reports/transport/landed-cost',
        LandedCostReportView.as_view(),
        name='report-landed-cost'),

    path('api/dashboard/transport',
        TransportDashboardView.as_view(),
        name='dashboard-transport'),

]
