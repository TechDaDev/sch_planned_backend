"""Deterministic, safe download filenames for the Phase 15 exports.

Filenames are built from identifiers, never from a raw user or model string, and every
component is sanitized before it reaches a header. The result is therefore predictable
for tests and safe for ``Content-Disposition``: no path separators, no quotes, no
non-ASCII bytes that a client would have to guess at.
"""

from __future__ import annotations

import re

#: Characters allowed to survive sanitization.
_ALLOWED = re.compile(r"[^A-Za-z0-9._-]+")

#: Upper bound of a sanitized component, so a header cannot grow without limit.
MAX_COMPONENT_LENGTH = 40

#: Fallback used when sanitization leaves nothing usable.
FALLBACK_COMPONENT = "unknown"

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PDF_MEDIA_TYPE = "application/pdf"


def sanitize_component(value: object) -> str:
    """One header-safe filename component.

    Runs of disallowed characters collapse into a single hyphen, so
    ``"Information Technology"`` becomes ``"Information-Technology"`` and a path
    separator can never survive. An empty result falls back to ``unknown``.
    """
    text = str(value if value is not None else "")
    cleaned = _ALLOWED.sub("-", text).strip("-._")
    if not cleaned:
        return FALLBACK_COMPONENT
    return cleaned[:MAX_COMPONENT_LENGTH]


def manage_version_filename(
    *, semester_id: int, version_number: int, extension: str
) -> str:
    """Filename of a management version export, for example
    ``schedule_semester-3_version-4.xlsx``."""
    return (
        f"schedule_semester-{int(semester_id)}"
        f"_version-{int(version_number)}.{sanitize_extension(extension)}"
    )


def published_filename(
    *, semester_id: int, extension: str, department_code: str | None = None
) -> str:
    """Filename of a published export, optionally naming the scoped department.

    A department-scoped workbook is named after the department so an administrator
    holding several downloads can tell the college-wide export from their own.
    """
    name = f"published_schedule_semester-{int(semester_id)}"
    if department_code:
        name = f"{name}_department-{sanitize_component(department_code)}"
    return f"{name}.{sanitize_extension(extension)}"


def template_filename() -> str:
    """Filename of the semester teaching plan template."""
    return "semester_teaching_plan_template.xlsx"


def sanitize_extension(value: str) -> str:
    """Lower-case alphanumeric extension, defaulting to ``bin``."""
    cleaned = re.sub(r"[^a-z0-9]", "", str(value or "").lower())
    return cleaned or "bin"


def content_disposition(filename: str) -> str:
    """Attachment header value for one already-sanitized filename.

    Quotes and control characters are stripped defensively even though callers build
    the name from identifiers, so a header can never be broken by its own value.
    """
    safe = re.sub(r'[^A-Za-z0-9._-]', "-", str(filename)) or "export"
    return f'attachment; filename="{safe}"'


__all__ = [
    "MAX_COMPONENT_LENGTH",
    "PDF_MEDIA_TYPE",
    "XLSX_MEDIA_TYPE",
    "content_disposition",
    "manage_version_filename",
    "published_filename",
    "sanitize_component",
    "sanitize_extension",
    "template_filename",
]
