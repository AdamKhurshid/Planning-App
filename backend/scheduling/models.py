"""SchedulePlan: the persisted record of one scheduling run.

It is simultaneously the preview payload, the undo snapshot and the audit
history of scheduling changes. The algorithm itself (Phase 4) lives in
scheduling/algorithm.py as a pure function; this model stores its results.
"""
from django.db import models

from common.models import OwnedSoftDeleteModel


class SchedulePlan(OwnedSoftDeleteModel):
    class Status(models.TextChoices):
        PREVIEW = "preview", "Preview"
        APPLIED = "applied", "Applied"
        UNDONE = "undone", "Undone"
        DISCARDED = "discarded", "Discarded"

    project = models.ForeignKey(
        "projects.Project", null=True, blank=True, on_delete=models.CASCADE, related_name="schedule_plans"
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PREVIEW)
    is_feasible = models.BooleanField(null=True, blank=True)
    feasibility_note = models.TextField(blank=True, default="")
    # When infeasible: how many extra minutes per day would make it feasible.
    deficit_minutes_per_day = models.PositiveIntegerField(null=True, blank=True)
    # Preview payload: proposed items, per-day load, conflicts.
    payload = models.JSONField(default=dict, blank=True)
    # Snapshot of the previous auto-block state, for undo.
    undo_snapshot = models.JSONField(null=True, blank=True)
    applied_at = models.DateTimeField(null=True, blank=True)
    undone_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Plan #{self.pk} ({self.status})"
