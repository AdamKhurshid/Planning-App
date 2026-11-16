"""Group management: facet groups, group members, bulk delete / bulk
complete, ghost blocks, and the delete-cascade + restore pairing."""
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from projects.models import Project
from .models import Task, TimeBlock
from .recurring_tasks import materialize_recurring_task
from .test_extras import BaseAPITestCase


class GroupFacetTests(BaseAPITestCase):
    def test_title_project_category_recurring_groups(self):
        project = Project.objects.create(owner=self.user, title="Habits", color="#3366ff")
        duo = [self.make_task(title="Duolingo", project=project, category="learning") for _ in range(4)]
        self.make_task(title="Solo", category="learning")
        self.make_task(title="Gym", project=project, recurrence_rule="FREQ=DAILY;INTERVAL=1")
        other = self.make_task(title="Other")
        TimeBlock.objects.create(owner=self.user, task=other,
                                 start=timezone.now(), end=timezone.now() + timedelta(minutes=30))

        res = self.client.get(reverse("task-groups"))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        body = res.data
        self.assertEqual(body["title"], [
            {"key": "Duolingo", "label": "Duolingo", "count": 4},
        ])
        self.assertEqual(
            [(g["key"], g["count"]) for g in body["project"]],
            [("none", 2), (str(project.id), 5)],
        )
        self.assertEqual(body["category"], [{"key": "learning", "label": "learning", "count": 5}])
        self.assertEqual(len(body["recurring"]), 1)
        self.assertEqual(body["recurring"][0]["key"], str(Task.objects.get(title="Gym").id))
        # in_progress bucket: `other` has a block spanning now
        status_map = {g["key"]: g["count"] for g in body["status"]}
        self.assertEqual(status_map["in_progress"], 1)
        self.assertEqual(status_map["open"], 7)
        self.assertEqual(status_map["completed"], 0)
        self.assertEqual(status_map["unscheduled"], 6)  # everything except `other`

    def test_group_members_by_title(self):
        self.make_task(title="Duolingo")
        self.make_task(title="Duolingo")
        self.make_task(title="Gym")
        res = self.client.get(reverse("task-group-members"), {"facet": "title", "key": "Duolingo"})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data), 2)
        self.assertTrue(all(t["title"] == "Duolingo" for t in res.data))

    def test_group_members_status_buckets(self):
        done = self.make_task(title="Done")
        done.completed_at = timezone.now()
        done.save(update_fields=["completed_at"])
        self.make_task(title="Open")
        res = self.client.get(reverse("task-group-members"), {"facet": "status", "key": "completed"})
        self.assertEqual([t["title"] for t in res.data], ["Done"])
        res = self.client.get(reverse("task-group-members"), {"facet": "status", "key": "nope"})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_groups_exclude_other_users(self):
        User = type(self.user)
        other = User.objects.create_user(username="other")
        Task.objects.create(owner=other, title="Duolingo")
        self.make_task(title="Mine")
        res = self.client.get(reverse("task-groups"))
        self.assertEqual([g for g in res.data["title"]], [])  # no repeated-title group
        res = self.client.get(reverse("task-group-members"), {"facet": "title", "key": "Duolingo"})
        self.assertEqual(res.data, [])


class BulkActionTests(BaseAPITestCase):
    def test_bulk_delete_cascades_to_blocks(self):
        tasks = [self.make_task(title="Duolingo") for _ in range(3)]
        for t in tasks:
            TimeBlock.objects.create(owner=self.user, task=t,
                                     start=timezone.now(), end=timezone.now() + timedelta(hours=1))
        keep = self.make_task(title="Keep")
        TimeBlock.objects.create(owner=self.user, task=keep,
                                 start=timezone.now(), end=timezone.now() + timedelta(hours=1))
        res = self.client.post(reverse("task-bulk-delete"), {"ids": [t.id for t in tasks]}, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data, {"deleted": 3})
        self.assertEqual(Task.objects.count(), 1)
        self.assertEqual(TimeBlock.objects.count(), 1)
        self.assertEqual(TimeBlock.objects.get().task_id, keep.id)

    def test_bulk_delete_ignores_foreign_and_deleted_ids(self):
        User = type(self.user)
        other = User.objects.create_user(username="other")
        foreign = Task.objects.create(owner=other, title="Foreign")
        mine = self.make_task(title="Mine")
        res = self.client.post(reverse("task-bulk-delete"),
                               {"ids": [foreign.id, mine.id, 999999]}, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data, {"deleted": 1})
        self.assertTrue(Task.all_objects.filter(pk=foreign.pk, deleted_at__isnull=True).exists())

    def test_bulk_delete_rejects_bad_payload(self):
        for payload in ({}, {"ids": []}, {"ids": "x"}, {"ids": [1, "a"]}):
            res = self.client.post(reverse("task-bulk-delete"), payload, format="json")
            self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_bulk_complete_sets_and_clears(self):
        t1 = self.make_task(title="A")
        t2 = self.make_task(title="B")
        res = self.client.post(reverse("task-bulk-complete"),
                               {"ids": [t1.id, t2.id], "completed": True}, format="json")
        self.assertEqual(res.data, {"changed": 2})
        self.assertEqual(Task.objects.filter(completed_at__isnull=False).count(), 2)
        res = self.client.post(reverse("task-bulk-complete"),
                               {"ids": [t1.id], "completed": False}, format="json")
        self.assertEqual(res.data, {"changed": 1})
        self.assertEqual(Task.objects.filter(completed_at__isnull=False).count(), 1)

    def test_bulk_complete_recurring_materializes(self):
        # A preferred time safely in the future so every COUNT slot lands.
        # When now+2h crosses midnight (suite run late in the UTC day) today's
        # first slot is already past and is correctly skipped by the
        # materializer — expect one fewer block in that case.
        now = timezone.now()
        future = now + timedelta(hours=2)
        pref = future.strftime("%H:%M")
        first_slot_today = future.date() == now.date()
        task = self.make_task(title="Daily", recurrence_rule="FREQ=DAILY;COUNT=5", preferred_time=pref)
        materialize_recurring_task(task, "UTC")  # direct ORM create skips serializer hooks
        self.assertEqual(TimeBlock.objects.filter(task=task).count(), 5 if first_slot_today else 4)
        res = self.client.post(reverse("task-bulk-complete"), {"ids": [task.id], "completed": True}, format="json")
        self.assertEqual(res.data, {"changed": 1})
        # Completing the series retires future slots.
        self.assertEqual(TimeBlock.objects.filter(task=task).count(), 0)

    def test_single_delete_cascades_and_restore_pairs_blocks(self):
        now = timezone.now()
        future = now + timedelta(hours=2)
        pref = future.strftime("%H:%M")
        first_slot_today = future.date() == now.date()
        expected = 3 if first_slot_today else 2
        task = self.make_task(title="Series", recurrence_rule="FREQ=DAILY;COUNT=3", preferred_time=pref)
        materialize_recurring_task(task, "UTC")  # direct ORM create skips serializer hooks
        self.assertEqual(TimeBlock.objects.filter(task=task).count(), expected)
        res = self.client.delete(reverse("task-detail", args=[task.id]))
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(TimeBlock.objects.count(), 0)  # cascade
        res = self.client.post(reverse("task-restore", args=[task.id]))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(TimeBlock.objects.filter(task=task).count(), expected)  # paired restore

    def test_ghost_blocks_count_and_purge(self):
        # Legacy orphans: task already deleted, block still live.
        task = self.make_task(title="Legacy")
        block = TimeBlock.objects.create(owner=self.user, task=task,
                                         start=timezone.now(), end=timezone.now() + timedelta(hours=1))
        task.delete()  # pre-cascade style: leaves the block behind
        self.assertEqual(TimeBlock.objects.filter(pk=block.pk).count(), 1)
        self.assertEqual(self.client.get(reverse("task-ghost-blocks")).data, {"count": 1})
        res = self.client.post(reverse("task-ghost-blocks"))
        self.assertEqual(res.data, {"purged": 1})
        self.assertEqual(TimeBlock.objects.filter(pk=block.pk).count(), 0)
        self.assertEqual(self.client.get(reverse("task-ghost-blocks")).data, {"count": 0})


class GhostLeakRegressionTests(BaseAPITestCase):
    """Blocks of soft-deleted tasks must not surface in calendar/dashboard."""

    def setUp(self):
        super().setUp()
        self.task = self.make_task(title="Duolingo")
        self.start = timezone.now().replace(minute=0, second=0, microsecond=0)
        self.block = TimeBlock.objects.create(owner=self.user, task=self.task,
                                              start=self.start, end=self.start + timedelta(hours=1))
        self.task.delete()  # leaves the block live (legacy behaviour)

    def test_calendar_hides_blocks_of_deleted_tasks(self):
        res = self.client.get("/api/calendar/", {"start": self.start.isoformat(),
                                                 "end": (self.start + timedelta(days=1)).isoformat()})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual([b for b in res.data["blocks"]], [])

    def test_dashboard_hides_blocks_of_deleted_tasks(self):
        res = self.client.get("/api/dashboard/today/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["time_blocks"], [])
        self.assertEqual(res.data["work_today"]["scheduled_minutes"], 0)
