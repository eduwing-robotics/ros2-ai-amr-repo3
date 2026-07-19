# 기능 책임: Scenario callback의 순서·완료 gate 순수 판정을 검증한다. 비책임: DB·재고·실장비 동작.
from app.domains.execution import steps, transitions


def test_contract_rejects_step_code_index_mismatch_and_backward_completion() -> None:
    step = {
        "scenario_progress": {"last_completed_step_index": 4},
        "route_timeline": steps.business_timeline(),
    }
    errors = transitions.scenario_event_contract_errors(
        step,
        {
            "contract_version": "1.0",
            "event": "STEP_COMPLETED",
            "current_step_index": 6,
            "current_step_code": "LOAD",
            "last_completed_step_index": 3,
        },
    )

    assert errors == ["current_step", "last_completed_step_index"]


def test_done_gate_requires_empty_parked_released_and_safe_state() -> None:
    progress = {
        "current_step_code": "PARK",
        "last_completed_step_index": 8,
        "business_completed": True,
        "cargo_state": "EMPTY",
        "authority_owner": "MAIN",
        "authority_released": True,
        "navigator_status": "IDLE",
        "is_emergency": False,
    }

    assert transitions.scenario_done_gate_errors(progress) == []
    assert transitions.scenario_done_gate_errors({**progress, "authority_released": False}) == [
        "authority_released"
    ]


def test_progress_snapshot_ignores_fields_outside_movement_contract() -> None:
    orchestration = {}
    step = {"scenario_progress": {"cargo_state": "EMPTY"}}

    result = transitions.update_scenario_progress(
        orchestration,
        step,
        {"cargo_state": "LOADED", "current_step_code": "LOAD", "item_code": "must-not-copy"},
    )

    assert result == {"cargo_state": "LOADED", "current_step_code": "LOAD"}
    assert orchestration["scenario_progress"] is result
