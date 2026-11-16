"""Project and Section models.

Completion stats are computed on demand (see stats.py) — never stored —
so they can never drift out of sync with the underlying tasks.
"""
from django.core.exceptions import ValidationError
from django.db import models

from common.models import OwnedSoftDeleteModel, Priority


class Project(OwnedSoftDeleteModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        PAUSED = "paused", "Paused"
        COMPLETED = "completed", "Completed"
        ARCHIVED = "archived", "Archived"

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    deadline = models.DateTimeField(null=True, blank=True)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    color = models.CharField(max_length=20, blank=True, default="")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return self.title


class Section(OwnedSoftDeleteModel):
    """A major phase/area of work within a project. Order is manual."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="sections")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self):
        return f"{self.project.title} / {self.title}"

    def clean(self):
        if not self.title.strip():
            raise ValidationError("Section title is required.")
