from rest_framework.routers import DefaultRouter

from .views import ProjectViewSet, SectionViewSet

router = DefaultRouter()
router.register("projects", ProjectViewSet, basename="project")
router.register("sections", SectionViewSet, basename="section")

urlpatterns = router.urls
