"""Root URL configuration: everything the app exposes lives under /api/."""
from django.contrib import admin
from django.urls import include, path

from accounts.urls import preferences_patterns

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("accounts.urls")),
    path("api/", include(preferences_patterns)),
    path("api/", include("planner.urls")),
    path("api/", include("projects.urls")),
    path("api/", include("scheduling.urls")),
]
