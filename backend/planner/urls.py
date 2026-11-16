from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (CalendarRangeView, DashboardTodayView, EventViewSet, HolidayViewSet,
                    ImportView, NotificationsView, ExportView, PrayerTimesView, SearchView,
                    TaskViewSet, TimeBlockViewSet)

router = DefaultRouter()
router.register("events", EventViewSet, basename="event")
router.register("tasks", TaskViewSet, basename="task")
router.register("time-blocks", TimeBlockViewSet, basename="timeblock")
router.register("holidays", HolidayViewSet, basename="holiday")

urlpatterns = [
    path("calendar/", CalendarRangeView.as_view(), name="calendar-range"),
    path("prayer-times/", PrayerTimesView.as_view(), name="prayer-times"),
    path("dashboard/today/", DashboardTodayView.as_view(), name="dashboard-today"),
    path("notifications/", NotificationsView.as_view(), name="notifications"),
    path("search/", SearchView.as_view(), name="search"),
    path("export/", ExportView.as_view(), name="export"),
    path("import/", ImportView.as_view(), name="import"),
    path("", include(router.urls)),
]
