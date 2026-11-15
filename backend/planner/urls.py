from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import CalendarRangeView, DashboardTodayView, EventViewSet, TaskViewSet, TimeBlockViewSet

router = DefaultRouter()
router.register("events", EventViewSet, basename="event")
router.register("tasks", TaskViewSet, basename="task")
router.register("time-blocks", TimeBlockViewSet, basename="timeblock")

urlpatterns = [
    path("calendar/", CalendarRangeView.as_view(), name="calendar-range"),
    path("dashboard/today/", DashboardTodayView.as_view(), name="dashboard-today"),
    path("", include(router.urls)),
]
