from django.contrib import admin

from .models import Profile

admin.site.register(
    Profile,
    list_display = ("user", "timezone", "work_start", "work_end", "prayer_method", "holidays_country"),
)
