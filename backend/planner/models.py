"""Calendar entry models: Event, Task, TimeBlock, RecurrenceOverride.

Key design decision: a *Task* (work to do) is separate from a *TimeBlock*
(calendar time scheduled to work on that task). The scheduler only ever
moves TimeBlocks with source="auto"; Events are fixed commitments it never
touches. Unscheduled tasks simply have no blocks and remain visible in their
project.
"""
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from common.models import OwnedSoftDeleteModel, Priority


class Event(OwnedSoftDeleteModel):
    """A fixed commitment happening at a specific time.

    All-day events are stored as midnight -> next-midnight with all_day=True;
    the UI renders them as day banners, not artificial timed entries.
    """

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    start = models.DateTimeField()
    end = models.DateTimeField()
    all_day = models.BooleanField(default=False)
    location = models.CharField(max_length=255, blank=True, default="")
    color = models.CharField(max_length=20, blank=True, default="")
    category = models.CharField(max_length=50, blank=True, default="")
    # Events are fixed unless explicitly marked otherwise.
    is_fixed = models.BooleanField(default=True)
    # RFC 5545 RRULE string (without DTSTART), e.g. "FREQ=WEEKLY;BYDAY=MO,WE".
    recurrence_rule = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["start"]
        indexes = [models.Index(fields=["start"])]

    def __str__(self):
        return self.title

    def clean(self):
        if self.start and self.end and self.end <= self.start:
            raise ValidationError("Event end must be after its start.")


class Task(OwnedSoftDeleteModel):
    """A unit of work to get done (~1 hour chunks by convention).

    Tasks may belong to a Project and a Section. Belonging to a Section
    implies the project (enforced). A task does not need to be scheduled:
    unscheduled tasks simply have no TimeBlocks.
    """

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    estimated_minutes = models.PositiveIntegerField(default=60)
    deadline = models.DateTimeField(null=True, blank=True)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    completed_at = models.DateTimeField(null=True, blank=True)
    color = models.CharField(max_length=20, blank=True, default="")
    category = models.CharField(max_length=50, blank=True, default="")
    project = models.ForeignKey(
        "projects.Project", null=True, blank=True, on_delete=models.CASCADE, related_name="tasks"
    )
    section = models.ForeignKey(
        "projects.Section", null=True, blank=True, on_delete=models.CASCADE, related_name="tasks"
    )
    position = models.PositiveIntegerField(default=0)
    recurrence_rule = models.CharField(max_length=200, blank=True, default="")
    depends_on = models.ManyToManyField("self", symmetrical=False, blank=True, related_name="dependents")

    class Meta:
        ordering = ["position", "id"]
        indexes = [models.Index(fields=["deadline"])]

    def __str__(self):
        return self.title

    @property
    def is_completed(self):
        return self.completed_at is not None

    @property
    def is_scheduled(self):
        return self.blocks.exists()  # default manager hides deleted blocks

    def clean(self):
        # A task inside a section belongs to that section's project.
        if self.section_id:
            if self.project_id and self.section.project_id != self.project_id:
                raise ValidationError("section does not belong to the given project.")
            self.project = self.section.project
        if self.pk and self.depends_on.filter(pk=self.pk).exists():
            raise ValidationError("A task cannot depend on itself.")
        if self.estimated_minutes is not None and self.estimated_minutes <= 0:
            raise ValidationError("estimated_minutes must be positive.")


class TimeBlock(OwnedSoftDeleteModel):
    """Calendar time scheduled for work on a Task — the calendar-facing
    object for project work. One task can have many blocks."""

    class Source(models.TextChoices):
        MANUAL = "manual", "Manual"
        AUTO = "auto", "Scheduler"

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="blocks")
    start = models.DateTimeField()
    end = models.DateTimeField()
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.MANUAL)
    # Locked blocks are pinned by the user; the scheduler never moves them.
    locked = models.BooleanField(default=False)

    class Meta:
        ordering = ["start"]
        indexes = [models.Index(fields=["start"])]

    def __str__(self):
        return f"{self.task.title} @ {self.start:%Y-%m-%d %H:%M}"

    @property
    def minutes(self):
        return int((self.end - self.start).total_seconds() // 60)

    def clean(self):
        if self.start and self.end and self.end <= self.start:
            raise ValidationError("TimeBlock end must be after its start.")
        # Blocks of the SAME task must not overlap; parallel blocks of
        # different tasks are allowed (the scheduler avoids them).
        if self.task_id and self.start and self.end:
            overlap = TimeBlock.objects.filter(
                task_id=self.task_id, start__lt=self.end, end__gt=self.start
            ).exclude(pk=self.pk).exists()
            if overlap:
                raise ValidationError("This task already has a block overlapping that time.")


class RecurrenceOverride(OwnedSoftDeleteModel):
    """Exception for one occurrence of a recurring event or task.

    Exactly one of event/task must be set. Either cancel the occurrence or
    patch chosen fields (stored as a JSON dict of field -> new value).
    """

    event = models.ForeignKey(Event, null=True, blank=True, on_delete=models.CASCADE, related_name="overrides")
    task = models.ForeignKey(Task, null=True, blank=True, on_delete=models.CASCADE, related_name="overrides")
    original_date = models.DateField()
    is_cancelled = models.BooleanField(default=False)
    patch = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["original_date"]
        constraints = [
            models.UniqueConstraint(fields=["event", "original_date"], name="unique_event_override_date"),
            models.UniqueConstraint(fields=["task", "original_date"], name="unique_task_override_date"),
        ]

    def clean(self):
        if bool(self.event_id) == bool(self.task_id):
            raise ValidationError("Set exactly one of event or task.")
