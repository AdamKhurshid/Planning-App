"""Auth views for the private single-user login.

The password check compares against TEMPO_PASSWORD_HASH (a Django-format
hash from the environment / .env file). The plaintext password is never
stored anywhere; the User row itself has an unusable password.
"""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework.authtoken.models import Token
from rest_framework.generics import RetrieveUpdateAPIView

from .models import Profile
from .serializers import ProfileSerializer, UserSerializer

User = get_user_model()


class LoginView(APIView):
    """POST /api/auth/login/ {password, username?} -> {token, user}."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        password = str(request.data.get("password", ""))
        username = str(request.data.get("username") or settings.TEMPO_USERNAME)

        if not settings.TEMPO_PASSWORD_HASH:
            return Response(
                {"detail": "No password configured on the server. Set TEMPO_PASSWORD_HASH "
                           "(generate one with: python manage.py hash_password)."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if not password or not check_password(password, settings.TEMPO_PASSWORD_HASH):
            return Response({"detail": "Incorrect password."}, status=status.HTTP_401_UNAUTHORIZED)

        user, created = User.objects.get_or_create(
            username=username,
            defaults={"is_staff": True, "is_superuser": True},
        )
        if created:
            # The real password hash lives in TEMPO_PASSWORD_HASH (env only).
            user.set_unusable_password()
            user.save(update_fields=["password"])
        Profile.objects.get_or_create(user=user)
        token, _ = Token.objects.get_or_create(user=user)
        return Response({"token": token.key, "user": UserSerializer(user).data})


class LogoutView(APIView):
    """POST /api/auth/logout/ — invalidates the current token."""

    def post(self, request):
        Token.objects.filter(user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    """GET /api/auth/me/ — user + profile in one call (used at app boot)."""

    def get(self, request):
        profile, _ = Profile.objects.get_or_create(user=request.user)
        return Response({"user": UserSerializer(request.user).data, "profile": ProfileSerializer(profile).data})


class PreferencesView(RetrieveUpdateAPIView):
    """GET/PATCH /api/preferences/ — availability, prayer and holiday settings."""

    serializer_class = ProfileSerializer

    def get_object(self):
        profile, _ = Profile.objects.get_or_create(user=self.request.user)
        return profile
