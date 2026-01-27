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

# Create router
router = DefaultRouter(trailing_slash=False)
router.register(r'products', ProductViewSet, basename='product')
router.register(r'vendors', VendorViewSet, basename='vendor')
router.register(r'requisitions', RequisitionViewSet, basename='requisition')
router.register(r'vendor-assignments', VendorAssignmentViewSet, basename='vendor-assignment')

urlpatterns = [
    path('admin/', admin.site.urls),

    # Auth endpoints
    path('api/auth/login', LoginView.as_view(), name='login'),
    path('api/auth/refresh', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/auth/profile', ProfileView.as_view(), name='profile'),

    # All API endpoints
    path('api/', include(router.urls)),

    # OpenAPI schema
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs', SpectacularSwaggerView.as_view(url_name='schema')),
    path('api/playground', SpectacularRedocView.as_view(url_name='schema')),
]
