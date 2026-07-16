from __future__ import annotations

import pytest

from app.services.nonphysical_execution import (
    NonphysicalAdmissionError,
    require_explicit_nonphysical_admission,
    resolve_execution_provenance,
)


def test_evidence_only_and_synthetic_hil_share_nonphysical_safety_invariants() -> None:
    evidence = resolve_execution_provenance("evidence_only", robot_id="tb3_1")
    synthetic = resolve_execution_provenance("synthetic_hil", robot_id="tb3_1")

    for provenance in (evidence, synthetic):
        assert provenance.evidence_class == "nonphysical"
        assert provenance.physical_lift_verified is False
        assert provenance.inventory_mutation_allowed is False

    assert evidence.base_motion == "manual_checkpoint"
    assert evidence.lift_backend == "manual_fixture"
    assert synthetic.base_motion == "live"
    assert synthetic.lift_backend == "virtual"


def test_nonphysical_modes_are_tb1_only_and_require_explicit_admission() -> None:
    with pytest.raises(NonphysicalAdmissionError, match="tb3_1"):
        resolve_execution_provenance("evidence_only", robot_id="tb3_2")
    with pytest.raises(NonphysicalAdmissionError, match="explicit"):
        require_explicit_nonphysical_admission(
            "synthetic_hil", robot_id="tb3_1", admitted=False
        )


def test_physical_mode_keeps_existing_live_semantics() -> None:
    provenance = require_explicit_nonphysical_admission(
        "physical", robot_id="tb3_2", admitted=False
    )
    assert provenance.execution_class == "live"
    assert provenance.evidence_class == "physical"
    assert provenance.inventory_mutation_allowed is True
