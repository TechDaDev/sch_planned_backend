"""URLconf for instructor resources (mounted under ``/api/``)."""

from django.urls import path
from rest_framework.routers import SimpleRouter

from resources.views import (
    InstructorAvailabilityViewSet,
    InstructorDepartmentAccessViewSet,
    InstructorPreferenceViewSet,
    InstructorProfileViewSet,
    MyTeachingAssignmentsView,
    RoomAvailabilityViewSet,
    RoomCapabilityAssignmentViewSet,
    RoomCapabilityViewSet,
    RoomDepartmentAccessViewSet,
    RoomTypeViewSet,
    RoomViewSet,
    TeachingAssignmentViewSet,
    TeachingComponentCapabilityRequirementViewSet,
    TeachingComponentRoomRequirementViewSet,
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
router.register("room-types", RoomTypeViewSet, basename="room-type")
router.register("room-capabilities", RoomCapabilityViewSet, basename="room-capability")
router.register("rooms", RoomViewSet, basename="room")
router.register(
    "room-department-access",
    RoomDepartmentAccessViewSet,
    basename="room-department-access",
)
router.register(
    "room-capability-assignments",
    RoomCapabilityAssignmentViewSet,
    basename="room-capability-assignment",
)
router.register(
    "room-availability",
    RoomAvailabilityViewSet,
    basename="room-availability",
)
router.register(
    "teaching-component-room-requirements",
    TeachingComponentRoomRequirementViewSet,
    basename="teaching-component-room-requirement",
)
router.register(
    "teaching-component-capability-requirements",
    TeachingComponentCapabilityRequirementViewSet,
    basename="teaching-component-capability-requirement",
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
