"""Serializers for calendar entries."""
import re

from rest_framework import serializers

from .models import Event, Holiday, RecurrenceOverride, Task, TimeBlock
from .recurrence import validate_rrule


class EventSerializer(serializers.ModelSerializer):
    is_fixed = serializers.BooleanField(default=True, required=False)

    class Meta:
        model = Event
        fields = [
            "id", "title", "description", "start", "end", "all_day",
            "location", "color", "category", "is_fixed", "recurrence_rule",
            "created_at", "updated_at",
        ]

    def validate_recurrence_rule(self, value):
        try:
            validate_rrule(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc))
        return value

    def validate(self, attrs):
        start = attrs.get("start", getattr(self.instance, "start", None))
        end = attrs.get("end", getattr(self.instance, "end", None))
        if start and end and end <= start:
            raise serializers.ValidationError({"end": "end must be after start."})
        return attrs


class TaskSerializer(serializers.ModelSerializer):
    is_completed = serializers.BooleanField(read_only=True)
    is_scheduled = serializers.BooleanField(read_only=True)
    is_recurring = serializers.SerializerMethodField()
    scheduled_minutes = serializers.SerializerMethodField()
    project_title = serializers.CharField(source="project.title", read_only=True, default="")
    section_title = serializers.CharField(source="section.title", read_only=True, default="")

    def get_scheduled_minutes(self, obj):
        dur = getattr(obj, "sched_duration", None)
        return int(dur.total_seconds() // 60) if dur else 0

    class Meta:
        model = Task
        fields = [
            "id", "title", "description", "estimated_minutes", "deadline",
            "priority", "completed_at", "is_completed", "color", "category",
            "project", "project_title", "section", "section_title",
            "position", "recurrence_rule", "preferred_time", "scheduled_date",
            "depends_on", "is_recurring",
            "is_scheduled", "scheduled_minutes",
            "created_at", "updated_at",
        ]

    def get_is_recurring(self, obj):
        return bool(obj.recurrence_rule)

    def validate_recurrence_rule(self, value):
        try:
            validate_rrule(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc))
        return value

    def validate_preferred_time(self, value):
        value = (value or "").strip()
        if value and not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", value):
            raise serializers.ValidationError("preferred_time must look like 08:30.")
        return value

    def validate_estimated_minutes(self, value):
        if value <= 0:
            raise serializers.ValidationError("estimated_minutes must be positive.")
        return value

    def validate(self, attrs):
        task = self.instance
        section = attrs.get("section", getattr(task, "section", None))
        project = attrs.get("project", getattr(task, "project", None))

        # A task inside a section belongs to that section's project.
        if section is not None:
            if project is not None and section.project_id != project.id:
                raise serializers.ValidationError({"section": "section does not belong to the given project."})
            attrs["project"] = section.project
        elif "section" in attrs and attrs["section"] is None:
            # Explicitly removing the section keeps the project link as-is.
            attrs.pop("section", None)

        # No self-dependency (on update; on create there is no id yet).
        if task is not None and "depends_on" in attrs:
            if any(dep.id == task.id for dep in attrs["depends_on"]):
                raise serializers.ValidationError({"depends_on": "A task cannot depend on itself."})
        return attrs


class TimeBlockSerializer(serializers.ModelSerializer):
    task_title = serializers.CharField(source="task.title", read_only=True)
    task_project = serializers.PrimaryKeyRelatedField(source="task.project", read_only=True)
    task_project_color = serializers.CharField(source="task.project.color", read_only=True, default="")
    minutes = serializers.IntegerField(read_only=True)

    class Meta:
        model = TimeBlock
        fields = [
            "id", "task", "task_title", "task_project", "task_project_color",
            "start", "end", "minutes", "source", "locked",
            "created_at", "updated_at",
        ]

    def validate(self, attrs):
        block = self.instance
        task = attrs.get("task", getattr(block, "task", None))
        start = attrs.get("start", getattr(block, "start", None))
        end = attrs.get("end", getattr(block, "end", None))
        if not task:
            raise serializers.ValidationError({"task": "This field is required."})
        if start and end and end <= start:
            raise serializers.ValidationError({"end": "end must be after start."})
        # Blocks of the same task must not overlap (parallel blocks of
        # different tasks are allowed; the scheduler avoids them).
        if TimeBlock.objects.filter(task=task, start__lt=end, end__gt=start).exclude(
            pk=getattr(block, "pk", None)
        ).exists():
            raise serializers.ValidationError({"start": "This task already has a block overlapping that time."})
        return attrs


class RecurrenceOverrideSerializer(serializers.ModelSerializer):
    class Meta:
        model = RecurrenceOverride
        fields = ["id", "event", "task", "original_date", "is_cancelled", "patch"]

    def validate(self, attrs):
        event = attrs.get("event", getattr(self.instance, "event", None))
        task = attrs.get("task", getattr(self.instance, "task", None))
        if bool(event) == bool(task):
            raise serializers.ValidationError("Set exactly one of event or task.")
        return attrs


class HolidaySerializer(serializers.ModelSerializer):
    class Meta:
        model = Holiday
        fields = ["id", "date", "name", "local_name", "country", "region", "source"]
