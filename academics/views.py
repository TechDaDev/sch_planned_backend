"""Academic structure API views.

Authorization is enforced twice: querysets are scoped to the caller's department
so out-of-scope records answer 404 without revealing that they exist, and the
Phase 2 permission classes gate the write roles.

Hard deletes are not part of the API: records are retired with ``is_active`` and
``DELETE`` answers HTTP 405.
"""

from django.db.models import Prefetch
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from academics.models import (
    AcademicYear,
    College,
    Course,
    CourseOffering,
    Department,
    Semester,
    StudentGroup,
    StudyProgram,
    StudyStage,
    TeachingComponent,
    TeachingComponentGroup,
)
from academics.permissions import (
    CanManageDepartments,
    IsCollegeAdminOrReadOnly,
    IsDepartmentScopedManager,
    IsDepartmentScopedWriter,
    visible_components_filter,
    visible_courses_filter,
    visible_group_links_filter,
    visible_offerings_filter,
)
from academics.serializers import (
    AcademicYearSerializer,
    CollegeSerializer,
    CourseOfferingSerializer,
    CourseOfferingWriteSerializer,
    CourseSerializer,
    CourseWriteSerializer,
    DepartmentSerializer,
    DepartmentWriteSerializer,
    SemesterSerializer,
    SemesterWriteSerializer,
    StudentGroupSerializer,
    StudentGroupWriteSerializer,
    StudyProgramSerializer,
    StudyProgramWriteSerializer,
    StudyStageSerializer,
    StudyStageWriteSerializer,
    TeachingComponentGroupSerializer,
    TeachingComponentGroupWriteSerializer,
    TeachingComponentSerializer,
    TeachingComponentWriteSerializer,
)

ACADEMIC_TAGS = ["academics"]
TEACHING_TAGS = ["teaching"]


class ReadWriteSerializerMixin:
    """Write with a dedicated serializer, always answer with the read shape.

    Write serializers accept foreign keys as primary keys; read serializers
    render compact nested summaries. Responding to writes with the read
    serializer keeps list, detail and write payloads identical.
    """

    read_serializer_class = None
    write_serializer_class = None

    def get_serializer_class(self):
        if getattr(self, "action", None) in ("create", "update", "partial_update"):
            return self.write_serializer_class or self.read_serializer_class
        return self.read_serializer_class

    def get_read_serializer(self, instance):
        return self.read_serializer_class(
            instance, context=self.get_serializer_context()
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        read_data = self.get_read_serializer(serializer.instance).data
        return Response(
            read_data,
            status=status.HTTP_201_CREATED,
            headers=self.get_success_headers(read_data),
        )

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        instance = serializer.instance
        if getattr(instance, "_prefetched_objects_cache", None):
            instance._prefetched_objects_cache = {}
        return Response(self.get_read_serializer(instance).data)


class DepartmentScopedQuerysetMixin:
    """Scope list/detail to the caller's department unless they have college-wide access.

    ``department_lookup`` is the ORM path from the model to its owning
    department; the department resource itself uses ``"pk"``. Users without a
    department get an empty queryset (fail closed).
    """

    department_lookup = "department"

    def get_queryset(self):
        queryset = super().get_queryset()
        user = getattr(self.request, "user", None)
        if user is None or not user.is_authenticated:
            return queryset.none()
        if user.has_cross_department_access:
            return queryset
        if user.department_id is None:
            return queryset.none()
        return queryset.filter(**{self.department_lookup: user.department_id})


class AcademicStructureViewSet(ReadWriteSerializerMixin, viewsets.ModelViewSet):
    """Base viewset for academic structure resources.

    ``http_method_names`` excludes ``delete``, so the detail route still exists
    but answers HTTP 405 Method Not Allowed as required for Phase 2.
    """

    http_method_names = ["get", "post", "put", "patch", "head", "options"]
    permission_classes = [IsAuthenticated]


@extend_schema(tags=ACADEMIC_TAGS)
class CollegeViewSet(AcademicStructureViewSet):
    """Colleges: readable by any authenticated user, writable by college admins."""

    queryset = College.objects.all()
    read_serializer_class = CollegeSerializer
    permission_classes = [IsAuthenticated, IsCollegeAdminOrReadOnly]


@extend_schema(tags=ACADEMIC_TAGS)
class AcademicYearViewSet(AcademicStructureViewSet):
    """Academic years: college-wide, writable by college admins."""

    queryset = AcademicYear.objects.all()
    read_serializer_class = AcademicYearSerializer
    permission_classes = [IsAuthenticated, IsCollegeAdminOrReadOnly]


@extend_schema(tags=ACADEMIC_TAGS)
class SemesterViewSet(AcademicStructureViewSet):
    """Semesters: college-wide, writable by college admins."""

    queryset = Semester.objects.select_related("academic_year")
    read_serializer_class = SemesterSerializer
    write_serializer_class = SemesterWriteSerializer
    permission_classes = [IsAuthenticated, IsCollegeAdminOrReadOnly]


@extend_schema(tags=ACADEMIC_TAGS)
class DepartmentViewSet(DepartmentScopedQuerysetMixin, AcademicStructureViewSet):
    """Departments: readers see their own department, college admins see all."""

    queryset = Department.objects.select_related("college")
    read_serializer_class = DepartmentSerializer
    write_serializer_class = DepartmentWriteSerializer
    permission_classes = [IsAuthenticated, CanManageDepartments]
    # A department's own primary key is its department scope.
    department_lookup = "pk"


@extend_schema(tags=ACADEMIC_TAGS)
class StudyProgramViewSet(DepartmentScopedQuerysetMixin, AcademicStructureViewSet):
    """Study programs, scoped to the caller's department."""

    queryset = StudyProgram.objects.select_related("department")
    read_serializer_class = StudyProgramSerializer
    write_serializer_class = StudyProgramWriteSerializer
    permission_classes = [IsAuthenticated, IsDepartmentScopedWriter]
    department_lookup = "department"


@extend_schema(tags=ACADEMIC_TAGS)
class StudyStageViewSet(DepartmentScopedQuerysetMixin, AcademicStructureViewSet):
    """Study stages, scoped through their program's department."""

    queryset = StudyStage.objects.select_related("program", "program__department")
    read_serializer_class = StudyStageSerializer
    write_serializer_class = StudyStageWriteSerializer
    permission_classes = [IsAuthenticated, IsDepartmentScopedWriter]
    department_lookup = "program__department"


@extend_schema(tags=ACADEMIC_TAGS)
class StudentGroupViewSet(DepartmentScopedQuerysetMixin, AcademicStructureViewSet):
    """Student groups, scoped through stage -> program -> department."""

    queryset = StudentGroup.objects.select_related(
        "stage", "stage__program", "parent_group"
    )
    read_serializer_class = StudentGroupSerializer
    write_serializer_class = StudentGroupWriteSerializer
    permission_classes = [IsAuthenticated, IsDepartmentScopedWriter]
    department_lookup = "stage__program__department"


class DepartmentVisibilityQuerysetMixin:
    """Scope reads to the caller's department, including joint participation.

    Phase 2 resources are scoped by an exact department match. Phase 3 records
    can also be visible to a second department whose students attend a joint
    component, so each viewset supplies its own ``visibility_filter``.
    """

    def visibility_filter(self, user):
        """Return the ``Q`` object describing the records visible to ``user``."""
        raise NotImplementedError

    def get_queryset(self):
        queryset = super().get_queryset()
        user = getattr(self.request, "user", None)
        if user is None or not user.is_authenticated:
            return queryset.none()
        if user.has_cross_department_access:
            return queryset
        if user.department_id is None:
            return queryset.none()
        return queryset.filter(self.visibility_filter(user)).distinct()


@extend_schema(tags=TEACHING_TAGS)
class CourseViewSet(DepartmentVisibilityQuerysetMixin, AcademicStructureViewSet):
    """Courses owned by a department, readable by departments that teach them."""

    queryset = Course.objects.select_related("department")
    read_serializer_class = CourseSerializer
    write_serializer_class = CourseWriteSerializer
    permission_classes = [IsAuthenticated, IsDepartmentScopedManager]
    management_department_lookups = ("department",)

    def visibility_filter(self, user):
        return visible_courses_filter(user)


@extend_schema(tags=TEACHING_TAGS)
class CourseOfferingViewSet(DepartmentVisibilityQuerysetMixin, AcademicStructureViewSet):
    """Course offerings managed by a department or attended by its students."""

    queryset = CourseOffering.objects.select_related(
        "course",
        "semester",
        "semester__academic_year",
        "managing_department",
    ).prefetch_related(
        Prefetch(
            "components",
            queryset=TeachingComponent.objects.filter(is_active=True),
            to_attr="active_components",
        )
    )
    read_serializer_class = CourseOfferingSerializer
    write_serializer_class = CourseOfferingWriteSerializer
    permission_classes = [IsAuthenticated, IsDepartmentScopedManager]
    management_department_lookups = ("managing_department", "course__department")

    def visibility_filter(self, user):
        return visible_offerings_filter(user)


@extend_schema(tags=TEACHING_TAGS)
class TeachingComponentViewSet(
    DepartmentVisibilityQuerysetMixin, AcademicStructureViewSet
):
    """Teaching components; only the managing department may write them."""

    queryset = TeachingComponent.objects.select_related(
        "offering",
        "offering__course",
        "offering__managing_department",
        "offering__semester",
        "offering__semester__academic_year",
    )
    read_serializer_class = TeachingComponentSerializer
    write_serializer_class = TeachingComponentWriteSerializer
    permission_classes = [IsAuthenticated, IsDepartmentScopedManager]
    management_department_lookups = ("offering__managing_department",)

    def visibility_filter(self, user):
        return visible_components_filter(user)


@extend_schema(tags=TEACHING_TAGS)
class TeachingComponentGroupViewSet(
    DepartmentVisibilityQuerysetMixin, AcademicStructureViewSet
):
    """Component/group relations, including combined and joint teaching.

    Writes require both the component's managing department and the student
    group's department to be the writer's own department.
    """

    queryset = TeachingComponentGroup.objects.select_related(
        "teaching_component",
        "teaching_component__offering",
        "teaching_component__offering__course",
        "student_group",
        "student_group__stage",
    )
    read_serializer_class = TeachingComponentGroupSerializer
    write_serializer_class = TeachingComponentGroupWriteSerializer
    permission_classes = [IsAuthenticated, IsDepartmentScopedManager]
    management_department_lookups = (
        "teaching_component__offering__managing_department",
        "student_group__stage__program__department",
    )

    def visibility_filter(self, user):
        return visible_group_links_filter(user)
