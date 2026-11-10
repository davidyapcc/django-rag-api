from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import AskView, QueryViewSet

router = DefaultRouter()
router.register("queries", QueryViewSet, basename="query")

urlpatterns = [path("ask/", AskView.as_view(), name="ask"), *router.urls]
