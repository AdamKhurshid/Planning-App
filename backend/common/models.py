"""Minimal shared model building blocks used by all apps.

`common` is intentionally not a Django app: it only holds abstract models,
managers and enums that the real apps (accounts, planner, projects,
scheduling) build on.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone


class Priority(models.TextChoices):
    """Shared priority scale for tasks and projects."""

    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"
    URGENT = "urgent", "Urgent"


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class ActiveManager(models.Manager):
    """Default manager that hides soft-deleted rows.

    Related managers (e.g. task.blocks) are built from the related model's
    default manager class, so reverse relations also hide deleted rows.
    """

    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class OwnedSoftDeleteModel(TimeStampedModel):
    """Base for all user data: ownership + reversible soft delete."""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True

    objects = ActiveManager()
    all_objects = models.Manager()

    def delete(self, using=None, keep_parents=False):
        """Soft delete: mark deleted_at instead of removing the row."""
        self.deleted_at = timezone.now()
        self.save(update_fields=["deleted_at", "updated_at"])

    def restore(self):
        self.deleted_at = None
        self.save(update_fields=["deleted_at", "updated_at"])
