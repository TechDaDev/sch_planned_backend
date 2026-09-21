"""Engine-specific exception types.

The engine is a library: application input problems must surface as clear engine
errors, never as raw ``KeyError``/``IndexError``/``AssertionError`` or as opaque
errors raised from inside OR-Tools. Expected input problems therefore raise
:class:`SolverInputError`; unexpected programming errors are deliberately not
caught anywhere in this package.
"""

from __future__ import annotations


class SolverError(Exception):
    """Base class for engine errors."""


class SolverInputError(SolverError, ValueError):
    """The supplied problem or options are not valid engine input.

    Subclasses ``ValueError`` so callers that already treat bad input as a value
    problem (validation layers, adapters) can catch it without importing the
    engine's own type.
    """


__all__ = ["SolverError", "SolverInputError"]
