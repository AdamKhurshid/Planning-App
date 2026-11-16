"""Recurring tasks, day tasks, occurrence done-marking, and import tests."""
from datetime import timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from projects.models import Project
from .models import Task, TaskOccurrenceDone, TimeBlock


class RecurringTaskTests(APITestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        from rest_framework.authtoken.models import Token
        self.user = get_user_model().objects.create_user(username="owner")
        token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        # Default profile timezone is whatever accounts creates; set UTC for
        # deterministic assertions.
        from accounts.models import Profile
        Profile.objects.update_or_create(user=self.user, defaults={"timezone": "UTC"})

    def _create_recurring(self, **over):
        payload = {
            "title": "Duolingo",
            "estimated_minutes": 15,
            "recurrence_rule": "FREQ=DAILY",
            "preferred_time": "08:30",
        }
        payload.update(over)
        response = self.client.post("/api/tasks/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        return Task.objects.get(id=response.data["id"])

    def test_create_materializes_future_blocks(self):
        task = self._create_recurring()
        blocks = TimeBlock.objects.filter(task=task).order_by("start")
        self.assertGreaterEqual(blocks.count(), 50)  # ~60 days of daily slots
        self.assertTrue(all(b.source == TimeBlock.Source.RECURRING for b in blocks))
        first = blocks.first()
        self.assertEqual(first.start.strftime("%H:%M"), "08:30")
        self.assertEqual(first.minutes, 15)
        self.assertTrue(task.is_scheduled)

    def test_moving_one_occurrence_leaves_the_series_alone(self):
        task = self._create_recurring()
        block = TimeBlock.objects.filter(task=task).order_by("start").first()
        new_start = block.start + timedelta(hours=3)
        response = self.client.patch(
            f"/api/time-blocks/{block.id}/",
            {"start": new_start.isoformat(), "end": (new_start + timedelta(minutes=15)).isoformat()},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        others = TimeBlock.objects.filter(task=task).exclude(pk=block.pk).order_by("start")
        self.assertTrue(all(b.start.strftime("%H:%M") == "08:30" for b in others))
        self.assertEqual(TimeBlock.objects.get(pk=block.pk).start, new_start)

    def test_series_edit_regenerates_future_only(self):
        task = self._create_recurring()
        blocks = list(TimeBlock.objects.filter(task=task).order_by("start"))
        first, second = blocks[0], blocks[1]
        # Move the first occurrence into the past (a past adjustment must
        # survive any later series edit).
        moved_start = timezone.now() - timedelta(hours=2)
        TimeBlock.objects.filter(pk=first.pk).update(start=moved_start, end=moved_start + timedelta(minutes=15))
        # Edit the series: new time + duration.
        response = self.client.patch(
            f"/api/tasks/{task.id}/",
            {"preferred_time": "09:45", "estimated_minutes": 30},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        first = TimeBlock.objects.get(pk=first.pk)
        self.assertEqual(first.start, moved_start)  # past/manual kept
        self.assertLess(first.start, timezone.now())
        # The future was regenerated wholesale: the old future rows are gone.
        self.assertFalse(TimeBlock.objects.filter(pk=second.pk).exists())
        fresh = TimeBlock.objects.filter(task=task, start__gte=timezone.now()).order_by("start")
        self.assertTrue(all(b.start.strftime("%H:%M") == "09:45" for b in fresh))
        self.assertTrue(all(b.minutes == 30 for b in fresh))

    def test_completing_series_clears_future(self):
        task = self._create_recurring()
        self.client.post(f"/api/tasks/{task.id}/complete/", {"completed": True}, format="json")
        self.assertEqual(TimeBlock.objects.filter(task=task, start__gte=timezone.now()).count(), 0)
        # Un-completing brings the series back.
        self.client.post(f"/api/tasks/{task.id}/complete/", {"completed": False}, format="json")
        self.assertGreater(TimeBlock.objects.filter(task=task, start__gte=timezone.now()).count(), 0)

    def test_occurrence_done_toggle(self):
        task = self._create_recurring()
        block = TimeBlock.objects.filter(task=task).order_by("start").first()
        day = block.start.date().isoformat()
        response = self.client.post(f"/api/tasks/{task.id}/occurrence_done/", {"date": day}, format="json")
        self.assertEqual(response.data["done"], True)
        self.assertTrue(TaskOccurrenceDone.objects.filter(task=task, date=day).exists())
        # The calendar reports it.
        cal = self.client.get(f"/api/calendar/?start={day}T00:00:00Z&end={day}T23:59:59Z")
        self.assertTrue(any(b["done_occurrence"] for b in cal.data["blocks"]))
        response = self.client.post(f"/api/tasks/{task.id}/occurrence_done/", {"date": day}, format="json")
        self.assertEqual(response.data["done"], False)
        self.assertFalse(TaskOccurrenceDone.objects.filter(task=task, date=day).exists())

    def test_scheduler_skips_recurring_tasks(self):
        from scheduling.services import create_preview
        project = Project.objects.create(owner=self.user, title="Habits")
        section = None
        task = self._create_recurring()
        task.project = project
        task.save()
        plan = create_preview(self.user, project)
        # No plan blocks may be produced for the recurring task.
        self.assertTrue(all(b["task_id"] != task.id for b in plan.payload["blocks"]))
        del section


class DayTaskTests(APITestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        from rest_framework.authtoken.models import Token
        self.user = get_user_model().objects.create_user(username="owner")
        token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        from accounts.models import Profile
        Profile.objects.update_or_create(user=self.user, defaults={"timezone": "UTC"})

    def test_day_task_appears_on_calendar(self):
        day = timezone.now().date().isoformat()
        response = self.client.post("/api/tasks/", {"title": "Text parents", "estimated_minutes": 10,
                                                    "scheduled_date": day}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["scheduled_date"], day)
        cal = self.client.get(f"/api/calendar/?start={day}T00:00:00Z&end={day}T23:59:59Z")
        self.assertEqual(len(cal.data["day_tasks"]), 1)
        self.assertEqual(cal.data["day_tasks"][0]["title"], "Text parents")
        self.assertFalse(cal.data["day_tasks"][0]["completed"])
        self.assertEqual(cal.data["blocks"], [])

    def test_completing_day_task_reflects_on_calendar(self):
        day = timezone.now().date().isoformat()
        created = self.client.post("/api/tasks/", {"title": "Call bank", "scheduled_date": day}, format="json")
        task_id = created.data["id"]
        self.client.post(f"/api/tasks/{task_id}/complete/", {}, format="json")
        cal = self.client.get(f"/api/calendar/?start={day}T00:00:00Z&end={day}T23:59:59Z")
        self.assertTrue(cal.data["day_tasks"][0]["completed"])


class ImportTests(APITestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        from rest_framework.authtoken.models import Token
        from accounts.models import Profile
        self.user = get_user_model().objects.create_user(username="owner")
        token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        Profile.objects.update_or_create(user=self.user, defaults={"timezone": "UTC"})

    def test_import_json(self):
        content = """
        {
          "projects": [
            {"title": "Thesis", "tasks": [
              {"title": "Outline chapter 1", "estimated_minutes": 45, "priority": "high"},
              {"title": "Read papers", "estimated_minutes": 90}
            ]}
          ],
          "tasks": [
            {"title": "Duolingo", "recurrence_rule": "FREQ=DAILY", "preferred_time": "08:00",
             "estimated_minutes": 15},
            {"title": "Text parents", "scheduled_date": "2026-11-20"}
          ]
        }
        """
        response = self.client.post("/api/import/", {"format": "json", "content": content}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["projects_created"], 1)
        self.assertEqual(response.data["tasks_created"], 4)
        duolingo = Task.objects.get(title="Duolingo")
        self.assertGreater(TimeBlock.objects.filter(task=duolingo).count(), 30)
        self.assertEqual(Task.objects.get(title="Text parents").scheduled_date.isoformat(), "2026-11-20")
        outline = Task.objects.get(title="Outline chapter 1")
        self.assertEqual(outline.project.title, "Thesis")
        self.assertEqual(outline.priority, "high")

    def test_import_text(self):
        content = (
            "# Learn CUDA\n"
            "- Install toolkit 30m !high\n"
            "- Run first kernel 1h30m @2026-12-01\n"
            "- Duolingo daily@08:30 15m\n"
            "- Text parents day:2026-11-21\n"
        )
        response = self.client.post("/api/import/", {"format": "text", "content": content}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["projects_created"], 1)
        self.assertEqual(response.data["tasks_created"], 4)
        kernel = Task.objects.get(title="Run first kernel")
        self.assertEqual(kernel.estimated_minutes, 90)
        self.assertIsNotNone(kernel.deadline)
        self.assertEqual(Task.objects.get(title="Install toolkit").priority, "high")
        duolingo = Task.objects.get(title="Duolingo")
        self.assertEqual(duolingo.recurrence_rule, "FREQ=DAILY")
        self.assertEqual(duolingo.preferred_time, "08:30")
        self.assertGreater(TimeBlock.objects.filter(task=duolingo).count(), 30)
        self.assertEqual(Task.objects.get(title="Text parents").scheduled_date.isoformat(), "2026-11-21")
        self.assertEqual(Task.objects.get(title="Install toolkit").project.title, "Learn CUDA")

    def test_import_reimports_match_projects_by_title(self):
        first = self.client.post("/api/import/", {"format": "text", "content": "# Habits\n- Meditate 10m\n"}, format="json")
        self.assertEqual(first.data["projects_created"], 1)
        second = self.client.post("/api/import/", {"format": "text", "content": "# habits\n- Journal 10m\n"}, format="json")
        self.assertEqual(second.data["projects_created"], 0)
        self.assertEqual(Project.objects.filter(owner=self.user).count(), 1)
        self.assertEqual(Project.objects.get().tasks.count(), 2)

    def test_import_bad_json_400(self):
        response = self.client.post("/api/import/", {"format": "json", "content": "{nope"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_import_bad_rrule_imported_without_recurrence(self):
        response = self.client.post(
            "/api/import/",
            {"format": "json", "content": '[{"title":"Weird","recurrence_rule":"FREQ=NOPE","preferred_time":"08:00"}]'},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        task = Task.objects.get(title="Weird")
        self.assertEqual(task.recurrence_rule, "")
        self.assertEqual(TimeBlock.objects.filter(task=task).count(), 0)
