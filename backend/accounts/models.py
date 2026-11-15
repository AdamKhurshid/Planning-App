"""User profile: availability settings (used by the scheduler) plus prayer
and holiday preferences.

The profile is auto-created for the single private user on first login (and
by `manage.py setup`), so every code path can rely on `user.profile`.
"""
from datetime import time

from django.conf import settings
from django.db import models

from common.models import TimeStampedModel


def _default_working_days():
    # Monday..Friday (0=Mon .. 6=Sun)
    return [0, 1, 2, 3, 4]


# Prayer calculation methods supported by the prayer-time service (Phase 5).
# Keys follow the well-known method names; "custom" adds offsets only.
PRAYER_METHODS = ["MWL", "ISNA", "Egypt", "Makkah", "Karachi", "Gulf", "Kuwait", "Qatar", "Singapore", "Turkey", "Tehran", "custom"]

ASR_MADHABS = ["standard", "hanafi"]


class Profile(TimeStampedModel):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")

    # --- scheduling availability ---
    timezone = models.CharField(max_length=64, default=settings.TEMPO_TIMEZONE)
    working_days = models.JSONField(default=_default_working_days)  # list of ints 0..6
    work_start = models.TimeField(default=time(9, 0))
    work_end = models.TimeField(default=time(17, 0))
    max_work_minutes_per_day = models.PositiveIntegerField(default=480)
    preferred_task_minutes = models.PositiveIntegerField(default=60)
    min_break_minutes = models.PositiveIntegerField(default=15)
    days_off = models.JSONField(default=list)  # list of "YYYY-MM-DD" strings

    # --- prayer times ---
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    elevation = models.FloatField(default=0)
    prayer_method = models.CharField(max_length=20, default="MWL")
    asr_madhab = models.CharField(max_length=10, default="standard")
    prayer_offsets = models.JSONField(default=dict)  # {"fajr": -5, ...} minute adjustments

    # --- holidays ---
    holidays_country = models.CharField(max_length=2, blank=True, default="")  # ISO 3166-1 alpha-2
    holidays_region = models.CharField(max_length=10, blank=True, default="")  # ISO 3166-2 subdivision

    def __str__(self):
        return f"Profile({self.user.username})"

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.work_start >= self.work_end:
            raise ValidationError("work_start must be earlier than work_end.")
