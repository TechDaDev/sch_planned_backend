"""Applying a validated semester teaching plan.

The write step is deliberately dull: the validation pass already turned every row into an
unsaved model instance, so applying means saving them in dependency order and counting
what was written. Nothing is validated again here, nothing is overwritten, and no
``update`` or ``delete`` is ever issued - an import creates rows and links, and fails
whole if any of them fails.

Callers wrap this in one transaction, so a failure half way through leaves the database
exactly as it was.
"""

from __future__ import annotations

from scheduling.services.imports.validator import ValidatedPlan


def write_plan(plan: ValidatedPlan) -> dict[str, int]:
    """Save every record of a validated plan and return the created counts.

    Order is the dependency order: courses before offerings, groups before links,
    components before assignments and room requirements, and room requirements before
    their capability requirements.
    """
    for spec in plan.courses:
        spec.instance.save()

    _save_groups(plan)

    for spec in plan.offerings:
        spec.instance.save()
    for spec in plan.components:
        spec.instance.save()
    for spec in plan.component_groups:
        spec.instance.save()
    for spec in plan.assignments:
        spec.instance.save()
    for spec in plan.room_requirements:
        spec.instance.save()
    for spec in plan.capability_requirements:
        spec.instance.save()

    return plan.counts()


def _save_groups(plan: ValidatedPlan) -> None:
    """Save student groups parents first.

    A subgroup stores a foreign key to its parent, so the parent row must exist first.
    A cycle is impossible here - the validator rejects one - so the loop always makes
    progress.
    """
    pending = list(plan.groups)
    workbook_instances = {id(spec.instance) for spec in plan.groups}
    saved: set[int] = set()
    while pending:
        progressed = False
        for spec in list(pending):
            parent = spec.instance.parent_group
            if (
                parent is not None
                and id(parent) in workbook_instances
                and id(parent) not in saved
            ):
                continue
            spec.instance.save()
            saved.add(id(spec.instance))
            pending.remove(spec)
            progressed = True
        if not progressed:  # pragma: no cover - defensive: validation rejects cycles
            raise RuntimeError(
                "The subgroup hierarchy could not be ordered; no records were written."
            )


__all__ = ["write_plan"]
