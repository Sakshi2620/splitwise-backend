from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView
from .views import (
    RegisterView, LoginView, MeView,
    UserViewSet, GroupViewSet,
    ExpenseViewSet, NotificationViewSet,
    SettlementViewSet,
)

router = DefaultRouter()
router.register('users',         UserViewSet,         basename='user')
router.register('groups',        GroupViewSet,        basename='group')
router.register('expenses',      ExpenseViewSet,      basename='expense')
router.register('notifications', NotificationViewSet, basename='notification')

urlpatterns = [
    path('auth/register/', RegisterView.as_view()),
    path('auth/login/',    LoginView.as_view()),
    path('auth/refresh/',  TokenRefreshView.as_view()),
    path('auth/me/',       MeView.as_view()),
    path('', include(router.urls)),

    # Settlement routes — explicit paths, no router needed
    path('settlements/group/<int:group_id>/',
         SettlementViewSet.as_view({'get': 'list_for_group'}),
         name='settlement-list'),
    path('settlements/detail/<int:settlement_id>/',
         SettlementViewSet.as_view({'get': 'detail_view'}),
         name='settlement-detail'),
    path('settlements/<int:settlement_id>/pay/',
         SettlementViewSet.as_view({'post': 'pay'}),
         name='settlement-pay'),
]