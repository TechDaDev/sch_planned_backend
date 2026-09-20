"""
URLconf for the ``/api/`` namespace.

Domain apps mount their own URLconfs here as later phases add endpoints.
"""

from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from config.views import HealthView

urlpatterns = [
    path("health/", HealthView.as_view(), name="api-health"),
    # Application URLconfs.
    path("", include("accounts.urls")),
    path("", include("academics.urls")),
    path("", include("resources.urls")),
    # OpenAPI schema and Swagger UI.
    path("schema/", SpectacularAPIView.as_view(), name="api-schema"),
    path(
        "docs/",
        SpectacularSwaggerView.as_view(url_name="api-schema"),
        name="api-docs",
    ),
    # Later phases append their URLconfs here, for example:
    #   path("departments/", include("academics.urls")),
    #   path("courses/", include("academics.urls")),
    #   path("instructors/", include("accounts.urls")),
    #   path("rooms/", include("resources.urls")),
    #   path("schedules/", include("scheduling.urls")),
    #   path("reports/", include("reports.urls")),
]
