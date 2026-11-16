"""Tests for export (JSON + ICS), global search, the notification centre,
recurring-occurrence overrides and the scheduled_minutes annotation."""
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from projects.models import Project, Section
from .models import Event, RecurrenceOverride, Task, TimeBlock

User = get_user_model()


class BaseAPITestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="owner")
        token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def make_event(self, title="Sync", offset_hours=1, **kw):
        start = timezone.now() + timedelta(hours=offset_hours)
        return Event.objects.create(
            owner=self.user, title=title, start=start, end=start + timedelta(hours=1), **kw)

    def make_task(self, title="Task", **kw):
        return Task.objects.create(owner=self.user, title=title, **kw)


class ExportTests(BaseAPITestCase):
    def test_json_contains_every_collection(self):
        self.make_event()
        project = Project.objects.create(owner=self.user, title="Thesis", color="#3366ff")
        section = Section.objects.create(owner=self.user, project=project, title="Writing")
        task = self.make_task(title="Draft intro", project=project, section=section)
        TimeBlock.objects.create(owner=self.user, task=task,
                                 start=timezone.now(), end=timezone.now() + timedelta(minutes=30))
        response = self.client.get("/api/export/", {"type": "json"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = json.loads(response.content)
        self.assertEqual(data["app"], "tempo")
        self.assertEqual(len(data["events"]), 1)
        self.assertEqual(len(data["projects"]), 1)
        self.assertEqual(len(data["sections"]), 1)
        self.assertEqual(len(data["tasks"]), 1)
        self.assertEqual(data["tasks"][0]["scheduled_minutes"], 30)

    def test_ics_has_events_blocks_and_todos(self):
        day = timezone.now() + timedelta(days=2)
        day = day.replace(minute=0, second=0, microsecond=0)
        event = Event.objects.create(owner=self.user, title="Review, #2; \"final\"", start=day,
                                     end=day + timedelta(hours=1), location="Office", description="Line1\nLine2")
        project = Project.objects.create(owner=self.user, title="Thesis")
        task = Task.objects.create(owner=self.user, title="Draft intro", project=project,
                                   deadline=day + timedelta(days=1), priority="high")
        TimeBlock.objects.create(owner=self.user, task=task, start=day + timedelta(hours=2),
                                 end=day + timedelta(hours=3))

        response = self.client.get("/api/export/", {"type": "ics"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"].split(";")[0], "text/calendar")
        text = response.content.decode()
        self.assertIn("BEGIN:VCALENDAR", text)
        self.assertIn("BEGIN:VEVENT", text)
        self.assertIn("BEGIN:VTODO", text)
        self.assertIn(r'SUMMARY:Review\, #2\; "final"', text)  # RFC 5545: escape only \ ; , and newlines
        self.assertIn(r"DESCRIPTION:Line1\nLine2", text)
        self.assertIn("SUMMARY:Work: Draft intro", text)
        self.assertIn("STATUS:NEEDS-ACTION", text)
        self.assertIn("PRIORITY:4", text)  # high -> 4 (1 = most urgent)
        self.assertIn(f"UID:tempo-e{event.id}-{day.date().isoformat()}@tempo.local", text)
        self.assertIn(f"UID:tempo-t{task.id}@tempo.local", text)
        # CRLF line endings per RFC 5545, no line longer than 75 octets.
        for line in text.split("\r\n"):
            self.assertLessEqual(len(line.encode()), 75)

    def test_ics_expands_recurring_with_overrides(self):
        from datetime import datetime, timezone as dt_timezone
        day = datetime(2026, 3, 2, 9, 0, tzinfo=dt_timezone.utc)  # a Monday
        event = Event.objects.create(owner=self.user, title="Standup", start=day,
                                     end=day + timedelta(minutes=15), recurrence_rule="FREQ=WEEKLY;BYDAY=MO")
        RecurrenceOverride.objects.create(owner=self.user, event=event, original_date=day.date(), is_cancelled=True)
        response = self.client.get("/api/export/", {"type": "ics", "start": day.isoformat(),
                                                    "end": (day + timedelta(days=8)).isoformat()})
        text = response.content.decode()
        self.assertNotIn("2026-03-02@tempo.local", text)  # cancelled occurrence gone
        self.assertIn("2026-03-09@tempo.local", text)     # next Monday present

    def test_ics_range_validation(self):
        response = self.client.get("/api/export/", {"type": "ics", "start": timezone.now().isoformat()})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response = self.client.get("/api/export/", {"type": "xlsx"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


import json  # noqa: E402  (used by ExportTests; placed after imports block for brevity)


class SearchTests(BaseAPITestCase):
    def test_empty_query_returns_empty_groups(self):
        response = self.client.get("/api/search/")
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        self.assertEqual(response.data["tasks"], [])

    def test_matches_across_kinds(self):
        self.make_event(title="Quarterly review")
        self.make_task(title="Write review notes")
        Project.objects.create(owner=self.user, title="Annual review project")
        response = self.client.get("/api/search/", {"q": "review"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["events"]), 1)
        self.assertEqual(len(response.data["tasks"]), 1)
        self.assertEqual(len(response.data["projects"]), 1)

    def test_results_scoped_to_owner(self):
        other = User.objects.create_user(username="intruder")
        Event.objects.create(owner=other, title="Secret party",
                             start=timezone.now(), end=timezone.now() + timedelta(hours=1))
        response = self.client.get("/api/search/", {"q": "Secret"})
        self.assertEqual(response.data["events"], [])


class NotificationTests(BaseAPITestCase):
    def test_overdue_and_upcoming_deadlines(self):
        self.make_task(title="Overdue", deadline=timezone.now() - timedelta(days=1))
        self.make_task(title="Soon", deadline=timezone.now() + timedelta(days=2))
        response = self.client.get("/api/notifications/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        pairs = {(i["title"], i["kind"]) for i in response.data["items"]}
        # An overdue unscheduled task shows up as overdue AND as a nudge.
        self.assertIn(("Overdue", "overdue"), pairs)
        self.assertIn(("Soon", "deadline"), pairs)

    def test_event_starting_soon(self):
        soon = timezone.now() + timedelta(minutes=30)
        Event.objects.create(owner=self.user, title="Sync", start=soon, end=soon + timedelta(minutes=30))
        response = self.client.get("/api/notifications/")
        detail = next(i for i in response.data["items"] if i["title"] == "Sync")
        self.assertEqual(detail["kind"], "event")
        self.assertIn("min", detail["detail"])

    def test_completed_tasks_not_listed(self):
        task = self.make_task(title="Done thing", deadline=timezone.now() - timedelta(days=1))
        task.completed_at = timezone.now()
        task.save(update_fields=["completed_at"])
        response = self.client.get("/api/notifications/")
        self.assertEqual(response.data["items"], [])

    def test_unscheduled_nudge(self):
        self.make_task(title="Needs scheduling", deadline=timezone.now() + timedelta(days=3))
        response = self.client.get("/api/notifications/")
        kinds = [i["kind"] for i in response.data["items"]]
        self.assertIn("unscheduled", kinds)

    def test_severity_sorting(self):
        self.make_task(title="Overdue", deadline=timezone.now() - timedelta(days=1))
        self.make_task(title="Soon", deadline=timezone.now() + timedelta(days=2))
        response = self.client.get("/api/notifications/")
        severities = [i["severity"] for i in response.data["items"]]
        self.assertEqual(severities, sorted(severities, key=lambda s: {"high": 0, "medium": 1, "low": 2}[s]))


class RecurrenceOverrideTests(BaseAPITestCase):
    def test_override_requires_recurring_event(self):
        event = self.make_event()
        response = self.client.post(f"/api/events/{event.id}/override/",
                                    {"original_date": event.start.date().isoformat(),
                                     "is_cancelled": True}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cancel_one_occurrence(self):
        from datetime import datetime, timezone as dt_timezone
        start = datetime(2026, 4, 6, 9, 0, tzinfo=dt_timezone.utc)
        event = Event.objects.create(owner=self.user, title="Standup", start=start,
                                     end=start + timedelta(minutes=15), recurrence_rule="FREQ=WEEKLY;BYDAY=MO")
        response = self.client.post(f"/api/events/{event.id}/override/",
                                    {"original_date": "2026-04-13", "is_cancelled": True}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(RecurrenceOverride.objects.get(event=event).is_cancelled)

        # The calendar range endpoint must now skip that occurrence.
        response = self.client.get("/api/calendar/", {"start": start.isoformat(),
                                                      "end": (start + timedelta(days=10)).isoformat()})
        dates = {e["original_date"] for e in response.json()["events"]}
        self.assertNotIn("2026-04-13", dates)
        self.assertIn("2026-04-06", dates)

    def test_move_one_occurrence(self):
        from datetime import datetime, timezone as dt_timezone
        start = datetime(2026, 4, 6, 9, 0, tzinfo=dt_timezone.utc)
        event = Event.objects.create(owner=self.user, title="1:1", start=start,
                                     end=start + timedelta(minutes=30), recurrence_rule="FREQ=WEEKLY;BYDAY=MO")
        new_start = datetime(2026, 4, 7, 15, 0, tzinfo=dt_timezone.utc)
        response = self.client.post(f"/api/events/{event.id}/override/",
                                    {"original_date": "2026-04-06",
                                     "patch": {"start": new_start.isoformat(), "title": "1:1 (moved)"}}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response = self.client.get("/api/calendar/", {"start": start.isoformat(),
                                                      "end": (start + timedelta(days=3)).isoformat()})
        titles = [(e["original_date"], e["title"]) for e in response.json()["events"]]
        self.assertIn(("2026-04-06", "1:1 (moved)"), titles)

    def test_reset_clears_override(self):
        from datetime import datetime, timezone as dt_timezone
        start = datetime(2026, 4, 6, 9, 0, tzinfo=dt_timezone.utc)
        event = Event.objects.create(owner=self.user, title="Standup", start=start,
                                     end=start + timedelta(minutes=15), recurrence_rule="FREQ=WEEKLY;BYDAY=MO")
        self.client.post(f"/api/events/{event.id}/override/",
                         {"original_date": "2026-04-13", "is_cancelled": True}, format="json")
        response = self.client.post(f"/api/events/{event.id}/override/",
                                    {"original_date": "2026-04-13", "reset": True}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(RecurrenceOverride.objects.filter(event=event).exists())

    def test_patch_rejects_unknown_fields(self):
        event = Event.objects.create(owner=self.user, title="R", start=timezone.now(),
                                     end=timezone.now() + timedelta(hours=1), recurrence_rule="FREQ=DAILY")
        response = self.client.post(f"/api/events/{event.id}/override/",
                                    {"original_date": "2026-01-01", "patch": {"owner": 2}}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class ScheduledMinutesTests(BaseAPITestCase):
    def test_list_reports_scheduled_minutes(self):
        task = self.make_task(title="Worked", estimated_minutes=120)
        TimeBlock.objects.create(owner=self.user, task=task,
                                 start=timezone.now(), end=timezone.now() + timedelta(minutes=45))
        TimeBlock.objects.create(owner=self.user, task=task,
                                 start=timezone.now() + timedelta(hours=2), end=timezone.now() + timedelta(hours=3))
        response = self.client.get("/api/tasks/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data[0]["scheduled_minutes"], 105)
        # Multiple blocks must not duplicate the row.
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["is_scheduled"], True)
