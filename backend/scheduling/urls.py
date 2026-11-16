from rest_framework.routers import DefaultRouter

from .views import SchedulePlanViewSet

router = DefaultRouter()
router.register("scheduling/plans", SchedulePlanViewSet, basename="scheduleplan")

urlpatterns = router.urls
