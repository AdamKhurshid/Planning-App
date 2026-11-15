"""Auth, permissions and preferences tests."""
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.test import override_settings
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

User = get_user_model()

TEST_HASH = make_password("correct horse battery staple")

# Every private endpoint must reject unauthenticated access.
PRIVATE_ENDPOINTS = [
    "/api/events/",
    "/api/tasks/",
    "/api/time-blocks/",
    "/api/projects/",
    "/api/sections/",
    "/api/dashboard/today/",
    "/api/preferences/",
    "/api/auth/me/",
    "/api/scheduling/plans/",
]


@override_settings(TEMPO_PASSWORD_HASH=TEST_HASH)
class LoginTests(APITestCase):
    def test_login_success_returns_token_and_creates_user_profile(self):
        response = self.client.post("/api/auth/login/", {"password": "correct horse battery staple"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("token", response.data)
        user = User.objects.get(username="owner")
        self.assertTrue(user.profile is not None)
        # The user's own password field stays unusable — the real hash lives
        # in the environment, not in the database.
        self.assertFalse(user.has_usable_password())

    def test_login_wrong_password_rejected(self):
        response = self.client.post("/api/auth/login/", {"password": "wrong"})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_empty_password_rejected(self):
        response = self.client.post("/api/auth/login/", {"password": ""})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_without_configured_hash_is_forbidden(self):
        with override_settings(TEMPO_PASSWORD_HASH=""):
            response = self.client.post("/api/auth/login/", {"password": "anything"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_logout_invalidates_token(self):
        token = self.client.post("/api/auth/login/", {"password": "correct horse battery staple"}).data["token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        self.assertEqual(self.client.post("/api/auth/logout/").status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(self.client.get("/api/auth/me/").status_code, status.HTTP_401_UNAUTHORIZED)


class PermissionWallTests(APITestCase):
    """All API endpoints require authentication."""

    def test_unauthenticated_access_is_rejected(self):
        for url in PRIVATE_ENDPOINTS:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED, url)

    def test_bogus_token_rejected(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token not-a-real-token")
        self.assertEqual(self.client.get("/api/events/").status_code, status.HTTP_401_UNAUTHORIZED)


@override_settings(TEMPO_PASSWORD_HASH=TEST_HASH)
class PreferencesTests(APITestCase):
    def setUp(self):
        token = self.client.post("/api/auth/login/", {"password": "correct horse battery staple"}).data["token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")

    def test_me_returns_user_and_profile(self):
        response = self.client.get("/api/auth/me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["user"]["username"], "owner")
        self.assertEqual(response.data["profile"]["timezone"], "UTC")

    def test_update_working_hours(self):
        response = self.client.patch(
            "/api/preferences/",
            {"work_start": "08:00", "work_end": "16:00", "max_work_minutes_per_day": 300},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["work_start"], "08:00:00")
        self.assertEqual(response.data["max_work_minutes_per_day"], 300)

    def test_work_start_before_end_enforced(self):
        response = self.client.patch("/api/preferences/", {"work_start": "18:00", "work_end": "09:00"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_working_days_validated(self):
        response = self.client.patch("/api/preferences/", {"working_days": [0, 9]}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_prayer_location_needs_both_coordinates(self):
        response = self.client.patch("/api/preferences/", {"latitude": 51.5}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response = self.client.patch("/api/preferences/", {"latitude": 51.5, "longitude": -0.12}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
