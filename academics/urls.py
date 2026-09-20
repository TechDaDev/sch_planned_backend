"""URLconf for the academic structure API (mounted under ``/api/``)."""

from rest_framework.routers import SimpleRouter

from academics.views import (
    AcademicYearViewSet,
    CollegeViewSet,
    DepartmentViewSet,
    SemesterViewSet,
    StudentGroupViewSet,
    StudyProgramViewSet,
    StudyStageViewSet,
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

urlpatterns = router.urls
