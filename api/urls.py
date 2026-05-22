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
router.register(r'settlements', SettlementViewSet, basename='settlement')
# Nested under groups
settlements_router = DefaultRouter()
settlements_router.register('settlements', SettlementViewSet, basename='group-settlement')

urlpatterns = [
    path('auth/register/', RegisterView.as_view()),
    path('auth/login/',    LoginView.as_view()),
    path('auth/refresh/',  TokenRefreshView.as_view()),
    path('auth/me/',       MeView.as_view()),
    path('', include(router.urls)),
    path('groups/<group_pk>/', include(settlements_router.urls)),
    
]