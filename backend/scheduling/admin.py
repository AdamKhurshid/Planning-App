from django.contrib import admin

from .models import SchedulePlan

admin.site.register(
    SchedulePlan,
    list_display=("id", "project", "status", "is_feasible", "created_at", "owner"),
    list_filter=("status",),
)
