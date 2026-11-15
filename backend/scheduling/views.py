"""Scheduling API (Phase 4 implements the algorithm + endpoints).

Phase 1 exposes read-only plan history so the frontend can already wire up
the data shape.
"""
from rest_framework import mixins, viewsets

from .models import SchedulePlan


class SchedulePlanViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """GET /api/scheduling/plans/ — history of scheduling runs."""

    def get_queryset(self):
        return SchedulePlan.objects.filter(owner=self.request.user)

    def get_serializer_class(self):
        from rest_framework import serializers

        class SchedulePlanSerializer(serializers.ModelSerializer):
            class Meta:
                model = SchedulePlan
                fields = "__all__"

        return SchedulePlanSerializer
