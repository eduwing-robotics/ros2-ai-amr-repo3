"""Main-owned, inventory-neutral evidence commissioning for TB1 fixtures."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.core.config import settings
from app.db.repo_bridge import evidence_repo, task_repo
from app.services import lift_load_evidence
from app.services import orchestration_state as orch_state
from app.services.nonphysical_execution import require_explicit_nonphysical_admission
from app.services.vision_proxy import post_lift_load_evaluate

ALLOWED_ZONES = {
    "inbound_static_item_zone",
    "outbound_static_item_zone",
    "storage_upper_static_item_zone",
    "storage_lower_static_item_zone",
}


def _request(task: dict[str, Any], scenario: dict[str, Any], step: dict[str, Any]) -> dict[str, object]:
    return {
        "source": settings.lift_load_evidence_source or "global_cam_01",
        "robot_id": "tb3_1",
        "task_id": task["task_id"],
        "command_id": f"evidence-only-{task['task_id']}-{step['operation'].lower()}",
        "operation": step["operation"],
        "expected_item_id": scenario["expected_item_id"],
        "expected_marker_id": scenario["expected_marker_id"],
        "expected_item_count": 1,
        "vision_zone_id": step["vision_zone_id"],
        "burst_frames": settings.lift_load_burst_frames,
        "min_pass_frames": settings.lift_load_min_pass_frames,
        "sample_interval_ms": settings.lift_load_sample_interval_ms,
        "max_frame_age_s": settings.lift_load_max_frame_age_s,
    }


def _evaluate(conn, task: dict[str, Any], orchestration: dict[str, Any]) -> dict[str, Any]:
    index = orch_state.get_step_index(orchestration)
    steps = orch_state.get_steps(orchestration)
    step = steps[index]
    request = _request(task, orchestration["scenario"], step)
    response = post_lift_load_evaluate(request)
    errors = lift_load_evidence._gate_binding_errors(response, request)
    event = response.get("event") if isinstance(response.get("event"), dict) else {}
    data = event.get("data_json") if isinstance(event.get("data_json"), dict) else {}
    approved = response.get("result") == "PASS" and data.get("command_satisfying") is True and not errors
    decision = {
        "approved": approved,
        "result": response.get("result"),
        "reason_code": response.get("reason_code"),
        "command_satisfying": bool(data.get("command_satisfying")),
        "binding_errors": errors,
        "event_id": event.get("event_id"),
    }
    step["decision"] = decision
    if approved:
        step["status"] = "DONE"
        index += 1
        if index >= len(steps):
            orch_state.set_phase(orchestration, orch_state.PHASE_DONE)
            task_repo(conn).set_status(task["task_id"], "DONE")
        else:
            orch_state.set_step_index(orchestration, index)
            orch_state.set_phase(orchestration, orch_state.PHASE_AWAITING_OPERATOR)
            orchestration["hold_reason"] = "manual_fixture_transfer_required"
            orchestration["recovery"] = {
                "reason": "manual_fixture_transfer_required",
                "gate_decision": decision,
            }
    else:
        orch_state.set_phase(orchestration, orch_state.PHASE_AWAITING_OPERATOR)
        orchestration["hold_reason"] = "evidence_not_approved"
        orchestration["recovery"] = {
            "reason": "evidence_not_approved",
            "gate_decision": decision,
        }
    orch_state.set_steps(orchestration, steps)
    evidence_repo(conn).save_orchestration(task["task_id"], orchestration)
    return {"task_id": task["task_id"], "phase": orchestration["phase"], "step_index": orch_state.get_step_index(orchestration), "decision": decision, "provenance": orchestration["provenance"]}


def start(conn, task_id: int, body: dict[str, Any]) -> dict[str, Any]:
    task = task_repo(conn).get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    if task["status"] not in {"CREATED", "QUEUED"}:
        raise HTTPException(status_code=409, detail=f"task is not startable (status={task['status']})")
    try:
        marker = int(body["expected_marker_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="expected_marker_id must be an integer") from exc
    if not 20 <= marker <= 49:
        raise HTTPException(status_code=422, detail="expected_marker_id must be between 20 and 49")
    source_zone = str(body.get("source_vision_zone_id") or "")
    destination_zone = str(body.get("destination_vision_zone_id") or "")
    if source_zone not in ALLOWED_ZONES or destination_zone not in ALLOWED_ZONES:
        raise HTTPException(status_code=422, detail="unsupported evidence ZoneROI")
    try:
        provenance = require_explicit_nonphysical_admission(
            "evidence_only",
            robot_id=str(body.get("robot_id") or "tb3_1"),
            admitted=bool(body.get("admit_nonphysical") and settings.nonphysical_task_admission_enabled),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    scenario = {
        "expected_item_id": str(body.get("expected_item_id") or f"ARUCO-{marker}"),
        "expected_marker_id": marker,
        "source_vision_zone_id": source_zone,
        "destination_vision_zone_id": destination_zone,
    }
    steps = [
        {"kind": "evidence_checkpoint", "operation": "PICK_UP", "vision_zone_id": source_zone, "status": "pending"},
        {"kind": "manual_fixture_transfer", "status": "pending"},
        {"kind": "evidence_checkpoint", "operation": "PRE_DROP_OFF", "vision_zone_id": destination_zone, "status": "pending"},
    ]
    orchestration = orch_state.new_orchestration(steps)
    orchestration.update({"provenance": provenance.as_dict(), "scenario": scenario})
    task_repo(conn).assign(task_id, "tb3_1", "RUNNING")
    evidence_repo(conn).save_orchestration(task_id, orchestration)
    task = task_repo(conn).get(task_id) or {**task, "assigned_robot_id": "tb3_1", "status": "RUNNING"}
    return _evaluate(conn, task, orchestration)


def continue_run(conn, task_id: int) -> dict[str, Any]:
    task = task_repo(conn).get(task_id)
    orchestration = evidence_repo(conn).get_orchestration(task_id)
    if not task or not orchestration or orchestration.get("provenance", {}).get("execution_mode") != "evidence_only":
        raise HTTPException(status_code=404, detail="evidence-only task run not found")
    if orch_state.normalize_phase(orchestration.get("phase")) == orch_state.PHASE_DONE:
        return {"task_id": task_id, "phase": orch_state.PHASE_DONE, "provenance": orchestration["provenance"]}
    steps = orch_state.get_steps(orchestration)
    index = orch_state.get_step_index(orchestration)
    if steps[index]["kind"] == "manual_fixture_transfer":
        steps[index]["status"] = "DONE"
        index += 1
        orch_state.set_steps(orchestration, steps)
        orch_state.set_step_index(orchestration, index)
        orch_state.set_phase(orchestration, orch_state.PHASE_RUNNING)
    return _evaluate(conn, task, orchestration)


def cancel_run(conn, task_id: int) -> dict[str, Any]:
    task = task_repo(conn).get(task_id)
    orchestration = evidence_repo(conn).get_orchestration(task_id)
    if not task or not orchestration or orchestration.get("provenance", {}).get("execution_mode") != "evidence_only":
        raise HTTPException(status_code=404, detail="evidence-only task run not found")
    if orch_state.normalize_phase(orchestration.get("phase")) == orch_state.PHASE_DONE:
        raise HTTPException(status_code=409, detail="evidence-only task already done")
    orch_state.set_phase(orchestration, orch_state.PHASE_ABORTED)
    orchestration["recovery"] = {"reason": "operator_cancelled_nonphysical_test"}
    evidence_repo(conn).save_orchestration(task_id, orchestration)
    task_repo(conn).set_status(task_id, "CANCELLED", clear_robot=True)
    return {"task_id": task_id, "phase": orch_state.PHASE_ABORTED, "status": "CANCELLED", "provenance": orchestration["provenance"]}
