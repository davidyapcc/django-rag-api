from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import DocumentViewSet, ingest_callback, ingest_failure_callback

router = DefaultRouter()
router.register("documents", DocumentViewSet, basename="document")
urlpatterns = [
    *router.urls,
    path("tasks/ingest/", ingest_callback, name="ingest-callback"),
    path("tasks/ingest/failed/", ingest_failure_callback, name="ingest-failure-callback"),
]
