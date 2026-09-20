"""URLconf for instructor resources (mounted under ``/api/``)."""

from django.urls import path
from rest_framework.routers import SimpleRouter

from resources.views import (
    InstructorAvailabilityViewSet,
    InstructorDepartmentAccessViewSet,
    InstructorPreferenceViewSet,
    InstructorProfileViewSet,
    MyTeachingAssignmentsView,
    TeachingAssignmentViewSet,
)

app_name = "resources"

router = SimpleRouter()
router.register("instructors", InstructorProfileViewSet, basename="instructor")
router.register(
    "instructor-department-access",
    InstructorDepartmentAccessViewSet,
    basename="instructor-department-access",
)
router.register(
    "instructor-availability",
    InstructorAvailabilityViewSet,
    basename="instructor-availability",
)
router.register(
    "instructor-preferences",
    InstructorPreferenceViewSet,
    basename="instructor-preference",
)
router.register(
    "teaching-assignments",
    TeachingAssignmentViewSet,
    basename="teaching-assignment",
)

urlpatterns = router.urls + [
    # The identity prefix is kept for client clarity, but the route lives with
    # the resource it exposes rather than in the accounts URLconf.
    path(
        "me/teaching-assignments/",
        MyTeachingAssignmentsView.as_view(),
        name="my-teaching-assignments",
    ),
]
