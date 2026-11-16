"""Repeating whole-day tasks (all-day recurring): calendar expansion with
per-date done flags, plus the unscheduled filters ignoring them."""
from datetime import date, timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from .models import Task, TaskOccurrenceDone
from .recurring_tasks import materialize_recurring_task
from .test_extras import BaseAPITestCase


class DayRecurringExpansionTests(BaseAPITestCase):
    def _anchor(self, days_ahead=1):
        return timezone.localdate() + timedelta(days=days_ahead)

    def test_calendar_expands_one_row_per_occurrence(self):
        anchor = self._anchor(0)  # today: keeps the arithmetic obvious
        task = self.make_task(title="Read Qur'an", scheduled_date=anchor,
                              recurrence_rule="FREQ=DAILY;COUNT=3")
        start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        res = self.client.get("/api/calendar/", {
            "start": start.isoformat(), "end": (start + timedelta(days=3)).isoformat(),
        })
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        rows = [r for r in res.data["day_tasks"] if r["task_id"] == task.id]
        self.assertEqual([r["scheduled_date"] for r in rows],
                         [(anchor + timedelta(days=i)).isoformat() for i in range(3)])
        self.assertTrue(all(not r["completed"] for r in rows))
        self.assertTrue(all(r["recurring_rule"] == "FREQ=DAILY;COUNT=3" for r in rows))

    def test_expansion_crosses_range_start_and_marks_done_per_date(self):
        anchor = self._anchor(2)
        task = self.make_task(title="Dhikr", scheduled_date=anchor,
                              recurrence_rule="FREQ=DAILY;COUNT=5")
        TaskOccurrenceDone.objects.create(owner=self.user, task=task, date=anchor)
        start = (timezone.now() + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        res = self.client.get("/api/calendar/", {
            "start": start.isoformat(), "end": (start + timedelta(days=2)).isoformat(),
        })
        rows = [r for r in res.data["day_tasks"] if r["task_id"] == task.id]
        # Anchor (today+2) lies inside this 2-day window and is marked done;
        # occurrences before the window are excluded, later ones included.
        dates = [r["scheduled_date"] for r in rows]
        self.assertEqual(dates, [anchor.isoformat()])
        self.assertTrue(rows[0]["completed"])

    def test_occurrence_done_endpoint_works_for_day_series(self):
        anchor = self._anchor(0)
        task = self.make_task(title="Read", scheduled_date=anchor, recurrence_rule="FREQ=DAILY;COUNT=2")
        res = self.client.post(reverse("task-occurrence-done", args=[task.id]),
                               {"date": anchor.isoformat(), "done": True}, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        res = self.client.get("/api/calendar/", {
            "start": start.isoformat(), "end": (start + timedelta(days=2)).isoformat(),
        })
        rows = {r["scheduled_date"]: r["completed"] for r in res.data["day_tasks"]}
        self.assertTrue(rows[anchor.isoformat()])
        self.assertFalse(rows[(anchor + timedelta(days=1)).isoformat()])

    def test_timed_recurring_tasks_do_not_double_as_day_rows(self):
        anchor = self._anchor(0)
        pref = (timezone.now() + timedelta(hours=3)).strftime("%H:%M")
        task = self.make_task(title="Duolingo", recurrence_rule="FREQ=DAILY;COUNT=3",
                              preferred_time=pref, scheduled_date=anchor)
        materialize_recurring_task(task, "UTC")  # direct ORM create skips serializer hooks
        start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        res = self.client.get("/api/calendar/", {
            "start": start.isoformat(), "end": (start + timedelta(days=2)).isoformat(),
        })
        # Timed series appear as blocks, not as whole-day chips.
        self.assertEqual(res.data["day_tasks"], [])
        self.assertTrue(len(res.data["blocks"]) > 0)

    def test_plain_day_task_still_single_row(self):
        anchor = self._anchor(1)
        self.make_task(title="One-off", scheduled_date=anchor)
        start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        res = self.client.get("/api/calendar/", {
            "start": start.isoformat(), "end": (start + timedelta(days=3)).isoformat(),
        })
        self.assertEqual(len(res.data["day_tasks"]), 1)


class UnscheduledFiltersTests(BaseAPITestCase):
    def test_unscheduled_list_excludes_recurring(self):
        self.make_task(title="Plain unscheduled")
        self.make_task(title="Repeats all day", scheduled_date=timezone.localdate(),
                       recurrence_rule="FREQ=DAILY;COUNT=4")
        res = self.client.get(reverse("task-list"), {"unscheduled": "true"})
        titles = [t["title"] for t in res.data]
        self.assertIn("Plain unscheduled", titles)
        self.assertNotIn("Repeats all day", titles)

    def test_dashboard_unscheduled_count_excludes_recurring(self):
        self.make_task(title="Plain unscheduled")
        self.make_task(title="Repeats all day", scheduled_date=timezone.localdate(),
                       recurrence_rule="FREQ=DAILY;COUNT=4")
        res = self.client.get("/api/dashboard/today/")
        self.assertEqual(res.data["unscheduled_count"], 1)
