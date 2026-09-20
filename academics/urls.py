"""URLconf for the academic structure API (mounted under ``/api/``)."""

from rest_framework.routers import SimpleRouter

from academics.views import (
    AcademicYearViewSet,
    CollegeViewSet,
    CourseOfferingViewSet,
    CourseViewSet,
    DepartmentViewSet,
    SemesterViewSet,
    StudentGroupViewSet,
    StudyProgramViewSet,
    StudyStageViewSet,
    TeachingComponentGroupViewSet,
    TeachingComponentViewSet,
)

app_name = "academics"

router = SimpleRouter()
router.register("colleges", CollegeViewSet, basename="college")
router.register("departments", DepartmentViewSet, basename="department")
router.register("academic-years", AcademicYearViewSet, basename="academic-year")
router.register("semesters", SemesterViewSet, basename="semester")
router.register("programs", StudyProgramViewSet, basename="study-program")
router.register("stages", StudyStageViewSet, basename="study-stage")
router.register("student-groups", StudentGroupViewSet, basename="student-group")
router.register("courses", CourseViewSet, basename="course")
router.register("course-offerings", CourseOfferingViewSet, basename="course-offering")
router.register(
    "teaching-components", TeachingComponentViewSet, basename="teaching-component"
)
router.register(
    "teaching-component-groups",
    TeachingComponentGroupViewSet,
    basename="teaching-component-group",
)

urlpatterns = router.urls
