"""URLconf for the accounts API (mounted under ``/api/``)."""

from django.urls import path

from accounts.views import LoginView, MeView, RefreshView

app_name = "accounts"

urlpatterns = [
    path("auth/login/", LoginView.as_view(), name="login"),
    path("auth/refresh/", RefreshView.as_view(), name="refresh"),
    path("me/", MeView.as_view(), name="me"),
]
