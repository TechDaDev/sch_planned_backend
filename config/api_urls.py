"""
URLconf for the ``/api/`` namespace.

Domain apps mount their own URLconfs here as later phases add endpoints.

The two health probes and the three public authentication routes are the only
unauthenticated endpoints. The OpenAPI schema and Swagger UI are registered only when
``API_DOCS_ENABLED`` is true: in production the routes simply do not exist, so a scanner
gets an ordinary ``404`` instead of being told that documentation is switched off.
"""

from django.conf import settings
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from config.views import HealthLiveView, HealthReadyView, HealthView

urlpatterns = [
    path("health/", HealthView.as_view(), name="api-health"),
    path("health/live/", HealthLiveView.as_view(), name="api-health-live"),
    path("health/ready/", HealthReadyView.as_view(), name="api-health-ready"),
    # Application URLconfs.
    path("", include("accounts.urls")),
    path("", include("academics.urls")),
    path("", include("resources.urls")),
    path("", include("scheduling.urls")),
]

if settings.API_DOCS_ENABLED:
    # OpenAPI schema and Swagger UI (development convenience; the ``spectacular``
    # management command works whether or not these routes are registered).
    urlpatterns += [
        path("schema/", SpectacularAPIView.as_view(), name="api-schema"),
        path(
            "docs/",
            SpectacularSwaggerView.as_view(url_name="api-schema"),
            name="api-docs",
        ),
    ]

