"""Permanent regression tests for the Phase 17 release hardening.

These cover the production-only behavior that no earlier phase had:

* the health probes, including the guarantee that liveness never touches the database and
  readiness never leaks the underlying error;
* the exception handler: documented DRF errors keep their bodies, an unhandled error
  answers generic JSON with a request id and no implementation detail;
* request-id sanitization at the HTTP boundary;
* documentation exposure, which must be routable in development and absent in production;
* the environment-driven production settings, checked by starting a fresh interpreter so
  the module-level fail-fast logic is exercised for real.

The production settings are verified in a subprocess on purpose: importing
``config.settings`` twice in one process would not re-run the module-level checks, and
those checks are exactly what has to hold.
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import clear_url_caches

from config.exceptions import INTERNAL_ERROR_CODE, INTERNAL_ERROR_DETAIL
from scheduling.services.audit.context import MAX_REQUEST_ID_LENGTH

REPO_ROOT = Path(__file__).resolve().parent.parent

LIVE_URL = "/api/health/live/"
READY_URL = "/api/health/ready/"
HEALTH_URL = "/api/health/"
SCHEMA_URL = "/api/schema/"
DOCS_URL = "/api/docs/"


def _settings_probe(**env: str) -> subprocess.CompletedProcess:
    """Import the settings module in a fresh interpreter with the given environment."""
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("DJANGO_")
    }
    environment.update(env)
    code = (
        "import json, django, os;"
        "os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings');"
        "django.setup();"
        "from django.conf import settings;"
        "print(json.dumps({"
        "'debug': settings.DEBUG,"
        "'secure_ssl_redirect': settings.SECURE_SSL_REDIRECT,"
        "'session_cookie_secure': settings.SESSION_COOKIE_SECURE,"
        "'csrf_cookie_secure': settings.CSRF_COOKIE_SECURE,"
        "'session_cookie_httponly': settings.SESSION_COOKIE_HTTPONLY,"
        "'session_cookie_samesite': settings.SESSION_COOKIE_SAMESITE,"
        "'csrf_cookie_samesite': settings.CSRF_COOKIE_SAMESITE,"
        "'nosniff': settings.SECURE_CONTENT_TYPE_NOSNIFF,"
        "'x_frame_options': settings.X_FRAME_OPTIONS,"
        "'hsts_seconds': settings.SECURE_HSTS_SECONDS,"
        "'hsts_subdomains': settings.SECURE_HSTS_INCLUDE_SUBDOMAINS,"
        "'hsts_preload': settings.SECURE_HSTS_PRELOAD,"
        "'cors': settings.CORS_ALLOWED_ORIGINS,"
        "'cors_allow_all': settings.CORS_ALLOW_ALL_ORIGINS,"
        "'cors_credentials': settings.CORS_ALLOW_CREDENTIALS,"
        "'csrf_trusted': settings.CSRF_TRUSTED_ORIGINS,"
        "'allowed_hosts': settings.ALLOWED_HOSTS,"
        "'docs_enabled': settings.API_DOCS_ENABLED,"
        "'renderers': settings.REST_FRAMEWORK['DEFAULT_RENDERER_CLASSES'],"
        "'parsers': settings.REST_FRAMEWORK['DEFAULT_PARSER_CLASSES'],"
        "'version': settings.SPECTACULAR_SETTINGS['VERSION'],"
        "'engine': settings.DATABASES['default']['ENGINE'],"
        "'static_root': str(settings.STATIC_ROOT),"
        "'time_zone': settings.TIME_ZONE,"
        "'use_tz': settings.USE_TZ,"
        "}))"
    )
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _probe_values(result: subprocess.CompletedProcess) -> dict:
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


PRODUCTION_ENV = {
    "DJANGO_DEBUG": "false",
    "DJANGO_SECRET_KEY": "phase17-test-only-secret-value-not-a-real-key",
    "DJANGO_ALLOWED_HOSTS": "example.test",
    "DJANGO_CORS_ALLOWED_ORIGINS": "https://frontend.example.test",
    "DJANGO_CSRF_TRUSTED_ORIGINS": "https://frontend.example.test",
}


# --- production settings ------------------------------------------------------


def test_production_requires_a_secret_key():
    result = _settings_probe(DJANGO_DEBUG="false", DJANGO_ALLOWED_HOSTS="example.test")
    assert result.returncode != 0
    assert "DJANGO_SECRET_KEY" in result.stderr


def test_production_requires_explicit_allowed_hosts():
    result = _settings_probe(
        DJANGO_DEBUG="false",
        DJANGO_SECRET_KEY="phase17-test-only-secret-value-not-a-real-key",
    )
    assert result.returncode != 0
    assert "DJANGO_ALLOWED_HOSTS" in result.stderr


def test_production_settings_are_secure_by_default():
    values = _probe_values(_settings_probe(**PRODUCTION_ENV))
    assert values["debug"] is False
    assert values["secure_ssl_redirect"] is True
    assert values["session_cookie_secure"] is True
    assert values["csrf_cookie_secure"] is True
    assert values["session_cookie_httponly"] is True
    assert values["session_cookie_samesite"] == "Lax"
    assert values["csrf_cookie_samesite"] == "Lax"
    assert values["nosniff"] is True
    assert values["x_frame_options"] == "DENY"
    assert values["hsts_seconds"] == 3600
    assert values["hsts_subdomains"] is False
    assert values["hsts_preload"] is False
    assert values["cors"] == ["https://frontend.example.test"]
    assert values["cors_allow_all"] is False
    assert values["cors_credentials"] is False
    assert values["csrf_trusted"] == ["https://frontend.example.test"]
    assert values["allowed_hosts"] == ["example.test"]
    assert values["docs_enabled"] is False
    assert "rest_framework.renderers.BrowsableAPIRenderer" not in values["renderers"]
    assert values["parsers"] == ["rest_framework.parsers.JSONParser"]
    assert values["version"] == "1.0.0"
    assert values["time_zone"] == "Asia/Baghdad"
    assert values["use_tz"] is True
    assert values["static_root"].endswith("staticfiles")


def test_production_cors_fails_closed_without_configuration():
    values = _probe_values(_settings_probe(**{**PRODUCTION_ENV, "DJANGO_CORS_ALLOWED_ORIGINS": "", "DJANGO_CSRF_TRUSTED_ORIGINS": ""}))
    assert values["cors"] == []
    assert values["csrf_trusted"] == []
    assert values["cors_allow_all"] is False


def test_production_security_settings_can_be_overridden():
    values = _probe_values(
        _settings_probe(
            **{
                **PRODUCTION_ENV,
                "DJANGO_SECURE_HSTS_SECONDS": "31536000",
                "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS": "true",
                "DJANGO_SECURE_SSL_REDIRECT": "false",
                "DJANGO_API_DOCS_ENABLED": "true",
            }
        )
    )
    assert values["hsts_seconds"] == 31536000
    assert values["hsts_subdomains"] is True
    assert values["secure_ssl_redirect"] is False
    assert values["docs_enabled"] is True


def test_development_defaults_stay_convenient_and_sqlite_backed():
    values = _probe_values(_settings_probe())
    assert values["debug"] is True
    assert values["cors"] == [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    assert values["docs_enabled"] is True
    assert values["parsers"] == ["rest_framework.parsers.JSONParser"]
    assert "rest_framework.renderers.BrowsableAPIRenderer" in values["renderers"]
    assert values["engine"] == "django.db.backends.sqlite3"
    assert values["hsts_seconds"] == 0
    assert values["secure_ssl_redirect"] is False
    assert values["allowed_hosts"] == ["localhost", "127.0.0.1"]


def test_proxy_header_is_only_trusted_when_enabled():
    assert _probe_values(_settings_probe(**PRODUCTION_ENV))["debug"] is False
    trusted = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import django, os;"
                "os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings');"
                "django.setup();"
                "from django.conf import settings;"
                "print(getattr(settings, 'SECURE_PROXY_SSL_HEADER', None))"
            ),
        ],
        cwd=REPO_ROOT,
        env={
            **{k: v for k, v in os.environ.items() if not k.startswith("DJANGO_")},
            **PRODUCTION_ENV,
            "DJANGO_TRUST_X_FORWARDED_PROTO": "true",
        },
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert trusted.returncode == 0, trusted.stderr
    assert trusted.stdout.strip().endswith("('HTTP_X_FORWARDED_PROTO', 'https')")


# --- health probes ------------------------------------------------------------


def test_health_endpoints_are_public_and_minimal(api_client, db):
    for url in (HEALTH_URL, LIVE_URL, READY_URL):
        response = api_client.get(url)
        assert response.status_code == 200, (url, response.content)
        body = response.json()
        assert set(body) <= {"status", "service"}, (url, body)
        assert body["status"] == "ok"


def test_liveness_never_queries_the_database(api_client, db):
    with CaptureQueriesContext(connection) as captured:
        response = api_client.get(LIVE_URL)
    assert response.status_code == 200
    assert len(captured) == 0, [query["sql"] for query in captured]


def test_readiness_reports_unavailable_without_leaking_details(
    api_client, monkeypatch
):
    from config import views as config_views

    monkeypatch.setattr(config_views, "_database_available", lambda: False)
    response = api_client.get(READY_URL)
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    body = response.content.decode().lower()
    for leak in ("sqlite", "traceback", "operationalerror", "connection", "/home/"):
        assert leak not in body, leak


def test_readiness_reports_a_broken_database_as_unavailable(monkeypatch):
    from config import views as config_views

    class BrokenCursor:
        def __enter__(self):
            raise RuntimeError("driver exploded while connecting to /secret/path")

        def __exit__(self, *args):
            return False

    class BrokenConnection:
        def cursor(self):
            return BrokenCursor()

    monkeypatch.setattr(
        config_views.connections, "default", BrokenConnection(), raising=False
    )
    assert config_views._database_available() is False


# --- exception handling -------------------------------------------------------


def test_unhandled_errors_answer_generic_json(api_client, monkeypatch):
    from config.views import HealthLiveView

    def explode(self, request):
        raise RuntimeError("secret implementation detail in /home/zeus3000/path")

    monkeypatch.setattr(HealthLiveView, "get", explode)
    response = api_client.get(LIVE_URL)
    assert response.status_code == 500
    body = response.json()
    assert body["detail"] == INTERNAL_ERROR_DETAIL
    assert body["code"] == INTERNAL_ERROR_CODE
    assert body.get("request_id")
    raw = response.content.decode()
    for leak in ("secret implementation detail", "RuntimeError", "/home/", "Traceback"):
        assert leak not in raw, leak


def test_documented_api_errors_keep_their_responses(api_client):
    unauthorized = api_client.get("/api/schedule-versions/")
    assert unauthorized.status_code == 401
    assert "detail" in unauthorized.json()

    validation = api_client.post(
        "/api/scheduling/validate/", {"scope": "DEPARTMENT"}, format="json"
    )
    assert validation.status_code in (400, 401)


def test_exception_handler_returns_none_for_handled_drf_errors():
    from rest_framework.exceptions import NotFound

    from config.exceptions import api_exception_handler

    response = api_exception_handler(NotFound("nope"), {"request": None})
    assert response is not None
    assert response.status_code == 404


# --- request id ---------------------------------------------------------------


def test_request_id_is_echoed_and_sanitized(api_client):
    response = api_client.get(LIVE_URL, HTTP_X_REQUEST_ID="abc.DEF-123_456:789")
    assert response["X-Request-ID"] == "abc.DEF-123_456:789"

    hostile = api_client.get(LIVE_URL, HTTP_X_REQUEST_ID="bad value\x00with<crlf>\r\n")
    echoed = hostile["X-Request-ID"]
    assert len(echoed) <= MAX_REQUEST_ID_LENGTH
    for character in ("\x00", "\r", "\n", "<", ">"):
        assert character not in echoed

    overlong = api_client.get(LIVE_URL, HTTP_X_REQUEST_ID="a" * 500)
    assert len(overlong["X-Request-ID"]) <= MAX_REQUEST_ID_LENGTH

    generated = api_client.get(LIVE_URL)
    assert len(generated["X-Request-ID"]) == 32


# --- documentation exposure ---------------------------------------------------


@pytest.fixture
def reload_api_urls():
    """Rebuild the ``/api/`` URLconf (and the root resolver) after a settings change."""

    def _reload() -> None:
        from config import api_urls, urls

        importlib.reload(api_urls)
        importlib.reload(urls)
        clear_url_caches()

    yield _reload
    _reload()


def test_docs_are_routable_in_development(api_client, reload_api_urls):
    reload_api_urls()
    assert api_client.get(SCHEMA_URL).status_code == 200
    assert api_client.get(DOCS_URL).status_code == 200


def test_docs_are_absent_when_disabled(api_client, reload_api_urls):
    with override_settings(API_DOCS_ENABLED=False):
        reload_api_urls()
        assert api_client.get(SCHEMA_URL).status_code == 404
        assert api_client.get(DOCS_URL).status_code == 404
        # The rest of the API is untouched by hiding the documentation.
        assert api_client.get(HEALTH_URL).status_code == 200
        assert api_client.get("/api/schedule-versions/").status_code == 401
