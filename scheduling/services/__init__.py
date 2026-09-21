"""Service layer for the scheduling app.

Services hold the domain logic that API views must not contain: a view validates
its input, authorizes the caller, calls a service and serializes the result.

Two service packages live here:

* ``scheduling.services.validation`` - Phase 7's pre-scheduling validator, which
  inspects stored data and reports whether timetable generation is ready to begin.
  It never writes, and it reads the ORM.
* ``scheduling.services.solver`` - Phase 8's CP-SAT engine, which solves an already
  prepared discrete problem and imports neither Django nor DRF.

The convenience re-exports below are resolved lazily (PEP 562) on purpose. An
eager import would pull the validation package - and therefore Django - into the
import path of the solver package, which must stay importable on its own::

    from scheduling.services.solver import solve          # no Django required
    from scheduling.services import PreSchedulingValidator  # resolved on demand
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

#: Names that used to be re-exported eagerly, mapped to their real location.
_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "IssueCode": ("scheduling.services.validation", "IssueCode"),
    "PreSchedulingValidator": (
        "scheduling.services.validation",
        "PreSchedulingValidator",
    ),
    "Severity": ("scheduling.services.validation", "Severity"),
    "TimeGrid": ("scheduling.services.validation", "TimeGrid"),
    "ValidationIssue": ("scheduling.services.validation", "ValidationIssue"),
    "ValidationResult": ("scheduling.services.validation", "ValidationResult"),
    "ValidationScope": ("scheduling.services.validation", "ValidationScope"),
    "ValidationSummary": ("scheduling.services.validation", "ValidationSummary"),
    "hours_to_minutes": ("scheduling.services.validation", "hours_to_minutes"),
    "max_contiguous_minutes": (
        "scheduling.services.validation",
        "max_contiguous_minutes",
    ),
}


def __getattr__(name: str) -> Any:
    """Resolve a re-exported validation symbol on first use."""
    try:
        module_name, attribute = _LAZY_EXPORTS[name]
    except KeyError:  # pragma: no cover - only hit for genuinely unknown names
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_EXPORTS))


__all__ = sorted(_LAZY_EXPORTS)
