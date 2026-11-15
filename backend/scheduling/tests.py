"""Phase 1 smoke tests for SchedulePlan (algorithm tests arrive in Phase 4)."""
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from projects.models import Project

from .models import SchedulePlan

User = get_user_model()


class SchedulePlanHistoryTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="owner")
        token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def test_plan_history_is_readable_and_scoped(self):
        other = User.objects.create_user(username="other")
        project = Project.objects.create(owner=self.user, title="P")
        SchedulePlan.objects.create(owner=self.user, project=project, payload={"items": []})
        SchedulePlan.objects.create(owner=other, payload={"items": []})
        response = self.client.get("/api/scheduling/plans/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
