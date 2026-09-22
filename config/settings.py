"""
Django settings for the College Academic Schedule Planner backend.

Phase 0: development-oriented configuration driven by environment variables.
Supported variables are documented in `.env.example`.
"""

from collections.abc import Sequence
from datetime import timedelta
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load optional local overrides from `.env` (never committed).
load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    """Return the environment variable ``name`` parsed as a boolean."""
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: Sequence[str] = ()) -> list[str]:
    """Return the environment variable ``name`` parsed as a comma-separated list."""
    raw_value = os.environ.get(name)
    if not raw_value:
        return list(default)
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def env_int(name: str, default: int) -> int:
    """Return the environment variable ``name`` parsed as an integer."""
    raw_value = os.environ.get(name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        return int(raw_value)
    except ValueError as exc:
        raise ImproperlyConfigured(
            f"{name} must be an integer, got {raw_value!r}."
        ) from exc


# Core security and host configuration.
DEBUG = env_bool("DJANGO_DEBUG", default=True)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is disabled."
        )
    # Development-only fallback so a fresh clone can run without a `.env` file.
    SECRET_KEY = "django-insecure-dev-only-change-me"

# Development answers to the local hostnames; production starts from an empty list and
# refuses to boot until an operator names the hosts explicitly. A silent localhost or
# wildcard default in production is a real vulnerability, not a convenience.
ALLOWED_HOSTS = env_list(
    "DJANGO_ALLOWED_HOSTS", ["localhost", "127.0.0.1"] if DEBUG else []
)
if not DEBUG and not ALLOWED_HOSTS:
    raise ImproperlyConfigured(
        "DJANGO_ALLOWED_HOSTS must list the hostnames this deployment answers to when "
        "DJANGO_DEBUG is disabled."
    )


# Application definition.

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party.
    "rest_framework",
    "corsheaders",
    "drf_spectacular",
    # Local.
    "accounts",
    "academics",
    "resources",
    "scheduling",
    "reports",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "scheduling.middleware.AuditRequestIdMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"


# Database: SQLite for local development. All access goes through the Django ORM.

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}


# Authentication.

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization.

LANGUAGE_CODE = "en-us"

TIME_ZONE = "Asia/Baghdad"

USE_I18N = True

USE_TZ = True


# Static files.

STATIC_URL = "static/"
# Collection target for a future deployment (``manage.py collectstatic``). No CDN,
# WhiteNoise or volume configuration is part of Phase 17.
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# Cross-origin resource sharing (the Next.js frontend runs on port 3000).
#
# Development keeps the local frontend origins for convenience. Production starts from an
# empty list and stays that way until an operator names the origins explicitly: a wildcard
# or a leftover localhost entry in production is a real vulnerability, not a convenience.
CORS_ALLOWED_ORIGINS = env_list(
    "DJANGO_CORS_ALLOWED_ORIGINS",
    ["http://localhost:3000", "http://127.0.0.1:3000"] if DEBUG else [],
)

# ``CORS_ALLOW_ALL_ORIGINS`` stays False in every environment. Authentication is a bearer
# JWT, so credentialed cross-origin cookies are not needed either and stay off.
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOW_CREDENTIALS = False

# Origins allowed to send unsafe cross-site requests (Django admin and any future
# cookie-authenticated form). Fail-closed: empty until deliberately configured.
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", [])


# Django REST Framework.

_rest_framework_renderers = ["rest_framework.renderers.JSONRenderer"]
if DEBUG:
    _rest_framework_renderers.append("rest_framework.renderers.BrowsableAPIRenderer")

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_RENDERER_CLASSES": tuple(_rest_framework_renderers),
    "DEFAULT_PARSER_CLASSES": ("rest_framework.parsers.JSONParser",),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    # Unhandled exceptions answer generic JSON (with the request id) and are logged
    # server-side; every documented DRF error keeps its established behavior.
    "EXCEPTION_HANDLER": "config.exceptions.api_exception_handler",
}


# Phase 17 production hardening.
#
# These settings apply when ``DJANGO_DEBUG=false``. Each one can be overridden through the
# environment, because an operator may legitimately terminate TLS upstream or need a
# different HSTS window; none of them is enabled by guessing.
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", default=not DEBUG)
SESSION_COOKIE_SECURE = env_bool("DJANGO_SESSION_COOKIE_SECURE", default=not DEBUG)
CSRF_COOKIE_SECURE = env_bool("DJANGO_CSRF_COOKIE_SECURE", default=not DEBUG)
SESSION_COOKIE_HTTPONLY = env_bool("DJANGO_SESSION_COOKIE_HTTPONLY", default=True)
SESSION_COOKIE_SAMESITE = os.environ.get("DJANGO_SESSION_COOKIE_SAMESITE", "Lax")
CSRF_COOKIE_SAMESITE = os.environ.get("DJANGO_CSRF_COOKIE_SAMESITE", "Lax")
SECURE_CONTENT_TYPE_NOSNIFF = env_bool(
    "DJANGO_SECURE_CONTENT_TYPE_NOSNIFF", default=True
)
X_FRAME_OPTIONS = os.environ.get("DJANGO_X_FRAME_OPTIONS", "DENY")
SECURE_HSTS_SECONDS = env_int(
    "DJANGO_SECURE_HSTS_SECONDS", 0 if DEBUG else 3600
)
# Subdomains and preload are deliberately off by default: this repository does not know
# which hostnames a deployment will serve, and both are effectively irreversible decisions
# for a browser.
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool(
    "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", default=False
)
SECURE_HSTS_PRELOAD = env_bool("DJANGO_SECURE_HSTS_PRELOAD", default=False)

# Trust ``X-Forwarded-Proto`` only when an operator says a reverse proxy sets it. This is
# generic proxy support, not a deployment-specific configuration.
if env_bool("DJANGO_TRUST_X_FORWARDED_PROTO", default=False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Whether ``/api/schema/`` and ``/api/docs/`` are routable over HTTP. Available in
# development by default, off in production until explicitly enabled. The
# ``spectacular`` management command works either way.
API_DOCS_ENABLED = env_bool("DJANGO_API_DOCS_ENABLED", default=DEBUG)


# Phase 15 exports and imports.

# PDF rendering needs a Unicode-capable TrueType font (Latin plus Arabic). These paths
# are optional: when unset, the exporter searches the common open-source locations and
# refuses the request rather than emitting a PDF whose text it cannot draw.
PDF_EXPORT_FONT_REGULAR = os.environ.get("DJANGO_PDF_EXPORT_FONT_REGULAR", "")
PDF_EXPORT_FONT_BOLD = os.environ.get("DJANGO_PDF_EXPORT_FONT_BOLD", "")

# Bounds of the semester teaching plan upload. They protect the reader from an oversized
# file or a workbook formatted far past its data; a deployment can tighten them.
SEMESTER_PLAN_IMPORT_MAX_BYTES = int(
    os.environ.get("DJANGO_SEMESTER_PLAN_IMPORT_MAX_BYTES", 5 * 1024 * 1024)
)
SEMESTER_PLAN_IMPORT_MAX_SHEET_ROWS = int(
    os.environ.get("DJANGO_SEMESTER_PLAN_IMPORT_MAX_SHEET_ROWS", 2000)
)
SEMESTER_PLAN_IMPORT_MAX_TOTAL_ROWS = int(
    os.environ.get("DJANGO_SEMESTER_PLAN_IMPORT_MAX_TOTAL_ROWS", 10000)
)
SEMESTER_PLAN_IMPORT_MAX_SCANNED_ROWS = int(
    os.environ.get("DJANGO_SEMESTER_PLAN_IMPORT_MAX_SCANNED_ROWS", 20000)
)

# Where ``manage.py create_local_backup`` writes archives. Local development default;
# the directory is created on demand with owner-only permissions and is git-ignored.
LOCAL_BACKUP_DIR = Path(
    os.environ.get("DJANGO_LOCAL_BACKUP_DIR", str(BASE_DIR / "var" / "backups"))
)


# SimpleJWT. Token issuing endpoints are added in a later phase.

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": False,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}


# OpenAPI schema (drf-spectacular).

SPECTACULAR_SETTINGS = {
    "TITLE": "College Academic Schedule Planner API",
    "DESCRIPTION": "Backend API for the College Academic Schedule Planner.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SERVE_PERMISSIONS": ["rest_framework.permissions.AllowAny"],
    "SERVE_AUTHENTICATION": [],
    "TAGS": [
        {"name": "system", "description": "Service health."},
        {"name": "auth", "description": "JWT login and token refresh."},
        {"name": "accounts", "description": "Current user identity."},
        {
            "name": "academics",
            "description": (
                "Academic structure: colleges, departments, academic years, semesters, "
                "study programs, study stages and student groups."
            ),
        },
        {
            "name": "teaching",
            "description": (
                "Teaching structure: courses, course offerings, teaching components "
                "and the student groups attending them."
            ),
        },
        {
            "name": "instructors",
            "description": (
                "Instructor resources: profiles and sharing, weekly availability, "
                "preferences and teaching assignments."
            ),
        },
        {
            "name": "rooms",
            "description": (
                "Room resources: room types and capabilities, rooms and sharing, "
                "availability and teaching-component room requirements."
            ),
        },
        {
            "name": "calendar",
            "description": (
                "Time configuration: working days, teaching periods, breaks and "
                "dated calendar exceptions."
            ),
        },
        {
            "name": "scheduling",
            "description": (
                "Pre-scheduling validation, generation previews and persisted "
                "schedule drafts: readiness checks, department and college-wide "
                "generation, and the read APIs for schedules, versions and entries."
            ),
        },
        {
            "name": "operations",
            "description": (
                "Operational records: the read-only scheduling audit trail. Local "
                "backup and integrity verification are management commands, not HTTP "
                "endpoints."
            ),
        },
    ],
    # Two independent choice sets share the field name ``status`` (the solver's
    # outcome and a schedule version's lifecycle), so the version one is named here
    # instead of leaving drf-spectacular to invent a name for it.
    "ENUM_NAME_OVERRIDES": {
        "ScheduleStatusEnum": "scheduling.models.ScheduleStatus.choices",
    },
}
