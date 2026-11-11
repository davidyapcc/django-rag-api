from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "web"

urlpatterns = [
    path("", views.landing, name="landing"),
    path("guest/", views.start_guest, name="guest"),
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("signup/", views.signup, name="signup"),
    path("app/", views.app, name="app"),
    path("app/documents/upload/", views.upload, name="upload"),
    path("app/documents/samples/", views.samples, name="samples"),
    path("app/documents/<int:pk>/delete/", views.delete_document, name="delete-document"),
    path("app/ask/", views.ask_view, name="ask"),
    path("app/history/", views.history, name="history"),
]
