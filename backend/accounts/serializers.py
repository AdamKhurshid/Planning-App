"""Serializers for auth/profile."""
import re

from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import ASR_MADHABS, PRAYER_METHODS, Profile

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "first_name", "email"]


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = [
            "timezone", "working_days", "work_start", "work_end",
            "max_work_minutes_per_day", "preferred_task_minutes", "min_break_minutes",
            "days_off", "latitude", "longitude", "elevation",
            "prayer_method", "asr_madhab", "prayer_offsets",
            "holidays_country", "holidays_region",
        ]

    def validate_working_days(self, value):
        if not isinstance(value, list) or not value:
            raise serializers.ValidationError("working_days must be a non-empty list of weekdays (0=Mon .. 6=Sun).")
        try:
            days = [int(d) for d in value]
        except (TypeError, ValueError):
            raise serializers.ValidationError("working_days must contain integers 0..6.")
        if any(d < 0 or d > 6 for d in days) or len(set(days)) != len(days):
            raise serializers.ValidationError("working_days must be unique integers in 0..6.")
        return days

    def validate_days_off(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("days_off must be a list of YYYY-MM-DD strings.")
        for item in value:
            if not isinstance(item, str) or not DATE_RE.match(item):
                raise serializers.ValidationError(f"'{item}' is not a YYYY-MM-DD date.")
        return value

    def validate(self, attrs):
        profile = self.instance
        work_start = attrs.get("work_start", getattr(profile, "work_start", None))
        work_end = attrs.get("work_end", getattr(profile, "work_end", None))
        if work_start and work_end and work_start >= work_end:
            raise serializers.ValidationError({"work_end": "work_end must be after work_start."})

        max_minutes = attrs.get("max_work_minutes_per_day", getattr(profile, "max_work_minutes_per_day", 480))
        if not (0 < int(max_minutes) <= 1440):
            raise serializers.ValidationError({"max_work_minutes_per_day": "Must be between 1 and 1440."})

        preferred = attrs.get("preferred_task_minutes", getattr(profile, "preferred_task_minutes", 60))
        if not (10 <= int(preferred) <= 480):
            raise serializers.ValidationError({"preferred_task_minutes": "Must be between 10 and 480 minutes."})

        latitude = attrs.get("latitude", getattr(profile, "latitude", None))
        longitude = attrs.get("longitude", getattr(profile, "longitude", None))
        if (latitude is not None) != (longitude is not None):
            raise serializers.ValidationError("latitude and longitude must be set together.")
        if latitude is not None and not (-90 <= latitude <= 90):
            raise serializers.ValidationError({"latitude": "Must be between -90 and 90."})
        if longitude is not None and not (-180 <= longitude <= 180):
            raise serializers.ValidationError({"longitude": "Must be between -180 and 180."})

        method = attrs.get("prayer_method", getattr(profile, "prayer_method", "MWL"))
        if method not in PRAYER_METHODS:
            raise serializers.ValidationError({"prayer_method": f"Must be one of: {', '.join(PRAYER_METHODS)}."})

        madhab = attrs.get("asr_madhab", getattr(profile, "asr_madhab", "standard"))
        if madhab not in ASR_MADHABS:
            raise serializers.ValidationError({"asr_madhab": "Must be 'standard' or 'hanafi'."})

        offsets = attrs.get("prayer_offsets", getattr(profile, "prayer_offsets", {}))
        if not isinstance(offsets, dict) or any(not isinstance(v, int) for v in offsets.values()):
            raise serializers.ValidationError({"prayer_offsets": "Must map prayer names to integer minute adjustments."})

        country = attrs.get("holidays_country", getattr(profile, "holidays_country", ""))
        if country and not re.fullmatch(r"[A-Za-z]{2}", country):
            raise serializers.ValidationError({"holidays_country": "Use a 2-letter ISO country code."})
        return attrs
