from django.contrib import admin

from .models import Event, RecurrenceOverride, Task, TimeBlock

admin.site.register(
    Event,
    list_display=("title", "start", "end", "all_day", "is_fixed", "owner"),
    list_filter=("all_day", "is_fixed"),
)
admin.site.register(
    Task,
    list_display=("title", "project", "section", "priority", "completed_at", "estimated_minutes", "owner"),
    list_filter=("priority",),
)
admin.site.register(TimeBlock, list_display=("task", "start", "end", "source", "locked", "owner"))
admin.site.register(RecurrenceOverride, list_display=("__str__", "original_date", "is_cancelled", "owner"))
