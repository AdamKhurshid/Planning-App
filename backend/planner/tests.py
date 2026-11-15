"""Calendar entry tests: events, tasks, time blocks, dashboard."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from projects.models import Project, Section
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from .models import Event, Task, TimeBlock

User = get_user_model()


class BaseAPITestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="owner")
        token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")


class EventTests(BaseAPITestCase):
    def test_create_event(self):
        start = timezone.now()
        response = self.client.post(
            "/api/events/",
            {"title": "Dentist", "start": start.isoformat(), "end": (start + timedelta(hours=1)).isoformat(),
             "location": "Clinic", "category": "health"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["is_fixed"])  # events are fixed by default
        self.assertEqual(Event.objects.get().owner, self.user)

    def test_end_must_be_after_start(self):
        start = timezone.now()
        response = self.client.post(
            "/api/events/",
            {"title": "Backwards", "start": start.isoformat(), "end": start.isoformat()},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_date_range_filter(self):
        now = timezone.now()
        Event.objects.create(owner=self.user, title="in-range", start=now, end=now + timedelta(hours=1))
        Event.objects.create(owner=self.user, title="far-future", start=now + timedelta(days=30),
                             end=now + timedelta(days=30, hours=1))
        response = self.client.get("/api/events/", {
            "date_from": now.isoformat(),
            "date_to": (now + timedelta(days=1)).isoformat(),
        })
        titles = [e["title"] for e in response.data]
        self.assertIn("in-range", titles)
        self.assertNotIn("far-future", titles)

    def test_search_filter(self):
        now = timezone.now()
        Event.objects.create(owner=self.user, title="Standup meeting", start=now, end=now + timedelta(minutes=15))
        response = self.client.get("/api/events/", {"search": "standup"})
        self.assertEqual(len(response.data), 1)

    def test_soft_delete_and_restore(self):
        now = timezone.now()
        event = Event.objects.create(owner=self.user, title="tmp", start=now, end=now + timedelta(hours=1))
        self.assertEqual(self.client.delete(f"/api/events/{event.id}/").status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(self.client.get("/api/events/").data, [])
        self.assertTrue(Event.all_objects.get(pk=event.id).deleted_at)  # row still exists
        self.assertEqual(self.client.post(f"/api/events/{event.id}/restore/").status_code, status.HTTP_200_OK)
        self.assertEqual(len(self.client.get("/api/events/").data), 1)


class TaskTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.project = Project.objects.create(owner=self.user, title="Learn CUDA", deadline=timezone.now() + timedelta(days=10))
        self.section = Section.objects.create(owner=self.user, project=self.project, title="C Programming", position=0)
        self.section2 = Section.objects.create(owner=self.user, project=self.project, title="GPU Architecture", position=1)

    def _create_task(self, **overrides):
        payload = {
            "title": "Understand pointer fundamentals",
            "estimated_minutes": 60,
            "section": self.section.id,
            **overrides,
        }
        return self.client.post("/api/tasks/", payload, format="json")

    def test_create_task_in_section_sets_project(self):
        response = self._create_task()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["project"], self.project.id)
        self.assertEqual(response.data["section_title"], "C Programming")

    def test_section_project_mismatch_rejected(self):
        other_project = Project.objects.create(owner=self.user, title="Other")
        response = self._create_task(project=other_project.id)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_estimated_minutes_must_be_positive(self):
        response = self._create_task(estimated_minutes=0)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_complete_toggle(self):
        task_id = self._create_task().data["id"]
        # No argument -> toggles (task starts incomplete, so it completes):
        self.assertTrue(self.client.post(f"/api/tasks/{task_id}/complete/").data["is_completed"])
        # Explicit false clears:
        self.assertFalse(
            self.client.post(f"/api/tasks/{task_id}/complete/", {"completed": False}, format="json").data["is_completed"]
        )

    def test_move_between_sections(self):
        task_id = self._create_task().data["id"]
        response = self.client.post(f"/api/tasks/{task_id}/move/", {"section_id": self.section2.id}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["section"], self.section2.id)
        self.assertEqual(response.data["section_title"], "GPU Architecture")

    def test_move_to_other_users_section_rejected(self):
        other_user = User.objects.create_user(username="other")
        foreign = Section.objects.create(owner=other_user, project=Project.objects.create(owner=other_user, title="x"), title="their section")
        task_id = self._create_task().data["id"]
        response = self.client.post(f"/api/tasks/{task_id}/move/", {"section_id": foreign.id}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reorder_bulk(self):
        a = self._create_task(title="A", position=0).data
        b = self._create_task(title="B", position=1).data
        response = self.client.post("/api/tasks/reorder/", {"items": [
            {"id": b["id"], "position": 0},
            {"id": a["id"], "position": 1},
        ]}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Task.objects.get(pk=b["id"]).position, 0)

    def test_unscheduled_filter(self):
        task_id = self._create_task().data["id"]
        self.assertEqual(len(self.client.get("/api/tasks/", {"unscheduled": "true"}).data), 1)
        start = timezone.now()
        TimeBlock.objects.create(owner=self.user, task_id=task_id, start=start, end=start + timedelta(hours=1))
        self.assertEqual(len(self.client.get("/api/tasks/", {"unscheduled": "true"}).data), 0)

    def test_self_dependency_rejected(self):
        task_id = self._create_task().data["id"]
        response = self.client.patch(f"/api/tasks/{task_id}/", {"depends_on": [task_id]}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_ownership_scoping(self):
        other_user = User.objects.create_user(username="someone-else")
        Task.objects.create(owner=other_user, title="their task")
        titles = [t["title"] for t in self.client.get("/api/tasks/").data]
        self.assertNotIn("their task", titles)


class TimeBlockTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.task = Task.objects.create(owner=self.user, title="Practice malloc and free")

    def _block(self, task, start, hours=1):
        return self.client.post("/api/time-blocks/", {
            "task": task.id, "start": start.isoformat(),
            "end": (start + timedelta(hours=hours)).isoformat(),
        }, format="json")

    def test_create_block(self):
        response = self._block(self.task, timezone.now())
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["task_title"], "Practice malloc and free")

    def test_same_task_overlap_rejected(self):
        start = timezone.now()
        self.assertEqual(self._block(self.task, start).status_code, status.HTTP_201_CREATED)
        response = self._block(self.task, start + timedelta(minutes=30))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_different_tasks_may_overlap(self):
        start = timezone.now()
        other = Task.objects.create(owner=self.user, title="Review flashcards")
        self.assertEqual(self._block(self.task, start).status_code, status.HTTP_201_CREATED)
        self.assertEqual(self._block(other, start + timedelta(minutes=30)).status_code, status.HTTP_201_CREATED)

    def test_end_after_start(self):
        start = timezone.now()
        response = self.client.post("/api/time-blocks/", {
            "task": self.task.id, "start": start.isoformat(), "end": start.isoformat(),
        }, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class DashboardTests(BaseAPITestCase):
    def test_today_overview(self):
        now = timezone.now()
        project = Project.objects.create(
            owner=self.user, title="Learn CUDA", color="#8B5CF6",
            deadline=now + timedelta(days=10),
        )
        task_done = Task.objects.create(owner=self.user, project=project, title="done thing",
                                        estimated_minutes=60, completed_at=now)
        task_open = Task.objects.create(owner=self.user, project=project, title="open thing",
                                        estimated_minutes=60, deadline=now - timedelta(hours=2))  # overdue
        Event.objects.create(owner=self.user, title="Meeting", start=now + timedelta(hours=1),
                             end=now + timedelta(hours=2))
        TimeBlock.objects.create(owner=self.user, task=task_open, start=now + timedelta(hours=3),
                                 end=now + timedelta(hours=4))
        TimeBlock.objects.create(owner=self.user, task=task_done, start=now - timedelta(hours=2),
                                 end=now - timedelta(hours=1))

        response = self.client.get("/api/dashboard/today/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["events"]), 1)
        self.assertEqual(len(response.data["time_blocks"]), 2)
        self.assertEqual(response.data["work_today"]["scheduled_minutes"], 60)
        self.assertEqual(response.data["work_today"]["completed_minutes"], 60)
        self.assertEqual([t["title"] for t in response.data["overdue_tasks"]], ["open thing"])
        self.assertEqual(response.data["projects"][0]["title"], "Learn CUDA")
        self.assertEqual(response.data["projects"][0]["completion_percent"], 50.0)
        self.assertEqual(response.data["unscheduled_count"], 0)
