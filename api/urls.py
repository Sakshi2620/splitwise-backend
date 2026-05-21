from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import UserViewSet, GroupViewSet, ExpenseViewSet

router = DefaultRouter()
router.register('users', UserViewSet)
router.register('groups', GroupViewSet)
router.register('expenses', ExpenseViewSet)

urlpatterns = [path('', include(router.urls))]