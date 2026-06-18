from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    SignatureViewSet,
    PIVerificationViewSet,
    POVerificationViewSet,
    NotificationViewSet
)

router = DefaultRouter()
router.register(r'signatures', SignatureViewSet, basename='signature')
router.register(r'pi-verifications', PIVerificationViewSet, basename='pi-verification')
router.register(r'po-verifications', POVerificationViewSet, basename='po-verification')
router.register(r'notifications', NotificationViewSet, basename='notification')

app_name = 'signatures'

urlpatterns = [
    path('', include(router.urls)),

    # PI Verification Endpoints
    path('pi/<uuid:pi_id>/verify/', PIVerificationViewSet.as_view({'post': 'create_request'}), name='pi-create-verification'),
    path('pi/<uuid:pi_id>/self-verify/', PIVerificationViewSet.as_view({'post': 'self_verify'}), name='pi-self-verify'),
    path('pi/<uuid:pi_id>/approve-verification/', PIVerificationViewSet.as_view({'post': 'approve_verification'}), name='pi-approve-verification'),
    path('pi/<uuid:pi_id>/reject-verification/', PIVerificationViewSet.as_view({'post': 'reject_verification'}), name='pi-reject-verification'),
    path('pi/<uuid:pi_id>/verification-chain/', PIVerificationViewSet.as_view({'get': 'verification_chain'}), name='pi-verification-chain'),
    path('pi/<uuid:pi_id>/verification-status/', PIVerificationViewSet.as_view({'get': 'verification_status'}), name='pi-verification-status'),

    # PO Verification Endpoints
    path('po/<uuid:po_id>/verify/', POVerificationViewSet.as_view({'post': 'create_request'}), name='po-create-verification'),
    path('po/<uuid:po_id>/self-verify/', POVerificationViewSet.as_view({'post': 'self_verify'}), name='po-self-verify'),
    path('po/<uuid:po_id>/approve-verification/', POVerificationViewSet.as_view({'post': 'approve_verification'}), name='po-approve-verification'),
    path('po/<uuid:po_id>/reject-verification/', POVerificationViewSet.as_view({'post': 'reject_verification'}), name='po-reject-verification'),
    path('po/<uuid:po_id>/verification-chain/', POVerificationViewSet.as_view({'get': 'verification_chain'}), name='po-verification-chain'),
    path('po/<uuid:po_id>/verification-status/', POVerificationViewSet.as_view({'get': 'verification_status'}), name='po-verification-status'),
]
