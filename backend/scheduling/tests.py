"""Scheduler tests: pure algorithm (no DB) + API flow (preview/apply/undo)."""
from datetime import date, datetime, time, timedelta, timezone as dt_tz
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from planner.models import Event, Task, TimeBlock
from projects.models import Project, Section

from .algorithm import Settings, TaskInput, build_plan, compute_availability, level_quotas, order_tasks
from .models import SchedulePlan

UTC = ZoneInfo("UTC")
MON = datetime(2030, 1, 7, 8, 0, tzinfo=UTC)  # a Monday, before work starts


def settings(**kw):
    return Settings(tz=UTC, **kw)


class LevelQuotaTests(SimpleTestCase):
    def test_even_spread(self):
        self.assertEqual(level_quotas([480, 480, 480], 300), [100, 100, 100])

    def test_small_days_are_capped_and_rest_redistributed(self):
        self.assertEqual(level_quotas([30, 480, 480], 330), [30, 150, 150])

    def test_infeasible_returns_capacities(self):
        self.assertEqual(level_quotas([60, 60], 500), [60, 60])

    def test_zero(self):
        self.assertEqual(level_quotas([60, 60], 0), [0, 0])
        self.assertEqual(level_quotas([], 10), [])


class AvailabilityTests(SimpleTestCase):
    def test_weekends_and_days_off_skipped(self):
        days = compute_availability(settings(days_off=frozenset({date(2030, 1, 9)})), MON, MON + timedelta(days=7), [])
        dates = [d.date for d in days]
        self.assertNotIn(date(2030, 1, 9), dates)       # day off
        self.assertNotIn(date(2030, 1, 12), dates)      # Saturday
        self.assertEqual(len(dates), 4)                 # Mon Tue Thu Fri (+Mon 14th at 08:00 excluded: window empty)

    def test_busy_interval_removed_and_cap_applied(self):
        busy = [(datetime(2030, 1, 7, 12, 0, tzinfo=UTC), datetime(2030, 1, 7, 13, 0, tzinfo=UTC))]
        d = compute_availability(settings(max_minutes_per_day=300), MON, MON + timedelta(hours=10), busy)[0]
        self.assertEqual(len(d.slots), 2)
        self.assertEqual(d.capacity, 300)  # 420 free but capped at 300

    def test_today_starts_at_now(self):
        now = datetime(2030, 1, 7, 14, 2, tzinfo=UTC)
        d = compute_availability(settings(), now, now + timedelta(hours=8), [])[0]
        self.assertEqual(d.slots[0][0], datetime(2030, 1, 7, 14, 5, tzinfo=UTC))

    def test_manual_load_counts_against_cap(self):
        d = compute_availability(settings(max_minutes_per_day=480), MON, MON + timedelta(hours=10), [],
                                 {date(2030, 1, 7): 400})[0]
        self.assertEqual(d.capacity, 80)


class OrderingTests(SimpleTestCase):
    def test_dependencies_override_manual_order(self):
        a = TaskInput(1, "a", 60, (0, 0), depends_on=(2,))
        b = TaskInput(2, "b", 60, (0, 1))
        ordered, cyc = order_tasks([a, b])
        self.assertEqual([t.id for t in ordered], [2, 1])
        self.assertEqual(cyc, [])

    def test_cycle_reported_not_fatal(self):
        a = TaskInput(1, "a", 60, (0, 0), depends_on=(2,))
        b = TaskInput(2, "b", 60, (0, 1), depends_on=(1,))
        ordered, cyc = order_tasks([a, b])
        self.assertEqual(len(ordered), 2)
        self.assertEqual(set(cyc), {1, 2})

    def test_priority_mode(self):
        lo = TaskInput(1, "lo", 60, (0, 0), priority="low")
        hi = TaskInput(2, "hi", 60, (0, 1), priority="urgent")
        self.assertEqual([t.id for t in order_tasks([lo, hi], "priority")[0]], [2, 1])


class BuildPlanTests(SimpleTestCase):
    def run_plan(self, tasks, days=5, **kw):
        s = kw.pop("settings", settings())
        return build_plan(tasks, s, MON, MON + timedelta(days=days), **kw)

    def test_spreads_work_evenly(self):
        tasks = [TaskInput(i, f"t{i}", 60, (0, i)) for i in range(5)]
        r = self.run_plan(tasks, days=5)
        self.assertTrue(r["feasible"])
        per_day = {d["date"]: d["planned_minutes"] for d in r["per_day"]}
        self.assertEqual(len(per_day), 5)
        self.assertEqual(sorted(per_day.values()), [60, 60, 60, 60, 60])  # one task per day, not 5h on day one
        self.assertTrue(all(v <= 120 for v in per_day.values()))
        self.assertEqual(r["totals"]["planned_minutes"], 300)

    def test_no_overlaps_and_breaks_respected(self):
        tasks = [TaskInput(i, f"t{i}", 60, (0, i)) for i in range(8)]
        r = self.run_plan(tasks, days=2)
        blocks = r["blocks"]
        for a, b in zip(blocks, blocks[1:]):
            if a["start"].date() == b["start"].date():
                self.assertGreaterEqual(b["start"] - a["end"], timedelta(minutes=15))

    def test_blocks_stay_inside_work_hours_and_avoid_busy(self):
        busy = [(datetime(2030, 1, 7, 9, 0, tzinfo=UTC), datetime(2030, 1, 7, 12, 0, tzinfo=UTC))]
        r = build_plan([TaskInput(1, "t", 120, (0, 0))], settings(), MON, MON + timedelta(hours=10), busy=busy)
        for b in r["blocks"]:
            self.assertGreaterEqual(b["start"], datetime(2030, 1, 7, 12, 0, tzinfo=UTC))
            self.assertLessEqual(b["end"], datetime(2030, 1, 7, 17, 0, tzinfo=UTC))

    def test_block_date_is_local_not_utc(self):
        ny = ZoneInfo("America/New_York")
        now = datetime(2030, 1, 7, 8, 0, tzinfo=ny)
        s = Settings(tz=ny, work_start=time(17, 0), work_end=time(22, 0))   # 22:00 NY == 03:00 UTC next day
        r = build_plan([TaskInput(1, "late", 60)], s, now, now + timedelta(hours=16))
        self.assertEqual(r["blocks"][0]["date"], date(2030, 1, 7))

    def test_long_task_is_split(self):
        r = self.run_plan([TaskInput(1, "big", 300, (0, 0))], days=1)
        self.assertGreater(len(r["blocks"]), 1)
        self.assertEqual(sum(b["minutes"] for b in r["blocks"]), 300)
        self.assertTrue(all(b["minutes"] <= 120 for b in r["blocks"]))

    def test_dependency_order_in_time(self):
        a = TaskInput(1, "first-by-position", 60, (0, 0), depends_on=(2,))
        b = TaskInput(2, "prereq", 60, (0, 1))
        r = self.run_plan([a, b], days=3)
        end_b = max(x["end"] for x in r["blocks"] if x["task_id"] == 2)
        start_a = min(x["start"] for x in r["blocks"] if x["task_id"] == 1)
        self.assertGreaterEqual(start_a, end_b)

    def test_infeasible_reports_deficit(self):
        tasks = [TaskInput(i, f"t{i}", 480, (0, i)) for i in range(4)]  # 32h of work, 1 day available
        r = build_plan(tasks, settings(), MON, MON + timedelta(hours=10))
        self.assertFalse(r["feasible"])
        self.assertGreater(r["totals"]["unplaced_minutes"], 0)
        self.assertEqual(r["deficit_minutes_per_day"], r["totals"]["unplaced_minutes"])
        self.assertTrue(any(c["type"] == "unplaced" for c in r["conflicts"]))
        self.assertEqual(r["totals"]["planned_minutes"] + r["totals"]["unplaced_minutes"], 1920)

    def test_no_availability(self):
        r = build_plan([TaskInput(1, "t", 60)], settings(working_days=()), MON, MON + timedelta(days=3))
        self.assertFalse(r["feasible"])
        self.assertEqual(r["conflicts"][0]["type"], "no_availability")

    def test_task_deadline_conflict(self):
        t = TaskInput(1, "t", 60, deadline=MON + timedelta(minutes=30))
        r = self.run_plan([t], days=2)
        self.assertTrue(any(c["type"] == "task_deadline" for c in r["conflicts"]))

    def test_daily_cap_never_exceeded(self):
        tasks = [TaskInput(i, f"t{i}", 60, (0, i)) for i in range(10)]
        r = self.run_plan(tasks, days=4, settings=settings(max_minutes_per_day=180))
        self.assertTrue(all(d["planned_minutes"] <= 180 for d in r["per_day"]))

    def test_total_conserved_property(self):
        import random
        rng = random.Random(7)
        for _ in range(40):
            tasks = [TaskInput(i, f"t{i}", rng.choice([10, 25, 45, 60, 90, 200]), (0, i)) for i in range(rng.randint(1, 9))]
            days = rng.randint(1, 6)
            r = build_plan(tasks, settings(), MON, MON + timedelta(days=days))
            want = sum(t.minutes for t in tasks)
            self.assertEqual(r["totals"]["planned_minutes"] + r["totals"]["unplaced_minutes"], want)
            self.assertEqual(sum(b["minutes"] for b in r["blocks"]), r["totals"]["planned_minutes"])
            bl = r["blocks"]
            for i, a in enumerate(bl):                      # no overlaps at all
                for b in bl[i + 1:]:
                    self.assertTrue(a["end"] <= b["start"] or b["end"] <= a["start"])


class PlanAPITests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="owner")
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.user).key}")
        from accounts.models import Profile
        Profile.objects.get_or_create(user=self.user)
        self.project = Project.objects.create(owner=self.user, title="P",
                                              deadline=timezone.now() + timedelta(days=21))
        self.section = Section.objects.create(owner=self.user, project=self.project, title="S")
        self.tasks = [Task.objects.create(owner=self.user, title=f"T{i}", project=self.project,
                                          section=self.section, position=i, estimated_minutes=60)
                      for i in range(6)]

    def preview(self, **extra):
        return self.client.post("/api/scheduling/plans/preview/", {"project": self.project.id, **extra}, format="json")

    def test_requires_auth(self):
        self.client.credentials()
        self.assertEqual(self.preview().status_code, 401)

    def test_preview_does_not_touch_calendar(self):
        r = self.preview()
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.data["is_feasible"])
        self.assertEqual(r.data["status"], "preview")
        self.assertEqual(TimeBlock.objects.count(), 0)
        self.assertEqual(sum(b["minutes"] for b in r.data["payload"]["blocks"]), 360)

    def test_apply_then_undo_roundtrip(self):
        plan_id = self.preview().data["id"]
        r = self.client.post(f"/api/scheduling/plans/{plan_id}/apply/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(TimeBlock.objects.filter(source="auto").count(), len(r.data["payload"]["blocks"]))
        self.assertEqual(self.client.post(f"/api/scheduling/plans/{plan_id}/apply/").status_code, 409)
        r = self.client.post(f"/api/scheduling/plans/{plan_id}/undo/")
        self.assertEqual(r.data["status"], "undone")
        self.assertEqual(TimeBlock.objects.count(), 0)

    def test_reschedule_replaces_old_auto_blocks_and_undo_restores_them(self):
        p1 = self.preview().data["id"]
        self.client.post(f"/api/scheduling/plans/{p1}/apply/")
        first = set(TimeBlock.objects.values_list("id", flat=True))
        p2 = self.preview().data["id"]
        self.client.post(f"/api/scheduling/plans/{p2}/apply/")
        self.assertTrue(first.isdisjoint(set(TimeBlock.objects.values_list("id", flat=True))))
        self.assertEqual(TimeBlock.objects.count(), len(first))     # replaced, not duplicated
        self.client.post(f"/api/scheduling/plans/{p2}/undo/")
        self.assertEqual(set(TimeBlock.objects.values_list("id", flat=True)), first)

    def test_locked_and_manual_blocks_are_kept(self):
        t = self.tasks[0]
        start = (timezone.now() + timedelta(days=2)).replace(hour=10, minute=0, second=0, microsecond=0)
        TimeBlock.objects.create(owner=self.user, task=t, start=start, end=start + timedelta(minutes=60),
                                 source="manual", locked=True)
        r = self.preview()
        scheduled_for_t = sum(b["minutes"] for b in r.data["payload"]["blocks"] if b["task_id"] == t.id)
        self.assertEqual(scheduled_for_t, 0)  # its 60 min are already covered
        self.client.post(f"/api/scheduling/plans/{r.data['id']}/apply/")
        self.assertTrue(TimeBlock.objects.filter(task=t, locked=True).exists())

    def test_completed_tasks_are_skipped(self):
        for t in self.tasks[:2]:
            t.completed_at = timezone.now()
            t.save()
        r = self.preview()
        self.assertEqual(sum(b["minutes"] for b in r.data["payload"]["blocks"]), 240)

    def test_events_block_time_including_recurring(self):
        start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        Event.objects.create(owner=self.user, title="Offsite", start=start, end=start + timedelta(hours=24),
                             recurrence_rule="FREQ=DAILY;COUNT=40")  # blocks every day, starting today
        r = self.preview()
        self.assertFalse(r.data["is_feasible"])   # every day is blocked
        self.assertIn("extra min/day", r.data["feasibility_note"])

    def test_infeasible_when_deadline_too_close(self):
        self.project.deadline = timezone.now() + timedelta(minutes=5)
        self.project.save()
        r = self.preview()
        self.assertFalse(r.data["is_feasible"])

    def test_discard_and_isolation(self):
        pid = self.preview().data["id"]
        self.assertEqual(self.client.post(f"/api/scheduling/plans/{pid}/discard/").data["status"], "discarded")
        other = get_user_model().objects.create_user(username="intruder")
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=other).key}")
        self.assertEqual(self.client.get(f"/api/scheduling/plans/{pid}/").status_code, 404)
        self.assertEqual(self.preview().status_code, 400)   # cannot plan someone else's project

    def test_newer_preview_discards_older(self):
        a = self.preview().data["id"]
        self.preview()
        self.assertEqual(SchedulePlan.objects.get(pk=a).status, "discarded")

    def test_validation(self):
        self.assertEqual(self.client.post("/api/scheduling/plans/preview/", {}, format="json").status_code, 400)
        self.assertEqual(self.preview(order="bogus").status_code, 400)
