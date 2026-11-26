from django.urls import path

from .views import health, live

urlpatterns = [
    path("health/", health, name="health"),
    path("health/live/", live, name="health-live"),
]
