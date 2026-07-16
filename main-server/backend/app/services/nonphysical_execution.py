"""Explicit execution-mode contract for reusable TB1 nonphysical trials.

This module contains no transport or database code.  Main orchestration and
operator-facing commissioning flows use the same admission/provenance rules so
an evidence-only trial cannot accidentally become physical acceptance.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ExecutionMode = Literal["physical", "evidence_only", "synthetic_hil"]
NONPHYSICAL_MODES = frozenset({"evidence_only", "synthetic_hil"})


class NonphysicalAdmissionError(ValueError):
    """Raised when a test-only execution mode crosses its safety boundary."""


@dataclass(frozen=True)
class ExecutionProvenance:
    execution_mode: ExecutionMode
    execution_class: str
    evidence_class: str
    physical_lift_verified: bool
    inventory_mutation_allowed: bool
    base_motion: str
    lift_backend: str

    def as_dict(self) -> dict[str, object]:
        return {
            "execution_mode": self.execution_mode,
            "execution_class": self.execution_class,
            "evidence_class": self.evidence_class,
            "physical_lift_verified": self.physical_lift_verified,
            "inventory_mutation_allowed": self.inventory_mutation_allowed,
            "base_motion": self.base_motion,
            "lift_backend": self.lift_backend,
        }


def resolve_execution_provenance(mode: str, *, robot_id: str) -> ExecutionProvenance:
    normalized = str(mode or "physical").strip().lower()
    if normalized == "physical":
        return ExecutionProvenance(
            execution_mode="physical",
            execution_class="live",
            evidence_class="physical",
            physical_lift_verified=True,
            inventory_mutation_allowed=True,
            base_motion="live",
            lift_backend="physical",
        )
    if robot_id != "tb3_1":
        raise NonphysicalAdmissionError("nonphysical execution is scoped to tb3_1")
    if normalized == "evidence_only":
        return ExecutionProvenance(
            execution_mode="evidence_only",
            execution_class="evidence_only",
            evidence_class="nonphysical",
            physical_lift_verified=False,
            inventory_mutation_allowed=False,
            base_motion="manual_checkpoint",
            lift_backend="manual_fixture",
        )
    if normalized == "synthetic_hil":
        return ExecutionProvenance(
            execution_mode="synthetic_hil",
            execution_class="synthetic_hil",
            evidence_class="nonphysical",
            physical_lift_verified=False,
            inventory_mutation_allowed=False,
            base_motion="live",
            lift_backend="virtual",
        )
    raise NonphysicalAdmissionError(f"unsupported execution mode: {normalized}")


def require_explicit_nonphysical_admission(
    mode: str,
    *,
    robot_id: str,
    admitted: bool,
) -> ExecutionProvenance:
    provenance = resolve_execution_provenance(mode, robot_id=robot_id)
    if provenance.execution_mode in NONPHYSICAL_MODES and not admitted:
        raise NonphysicalAdmissionError("explicit nonphysical admission is required")
    return provenance
