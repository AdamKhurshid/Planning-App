"""Project stats math and section management tests."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from planner.models import Task, TimeBlock
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from .models import Project, Section

User = get_user_model()


class StatsTests(APITestCase):
    """The progress math must be exact — it drives the whole UI."""

    def setUp(self):
        self.user = User.objects.create_user(username="owner")
        token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        now = timezone.now()

        self.project = Project.objects.create(owner=self.user, title="Learn CUDA", color="#8B5CF6",
                                              deadline=now + timedelta(days=10))
        self.s1 = Section.objects.create(owner=self.user, project=self.project, title="C Programming", position=0)
        self.s2 = Section.objects.create(owner=self.user, project=self.project, title="GPU Architecture", position=1)

        # Section 1: 60 min done + 60 min open. Section 2: 30 done + 90 open.
        Task.objects.create(owner=self.user, project=self.project, section=self.s1,
                            title="t1", estimated_minutes=60, completed_at=now)
        Task.objects.create(owner=self.user, project=self.project, section=self.s1,
                            title="t2", estimated_minutes=60)
        Task.objects.create(owner=self.user, project=self.project, section=self.s2,
                            title="t3", estimated_minutes=30, completed_at=now)
        Task.objects.create(owner=self.user, project=self.project, section=self.s2,
                            title="t4", estimated_minutes=90)

    def test_project_summary_math(self):
        response = self.client.get(f"/api/projects/{self.project.id}/summary/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        self.assertEqual(data["tasks_total"], 4)
        self.assertEqual(data["tasks_completed"], 2)
        self.assertEqual(data["tasks_remaining"], 2)
        self.assertEqual(data["minutes_total"], 240)
        self.assertEqual(data["minutes_completed"], 90)
        self.assertEqual(data["minutes_remaining"], 150)
        self.assertEqual(data["hours_total"], 4.0)
        self.assertEqual(data["hours_completed"], 1.5)
        self.assertEqual(data["hours_remaining"], 2.5)
        self.assertEqual(data["completion_percent"], 37.5)  # by minutes
        self.assertEqual(data["completion_percent_by_tasks"], 50.0)
        self.assertFalse(data["is_overdue"])

    def test_section_progress_math(self):
        response = self.client.get(f"/api/projects/{self.project.id}/summary/")
        sections = {s["title"]: s for s in response.data["sections"]}
        self.assertEqual(sections["C Programming"]["completion_percent"], 50.0)
        self.assertEqual(sections["C Programming"]["minutes_remaining"], 60)
        self.assertEqual(sections["GPU Architecture"]["completion_percent"], 25.0)
        self.assertEqual(sections["GPU Architecture"]["minutes_remaining"], 90)

    def test_pace_and_overdue(self):
        # 150 min remaining over ~10 days -> 0.25 h/day needed.
        response = self.client.get(f"/api/projects/{self.project.id}/summary/")
        self.assertEqual(response.data["hours_per_day_needed"], 0.25)

        self.project.deadline = timezone.now() - timedelta(days=1)
        self.project.save()
        response = self.client.get(f"/api/projects/{self.project.id}/summary/")
        self.assertTrue(response.data["is_overdue"])

    def test_upcoming_blocks_and_unscheduled_tasks(self):
        now = timezone.now()
        t2 = Task.objects.get(title="t2")
        t4 = Task.objects.get(title="t4")
        TimeBlock.objects.create(owner=self.user, task=t2, start=now + timedelta(days=1),
                                 end=now + timedelta(days=1, hours=1))
        response = self.client.get(f"/api/projects/{self.project.id}/summary/")
        self.assertEqual(len(response.data["upcoming_blocks"]), 1)
        self.assertEqual(len(response.data["unscheduled_tasks"]), 1)
        self.assertEqual(response.data["unscheduled_tasks"][0]["title"], "t4")

    def test_compact_stats_in_list(self):
        response = self.client.get("/api/projects/")
        item = response.data[0]
        self.assertEqual(item["completion_percent"], 37.5)
        self.assertEqual(item["tasks_completed"], 2)


class SectionTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="owner")
        token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        self.project = Project.objects.create(owner=self.user, title="P")

    def _section(self, title, **kwargs):
        return Section.objects.create(owner=self.user, project=self.project, title=title, **kwargs)

    def test_create_appends_position(self):
        response = self.client.post("/api/sections/", {"project": self.project.id, "title": "First"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["position"], 0)
        response = self.client.post("/api/sections/", {"project": self.project.id, "title": "Second"}, format="json")
        self.assertEqual(response.data["position"], 1)

    def test_reorder(self):
        a, b, c = self._section("A", position=0), self._section("B", position=1), self._section("C", position=2)
        response = self.client.post("/api/sections/reorder/", {"ordered_ids": [c.id, a.id, b.id]}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Section.objects.get(pk=c.id).position, 0)
        self.assertEqual(Section.objects.get(pk=a.id).position, 1)
        self.assertEqual(Section.objects.get(pk=b.id).position, 2)

    def test_project_cascade_delete_is_recoverable(self):
        self._section("A")
        Task.objects.create(owner=self.user, project=self.project, title="task")
        self.assertEqual(self.client.delete(f"/api/projects/{self.project.id}/").status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(self.client.get("/api/tasks/").data, [])  # tasks hidden
        self.assertEqual(self.client.post(f"/api/projects/{self.project.id}/restore/").status_code, status.HTTP_200_OK)
        self.assertEqual(len(self.client.get("/api/tasks/").data), 1)  # and back

    def test_projects_are_scoped_to_owner(self):
        other = User.objects.create_user(username="intruder")
        Project.objects.create(owner=other, title="secret")
        titles = [p["title"] for p in self.client.get("/api/projects/").data]
        self.assertIn("P", titles)  # own project is visible
        self.assertNotIn("secret", titles)  # someone else's is not
