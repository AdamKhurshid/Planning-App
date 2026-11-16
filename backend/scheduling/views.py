"""Scheduling API.

GET  /api/scheduling/plans/                 history of plans
GET  /api/scheduling/plans/{id}/            one plan (payload = proposed blocks, per-day load, conflicts)
POST /api/scheduling/plans/preview/         {project, order?: manual|priority, horizon_days?} -> new preview
POST /api/scheduling/plans/{id}/apply/      write the preview onto the calendar
POST /api/scheduling/plans/{id}/undo/       revert an applied plan
POST /api/scheduling/plans/{id}/discard/    throw a preview away
"""
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from projects.models import Project

from . import services
from .models import SchedulePlan


class SchedulePlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = SchedulePlan
        fields = [
            "id", "project", "status", "is_feasible", "feasibility_note",
            "deficit_minutes_per_day", "payload", "applied_at", "undone_at",
            "created_at", "updated_at",
        ]
        read_only_fields = fields


class PreviewRequestSerializer(serializers.Serializer):
    project = serializers.IntegerField()
    order = serializers.ChoiceField(choices=["manual", "priority"], default="manual")
    horizon_days = serializers.IntegerField(required=False, min_value=1, max_value=services.MAX_HORIZON_DAYS)


class SchedulePlanViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = SchedulePlanSerializer

    def get_queryset(self):
        qs = SchedulePlan.objects.filter(owner=self.request.user)
        if self.request.query_params.get("project"):
            qs = qs.filter(project_id=self.request.query_params["project"])
        return qs

    @action(detail=False, methods=["post"])
    def preview(self, request):
        req = PreviewRequestSerializer(data=request.data)
        req.is_valid(raise_exception=True)
        project = Project.objects.filter(owner=request.user, pk=req.validated_data["project"]).first()
        if project is None:
            return Response({"project": ["Project not found."]}, status=status.HTTP_400_BAD_REQUEST)
        plan = services.create_preview(
            request.user, project, order=req.validated_data["order"],
            horizon_days=req.validated_data.get("horizon_days"))
        return Response(self.get_serializer(plan).data, status=status.HTTP_201_CREATED)

    def _transition(self, fn):
        plan = self.get_object()
        try:
            plan = fn(plan)
        except services.PlanError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(self.get_serializer(plan).data)

    @action(detail=True, methods=["post"])
    def apply(self, request, pk=None):
        return self._transition(services.apply_plan)

    @action(detail=True, methods=["post"])
    def undo(self, request, pk=None):
        return self._transition(services.undo_plan)

    @action(detail=True, methods=["post"])
    def discard(self, request, pk=None):
        return self._transition(services.discard_plan)
