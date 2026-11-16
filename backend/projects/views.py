"""ViewSets for projects and sections."""
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from planner.models import Task

from .models import Project, Section
from .serializers import ProjectSerializer, SectionSerializer
from .stats import project_stats


class ProjectViewSet(ModelViewSet):
    serializer_class = ProjectSerializer

    def get_queryset(self):
        qs = Project.objects.filter(owner=self.request.user)
        params = self.request.query_params
        if params.get("status"):
            qs = qs.filter(status=params["status"])
        if params.get("priority"):
            qs = qs.filter(priority=params["priority"])
        search = params.get("search")
        if search:
            qs = qs.filter(title__icontains=search) | qs.filter(description__icontains=search)
        return qs

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    def perform_destroy(self, instance):
        # Soft-delete the project and everything inside it, so nothing is
        # lost silently; restoring the project restores its children.
        for task in instance.tasks.all():
            task.delete()
        for section in instance.sections.all():
            section.delete()
        instance.delete()

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        project = Project.all_objects.filter(owner=request.user, pk=pk).first()
        if project is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        # Use all_objects: the default manager hides soft-deleted children.
        for task in Task.all_objects.filter(project_id=pk, owner=request.user):
            task.restore()
        for section in Section.all_objects.filter(project_id=pk, owner=request.user):
            section.restore()
        project.restore()
        return Response(self.get_serializer(project).data)

    @action(detail=True, methods=["get"])
    def summary(self, request, pk=None):
        project = self.get_object()
        return Response(project_stats(project))


class SectionViewSet(ModelViewSet):
    serializer_class = SectionSerializer

    def get_queryset(self):
        qs = Section.objects.filter(owner=self.request.user)
        project_id = self.request.query_params.get("project")
        if project_id:
            qs = qs.filter(project_id=project_id)
        return qs

    def perform_create(self, serializer):
        # Append to the end of the project's section list by default.
        project = serializer.validated_data["project"]
        last = project.sections.order_by("-position").first()
        serializer.save(owner=self.request.user, position=(last.position + 1) if last else 0)

    @action(detail=False, methods=["post"], url_path="reorder")
    def reorder(self, request):
        """POST {ordered_ids: [...]} — assign positions 0..n in list order.
        All sections must belong to the same project (implicit: the first one's)."""
        ordered_ids = request.data.get("ordered_ids")
        if not isinstance(ordered_ids, list) or not ordered_ids:
            raise ValidationError({"ordered_ids": ["A non-empty list of section ids is required."]})
        sections = []
        for section_id in ordered_ids:
            section = Section.objects.filter(owner=request.user, pk=section_id).first()
            if section is None:
                raise ValidationError({"ordered_ids": [f"Section {section_id} not found."]})
            sections.append(section)
        project_ids = {s.project_id for s in sections}
        if len(project_ids) > 1:
            raise ValidationError({"ordered_ids": ["All sections must belong to the same project."]})
        for position, section in enumerate(sections):
            section.position = position
            section.save(update_fields=["position", "updated_at"])
        return Response(self.get_serializer(sections, many=True).data)
