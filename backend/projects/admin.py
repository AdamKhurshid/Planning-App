from django.contrib import admin

from .models import Project, Section

admin.site.register(
    Project,
    list_display=("title", "status", "priority", "deadline", "owner"),
    list_filter=("status", "priority"),
)
admin.site.register(
    Section,
    list_display=("title", "project", "position"),
    list_filter=("project",),
)
