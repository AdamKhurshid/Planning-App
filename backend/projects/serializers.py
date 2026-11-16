"""Serializers for projects and sections."""
from rest_framework import serializers

from .models import Project, Section


class ProjectSerializer(serializers.ModelSerializer):
    tasks_total = serializers.IntegerField(read_only=True, default=0)
    tasks_completed = serializers.IntegerField(read_only=True, default=0)
    completion_percent = serializers.FloatField(read_only=True, default=0.0)
    hours_remaining = serializers.FloatField(read_only=True, default=0.0)

    class Meta:
        model = Project
        fields = [
            "id", "title", "description", "deadline", "priority", "color", "status",
            "tasks_total", "tasks_completed", "completion_percent", "hours_remaining",
            "created_at", "updated_at",
        ]

    def to_representation(self, instance):
        # Fill compact stats for read/list calls; on write they are defaults.
        data = super().to_representation(instance)
        if instance and instance.pk:
            from .stats import compact_project_stats

            data.update({k: v for k, v in compact_project_stats(instance).items() if k in {
                "tasks_total", "tasks_completed", "completion_percent", "hours_remaining"
            }})
        return data


class SectionSerializer(serializers.ModelSerializer):
    tasks_total = serializers.IntegerField(read_only=True, default=0)
    tasks_completed = serializers.IntegerField(read_only=True, default=0)
    completion_percent = serializers.FloatField(read_only=True, default=0.0)
    minutes_remaining = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Section
        fields = [
            "id", "project", "title", "description", "position",
            "tasks_total", "tasks_completed", "completion_percent", "minutes_remaining",
            "created_at", "updated_at",
        ]

    def validate_project(self, value):
        if value and value.owner != self.context["request"].user:
            raise serializers.ValidationError("Not your project.")
        return value

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance and instance.pk:
            from .stats import section_stats

            tasks = list(instance.tasks.all())
            stats = section_stats(instance, tasks)
            data.update({
                "tasks_total": stats["tasks_total"],
                "tasks_completed": stats["tasks_completed"],
                "completion_percent": stats["completion_percent"],
                "minutes_remaining": stats["minutes_remaining"],
            })
        return data
