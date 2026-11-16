"""Auth routes live under /api/auth/; preferences is mounted at its own
top-level path /api/preferences/ (see config/urls.py)."""
from django.urls import path

from .views import LoginView, LogoutView, MeView, PreferencesView

auth_patterns = [
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("me/", MeView.as_view(), name="me"),
]

preferences_patterns = [
    path("preferences/", PreferencesView.as_view(), name="preferences"),
]

urlpatterns = auth_patterns + preferences_patterns
