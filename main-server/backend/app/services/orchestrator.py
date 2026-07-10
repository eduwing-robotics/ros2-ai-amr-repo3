"""콜백 구동 task 오케스트레이터 (PHASE_12-C, PHASE_62/63 DBML).

steps/step_index 상태는 evidence_events ORCHESTRATION_STATE에 저장한다.
(구 legs/cursor 키는 읽기 폴백·이중 기록으로 호환.)
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from typing import Any

from fastapi import HTTPException

from app.db.mvp.evidence import MvpEvidenceRepository
from app.db.repo_bridge import event_repo, evidence_repo, robot_repo, task_repo, waypoint_repo
from app.models.schemas import RobotCommandRequest
from app.services import evidence_runtime, field_bindings, lift_load_evidence, person_hazard
from app.services import orchestration_state as orch_state
from app.services import robot_commands as command_service
from app.services import tasks as task_service
from app.services.movement import MovementClientError, movement_client
from app.services.robot_commands import normalize_dock_transfer_params

logger = logging.getLogger(__name__)

TERMINAL_STEP_STATES = {"DONE", "FAILED", "ABORTED", "CANCELLED"}
ORCHESTRATION_HOLD_PHASES = orch_state.HOLD_PHASES
PHYSICAL_MOTION_KINDS = frozenset({"move_to_point", "aruco_align", "dock_transfer", "leave_dock"})

# Backward-compatible aliases
TERMINAL_LEG_STATES = TERMINAL_STEP_STATES

# The repository performs the real PostgreSQL cross-worker lock.  This lock is
# its deterministic in-process equivalent for test/fake repositories.
_transition_locks: defaultdict[int, threading.RLock] = defaultdict(threading.RLock)


def _claim_terminal_transition(conn, task_id: int, command_id: str, event_name: str) -> dict[str, Any] | None:
    repo = evidence_repo(conn)
    if isinstance(repo, MvpEvidenceRepository) and getattr(conn, "is_postgres", False) is True:
        return repo.claim_terminal_transition(task_id, command_id, event_name)
    fake_claim = None if isinstance(repo, MvpEvidenceRepository) else getattr(repo, "claim_terminal_transition", None)
    if callable(fake_claim) and repo.__class__.__module__ != "unittest.mock":
        return fake_claim(task_id, command_id, event_name)
    with _transition_locks[task_id]:
        task = _task(conn, task_id)
        if not task:
            return None
        orch = _orch(task)
        steps = orch_state.get_steps(orch)
        index = orch_state.get_step_index(orch)
        if index >= len(steps):
            return None
        step = steps[index]
        if str(step.get("command_id") or "") != command_id or step.get("status") not in {"dispatched", "RUNNING"}:
            return None
        step["status"] = "transition_claimed"
        step["transition_id"] = f"{task_id}:{index}:{command_id}:{event_name}"
        orch_state.set_phase(orch, orch_state.PHASE_ADVANCING)
        orch_state.set_steps(orch, steps)
        evidence_runtime.save_orchestration(conn, task_id, orch)
        return orch


def _claim_step_dispatch(conn, task_id: int, robot_id: str, step_index: int) -> dict[str, Any] | None:
    repo = evidence_repo(conn)
    task = _task(conn, task_id)
    if not task:
        return None
    orch = _orch(task)
    steps = orch_state.get_steps(orch)
    if step_index >= len(steps):
        return None
    command_id = orch_state.deterministic_step_command_id(task_id, robot_id, steps[step_index], step_index)
    if isinstance(repo, MvpEvidenceRepository) and getattr(conn, "is_postgres", False) is True:
        return repo.claim_step_dispatch(task_id, step_index, command_id)
    fake_claim = None if isinstance(repo, MvpEvidenceRepository) else getattr(repo, "claim_step_dispatch", None)
    if callable(fake_claim) and repo.__class__.__module__ != "unittest.mock":
        return fake_claim(task_id, step_index, command_id)
    with _transition_locks[task_id]:
        task = _task(conn, task_id)
        if not task:
            return None
        orch = _orch(task)
        steps = orch_state.get_steps(orch)
        if orch_state.get_step_index(orch) != step_index or step_index >= len(steps):
            return None
        step = steps[step_index]
        if step.get("status") == "dispatched" or step.get("status") not in {"pending", "dispatching"}:
            return None
        if step.get("command_id") and step["command_id"] != command_id:
            return None
        step["command_id"] = command_id
        step["status"] = "dispatching"
        orch_state.set_steps(orch, steps)
        evidence_runtime.save_orchestration(conn, task_id, orch)
        return orch


def _step_done_events(kind: str) -> set[str]:
    if kind == "move_to_point":
        return {"ARRIVED", "DONE"}
    return {"DONE"}


_leg_done_events = _step_done_events


def _task(conn, task_id: int) -> dict[str, Any] | None:
    return evidence_runtime.attach_orchestration(task_repo(conn).get(task_id), conn)


def plan_command_steps(conn, scenario: dict[str, Any], task_id: int, robot_id: str) -> list[dict[str, Any]]:
    map_id = scenario.get("map_id")
    if not map_id:
        raise HTTPException(status_code=409, detail="scenario missing map_id")
    waypoints = {w["waypoint_id"]: w for w in waypoint_repo(conn).list(map_id=map_id)}
    raw_steps = sorted(scenario.get("steps") or [], key=lambda item: item.get("seq", 0))
    if not raw_steps:
        raise HTTPException(status_code=409, detail="scenario has no steps")

    steps: list[dict[str, Any]] = []
    for idx, step in enumerate(raw_steps, start=1):
        action_type = str(step.get("action_type") or "move")
        if action_type == "dock_transfer":
            params = dict(step.get("params") or {})
            normalized = normalize_dock_transfer_params(
                params,
                status_code=409,
                detail_prefix=f"dock_transfer step {idx}",
            )
            steps.append({
                "seq": idx,
                "kind": "dock_transfer",
                "label": step.get("name") or f"dock-{idx}",
                "params": normalized,
                "status": "pending",
                "command_id": None,
            })
            continue

        if action_type in ("leave_dock", "aruco_align"):
            steps.append({
                "seq": idx,
                "kind": action_type,
                "label": step.get("name") or f"{action_type}-{idx}",
                "params": dict(step.get("params") or {}),
                "status": "pending",
                "command_id": None,
            })
            continue

        waypoint = waypoints.get(step.get("waypoint_id"))
        if waypoint:
            params = {
                "map_id": map_id,
                "x": waypoint["x"],
                "y": waypoint["y"],
                "yaw": waypoint.get("yaw", 0.0),
            }
            label = step.get("name") or waypoint.get("name") or f"step-{idx}"
        elif step.get("x") is not None and step.get("y") is not None:
            params = {
                "map_id": map_id,
                "x": float(step["x"]),
                "y": float(step["y"]),
                "yaw": float(step.get("yaw", 0.0)),
            }
            label = step.get("name") or f"step-{idx}"
        else:
            raise HTTPException(status_code=409, detail=f"step {idx} has no pose")
        steps.append({
            "seq": idx,
            "kind": "move_to_point",
            "label": label,
            "params": params,
            "status": "pending",
            "command_id": None,
        })
    return steps


# Backward-compatible alias
unfold_legs = plan_command_steps


def _orch(task: dict[str, Any]) -> dict[str, Any]:
    snap = task.get("preset_snapshot") or {}
    orch = snap.get("_orchestration")
    if not orch:
        raise HTTPException(status_code=409, detail="task has no orchestration state")
    return orch


# commands 시드는 move/dock 5-step만 정의하므로, leave_dock·aruco_align 같은
# 시드 외 step를 건너뛴 위치로 step_index를 환산해야 seq 매핑이 어긋나지 않는다.
_SEEDED_STEP_KINDS = {"move_to_point", "dock_transfer"}
_SEEDED_LEG_KINDS = _SEEDED_STEP_KINDS


def _seed_step_index(steps: list[dict[str, Any]], step_index: int) -> int:
    return sum(1 for step in steps[:step_index] if str(step.get("kind")) in _SEEDED_STEP_KINDS)


_seed_cursor = _seed_step_index


def start_task_orchestration(conn, task_id: int, callback_base_url: str | None = None, source: str = "operator") -> dict[str, Any]:
    tasks = task_repo(conn)
    task = _task(conn, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    if task["status"] != task_service.ASSIGNED_STATUS:
        raise HTTPException(status_code=409, detail=f"task is not assigned (status={task['status']})")
    robot_id = task.get("assigned_robot_id")
    if not robot_id:
        raise HTTPException(status_code=409, detail="task has no assigned robot")

    # The callback destination is a Main-server capability.  Ignore callers that
    # attempt to supply one so orchestration cannot become an SSRF deputy.
    del callback_base_url
    from app.api.helpers import callback_base_url as configured_callback_base_url

    scenario = evidence_runtime.build_scenario_from_task(conn, task)
    scenario_map_id = str(scenario.get("map_id") or "")
    if not scenario_map_id:
        raise HTTPException(status_code=409, detail="scenario missing map_id")
    task_type = str(task.get("task_type") or "").upper()
    if task_type in {"INBOUND", "OUTBOUND", "CHARGE"}:
        location_ids = [
            str(location_id)
            for location_id in (task.get("from_location_id"), task.get("to_location_id"))
            if location_id
        ]
        if task_type in {"INBOUND", "OUTBOUND"}:
            location_ids.append("HOME_01")
        field_bindings.assert_locations_match_map(location_ids, scenario_map_id)
    field_bindings.assert_field_dispatch_commissioned(task_type, scenario_map_id)
    # Bound field coordinates may only be sent in the exact map frame reported
    # by the assigned robot.  Never compatibility-remap a task scenario.
    field_bindings.assert_robot_live_map(str(robot_id), scenario_map_id)
    steps = plan_command_steps(conn, scenario, task_id, robot_id)
    orchestration = orch_state.new_orchestration(steps, callback_base_url=configured_callback_base_url())
    evidence_runtime.save_orchestration(conn, task_id, orchestration)

    tasks.set_status(task_id, "RUNNING")
    robot_repo(conn).set_task(robot_id, "RUNNING", task_id)
    tasks.add_history(task_id, task_service.ASSIGNED_STATUS, "RUNNING", "orchestrator started", source)

    command_id = dispatch_current_step(conn, task_id)
    event_repo(conn).append(
        event_type="TASK_ORCHESTRATION_STARTED",
        robot_id=robot_id,
        message=f"task {task_id} step0 dispatched ({command_id})",
        payload={"task_id": task_id, "command_id": command_id, "step_count": len(steps), "leg_count": len(steps)},
    )
    return {
        "task": _task(conn, task_id),
        "robot_id": robot_id,
        "command_id": command_id,
        "step_count": len(steps),
        "leg_count": len(steps),
    }



def _dock_action(step: dict[str, Any]) -> str:
    params = step.get("params") if isinstance(step.get("params"), dict) else {}
    return str(params.get("action") or "").strip().lower()


def _step_for_evidence(step: dict[str, Any], *, operation_override: str | None = None) -> dict[str, Any]:
    evidence_step = dict(step)
    params = dict(step.get("params") or {})
    if operation_override:
        params["evidence_operation"] = operation_override
    evidence_step["params"] = params
    return evidence_step


def _movement_params(step: dict[str, Any]) -> dict[str, Any]:
    params = dict(step.get("params") or {})
    params.pop("evidence_operation", None)
    return params


def _gate_approval_metadata(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        evidence_id = result.get("advisory_evidence_id", result.get("evidence_id"))
        decision = {
            "advisory_evidence_id": evidence_id,
            "evidence_id": evidence_id,
            "result": result.get("result"),
            "reason_code": result.get("reason_code"),
            "command_satisfying": bool(result.get("command_satisfying")),
            "status": result.get("status") or "recorded",
        }
    else:
        decision = {
            "advisory_evidence_id": None,
            "evidence_id": None,
            "result": None,
            "reason_code": "NO_GATE_RESULT",
            "command_satisfying": False,
            "status": "missing",
        }
    approved = (
        str(decision.get("status") or "recorded") == "recorded"
        and str(decision.get("result") or "").upper() == "PASS"
        and decision.get("command_satisfying") is True
    )
    decision["decision"] = "PASS" if approved else "HOLD"
    decision["approved"] = approved
    return decision


def _record_gate_decision(
    conn,
    *,
    task_id: int,
    command_def_id: int | None,
    robot_id: str | None,
    step_index: int,
    action: str,
    decision: dict[str, Any],
) -> None:
    payload = {
        "step_index": step_index,
        "cursor": step_index,
        "action": action,
        "advisory_evidence_id": decision.get("advisory_evidence_id"),
        "evidence_id": decision.get("evidence_id"),
        "result": decision.get("result"),
        "reason_code": decision.get("reason_code"),
        "command_satisfying": bool(decision.get("command_satisfying")),
        "decision": "PASS" if decision.get("approved") else "HOLD",
        "approved": bool(decision.get("approved")),
        "status": decision.get("status"),
    }
    evidence_runtime.record_movement_evidence(
        conn,
        task_id=task_id,
        command_def_id=command_def_id,
        event_type="LIFT_LOAD_GATE_DECISION",
        source="main_gate_policy",
        trusted=True,
        data_json=payload,
    )
    event_repo(conn).append(
        event_type="LIFT_LOAD_GATE_DECISION",
        task_id=task_id,
        robot_id=robot_id,
        message=f"task {task_id} evidence gate {payload['decision'].lower()} at step {step_index}",
        payload=payload,
    )


def _hold_for_evidence_gate(
    conn,
    *,
    task_id: int,
    task: dict[str, Any],
    orch: dict[str, Any],
    steps: list[dict[str, Any]],
    step_index: int,
    decision: dict[str, Any],
    hold_reason: str = "evidence_gate",
) -> dict[str, Any] | None:
    robot_id = task.get("assigned_robot_id")
    orch_state.set_phase(orch, orch_state.PHASE_AWAITING_OPERATOR)
    orch["recovery"] = {
        "reason": hold_reason,
        "robot_id": robot_id,
        "step_index": step_index,
        "cursor": step_index,
        "gate_decision": decision,
    }
    orch_state.set_steps(orch, steps)
    evidence_runtime.save_orchestration(conn, task_id, orch)
    event_repo(conn).append(
        event_type=orch_state.EVENT_AWAITING_OPERATOR,
        task_id=task_id,
        robot_id=robot_id,
        message=f"task {task_id} held by {hold_reason} at step {step_index}",
        payload={"task_id": task_id, "step_index": step_index, "cursor": step_index, "reason": hold_reason, "gate_decision": decision},
    )
    event_repo(conn).append(
        event_type=orch_state.EVENT_NEEDS_ATTENTION_LEGACY,
        task_id=task_id,
        robot_id=robot_id,
        message=f"task {task_id} held by {hold_reason} at step {step_index}",
        payload={"task_id": task_id, "step_index": step_index, "cursor": step_index, "reason": hold_reason, "gate_decision": decision},
    )
    return _task(conn, task_id)


def _evaluate_gate(
    conn,
    *,
    task: dict[str, Any],
    step: dict[str, Any],
    command_def_id: int | None,
    operation_override: str | None = None,
) -> dict[str, Any]:
    try:
        evidence_step = _step_for_evidence(step, operation_override=operation_override)
        return _gate_approval_metadata(lift_load_evidence.evaluate_and_record(conn, task, evidence_step, command_def_id))
    except Exception as exc:
        logger.exception("lift-load evidence gate failed")
        return _gate_approval_metadata({"result": "ERROR", "reason_code": str(exc), "command_satisfying": False, "status": "error"})

def dispatch_current_step(conn, task_id: int) -> str:
    tasks = task_repo(conn)
    task = _task(conn, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    robot_id = task.get("assigned_robot_id")
    if not robot_id:
        raise HTTPException(status_code=409, detail="task has no robot")

    orch = _orch(task)
    steps = orch_state.get_steps(orch)
    step_index = orch_state.get_step_index(orch)
    if step_index >= len(steps):
        raise HTTPException(status_code=409, detail="no step to dispatch")

    step = steps[step_index]
    task = _task(conn, task_id) or {}
    command_def_id = evidence_runtime.resolve_command_def_id(
        conn, task, _seed_step_index(steps, step_index), str(step.get("kind") or "move_to_point"),
    )
    action = _dock_action(step)
    if str(step.get("kind")) == "dock_transfer" and action == "unload":
        approval = step.get("approval") if isinstance(step.get("approval"), dict) else None
        if approval is None:
            approval = _evaluate_gate(conn, task=task, step=step, command_def_id=command_def_id, operation_override="PRE_DROP_OFF")
            step["approval"] = approval
            _record_gate_decision(
                conn,
                task_id=task_id,
                command_def_id=command_def_id,
                robot_id=robot_id,
                step_index=step_index,
                action="PRE_DROP_OFF",
                decision=approval,
            )
            orch_state.set_steps(orch, steps)
            evidence_runtime.save_orchestration(conn, task_id, orch)
        if not approval.get("approved"):
            _hold_for_evidence_gate(
                conn,
                task_id=task_id,
                task=task,
                orch=orch,
                steps=steps,
                step_index=step_index,
                decision=approval,
            )
            raise HTTPException(status_code=409, detail="evidence_gate_hold")

    # Arm before claiming a dispatch.  A monitor outage must not leave a step
    # durably stuck in ``dispatching`` merely because motion was correctly
    # blocked before the Movement HTTP call.
    intended_command_id = orch_state.deterministic_step_command_id(task_id, str(robot_id), step, step_index)
    if step["kind"] in PHYSICAL_MOTION_KINDS and not person_hazard.arm_physical_motion_monitor(
        conn, robot_id, task_id, intended_command_id, str(step["kind"]),
    ):
        raise HTTPException(status_code=503, detail="person_monitor_unavailable")

    # Durable claim/command identity is committed before Movement HTTP. A retry
    # reuses the same id, while a second worker cannot claim this step.
    claimed_orch = _claim_step_dispatch(conn, task_id, str(robot_id), step_index)
    if claimed_orch is None:
        current = _task(conn, task_id)
        if current:
            current_step = orch_state.get_steps(_orch(current))[step_index]
            return str(current_step.get("command_id") or "")
        return ""
    orch = claimed_orch
    steps = orch_state.get_steps(orch)
    step = steps[step_index]
    command_id = str(step["command_id"])
    payload = RobotCommandRequest(
        robot_id=robot_id,
        kind=step["kind"],
        command_id=command_id,
        dry_run=False,
        params=_movement_params(step),
        task_id=task_id,
    )
    result = command_service.dispatch_robot_command(conn, payload, request=None)
    if not result.accepted:
        step["status"] = "FAILED"
        orch_state.set_phase(orch, orch_state.PHASE_FAILED)
        orch_state.set_steps(orch, steps)
        evidence_runtime.save_orchestration(conn, task_id, orch)
        tasks.set_status(task_id, "FAILED", clear_robot=True)
        robot_repo(conn).set_task(robot_id, "IDLE", None)
        person_hazard.on_robot_task_terminal(robot_id)
        raise HTTPException(status_code=502, detail="step dispatch rejected")

    step["status"] = "dispatched"
    step["command_id"] = result.command_id
    orch_state.set_steps(orch, steps)
    evidence_runtime.save_orchestration(conn, task_id, orch)
    evidence_runtime.record_movement_evidence(
        conn,
        task_id=task_id,
        command_def_id=command_def_id,
        event_type="DISPATCHED",
        data_json={"command_id": result.command_id, "robot_id": robot_id, "kind": step["kind"], "commands_id": command_def_id},
    )
    return result.command_id


dispatch_current_leg = dispatch_current_step


def advance_on_command_event(conn, task_id: int, event: dict[str, Any], source: str = "callback") -> dict[str, Any] | None:
    tasks = task_repo(conn)
    task = _task(conn, task_id)
    if not task or task["status"] not in {"RUNNING"}:
        return None

    orch = _orch(task)
    if orch_state.is_hold_phase(orch.get("phase")):
        return None
    steps = orch_state.get_steps(orch)
    step_index = orch_state.get_step_index(orch)
    if step_index >= len(steps):
        return None

    step = steps[step_index]
    event_name = str(event.get("event") or event.get("state") or event.get("status") or "").upper()
    event_command_id = event.get("command_id")
    if event_command_id and step.get("command_id") and event_command_id != step.get("command_id"):
        return None
    if step.get("status") in TERMINAL_STEP_STATES:
        return None
    terminal_event = event_name in _step_done_events(str(step.get("kind") or "move_to_point")) or event_name in {"FAILED", "ABORTED", "REJECTED"}
    if terminal_event:
        if not event_command_id:
            return None
        claimed_orch = _claim_terminal_transition(conn, task_id, str(event_command_id), event_name)
        if claimed_orch is None:
            return None
        orch = claimed_orch
        steps = orch_state.get_steps(orch)
        step_index = orch_state.get_step_index(orch)
        step = steps[step_index]

    task = _task(conn, task_id) or task
    command_def_id = evidence_runtime.resolve_command_def_id(
        conn, task, _seed_step_index(steps, step_index), str(step.get("kind") or "move_to_point"),
    )
    evidence_runtime.record_movement_evidence(
        conn,
        task_id=task_id,
        command_def_id=command_def_id,
        event_type=event_name or "MOVEMENT_EVENT",
        data_json={"command_id": event_command_id, "event": event, "commands_id": command_def_id},
    )

    if event_name in {"FAILED", "ABORTED", "REJECTED"}:
        step["status"] = event_name
        orch_state.set_steps(orch, steps)
        event_payload = event.get("event") if isinstance(event.get("event"), dict) else event
        reason = str((event_payload or {}).get("reason") or "").lower()
        awaiting_operator = event_name == "ABORTED" and "estop" in reason
        if awaiting_operator:
            orch_state.set_phase(orch, orch_state.PHASE_AWAITING_OPERATOR)
            orch["recovery"] = {
                "reason": "movement_estop",
                "robot_id": task.get("assigned_robot_id"),
            }
            evidence_runtime.save_orchestration(conn, task_id, orch)
            robot_id = task.get("assigned_robot_id")
            event_repo(conn).append(
                event_type=orch_state.EVENT_AWAITING_OPERATOR,
                task_id=task_id,
                robot_id=robot_id,
                message=f"task {task_id} step {step_index} aborted (estop) — recovery required",
                payload={"task_id": task_id, "event": event, "step_index": step_index, "cursor": step_index},
            )
            # Legacy event for older UIs/logs during transition
            event_repo(conn).append(
                event_type=orch_state.EVENT_NEEDS_ATTENTION_LEGACY,
                task_id=task_id,
                robot_id=robot_id,
                message=f"task {task_id} step {step_index} aborted (estop) — recovery required",
                payload={"task_id": task_id, "event": event, "step_index": step_index, "cursor": step_index},
            )
            return _task(conn, task_id)

        orch_state.set_phase(orch, event_name)
        evidence_runtime.save_orchestration(conn, task_id, orch)
        tasks.set_status(task_id, "FAILED", clear_robot=True)
        robot_id = task.get("assigned_robot_id")
        if robot_id:
            robot_repo(conn).set_task(robot_id, "IDLE", None)
            person_hazard.on_robot_task_terminal(str(robot_id))
        event_repo(conn).append(
            event_type=f"TASK_STEP_{event_name}",
            task_id=task_id,
            robot_id=robot_id,
            message=f"task {task_id} step {step_index} {event_name}",
            payload={"task_id": task_id, "event": event, "step_index": step_index, "cursor": step_index},
        )
        return _task(conn, task_id)

    if event_name not in _step_done_events(str(step.get("kind") or "move_to_point")):
        return None

    if str(step.get("kind")) == "dock_transfer":
        action = _dock_action(step)
        if action == "load":
            if (
                str(task.get("task_type") or "").upper() in {"INBOUND", "OUTBOUND"}
                and ("steps" not in orch or "step_index" not in orch)
            ):
                decision = _gate_approval_metadata({
                    "result": "ERROR",
                    "reason_code": "ORCHESTRATION_MIGRATION_REQUIRED",
                    "command_satisfying": False,
                    "status": "migration_required",
                })
                step["approval"] = decision
                _record_gate_decision(
                    conn,
                    task_id=task_id,
                    command_def_id=command_def_id,
                    robot_id=task.get("assigned_robot_id"),
                    step_index=step_index,
                    action="POST_PICK_UP",
                    decision=decision,
                )
                step["status"] = "DONE"
                _hold_for_evidence_gate(
                    conn,
                    task_id=task_id,
                    task=task,
                    orch=orch,
                    steps=steps,
                    step_index=step_index,
                    decision=decision,
                    hold_reason="orchestration_migration_required",
                )
                return _task(conn, task_id)

            decision = _evaluate_gate(conn, task=task, step=step, command_def_id=command_def_id)
            step["approval"] = decision
            _record_gate_decision(
                conn,
                task_id=task_id,
                command_def_id=command_def_id,
                robot_id=task.get("assigned_robot_id"),
                step_index=step_index,
                action="POST_PICK_UP",
                decision=decision,
            )
            if not decision.get("approved"):
                step["status"] = "DONE"
                _hold_for_evidence_gate(
                    conn,
                    task_id=task_id,
                    task=task,
                    orch=orch,
                    steps=steps,
                    step_index=step_index,
                    decision=decision,
                )
                return _task(conn, task_id)
        elif action == "unload":
            # Unload was pre-gated before dispatch; DONE only records progress.
            pass

    step["status"] = "DONE"
    orch_state.set_steps(orch, steps)
    step_index += 1
    orch_state.set_step_index(orch, step_index)
    orch_state.set_phase(orch, orch_state.PHASE_RUNNING)

    if step_index >= len(steps):
        orch_state.set_phase(orch, orch_state.PHASE_DONE)
        evidence_runtime.save_orchestration(conn, task_id, orch)
        finished = task_service.complete_task(conn, task_id, source=source)
        robot_id = task.get("assigned_robot_id")
        if robot_id:
            robot_repo(conn).set_task(str(robot_id), "IDLE", None)
            person_hazard.on_robot_task_terminal(str(robot_id))
        event_repo(conn).append(
            event_type="TASK_ORCHESTRATION_DONE",
            task_id=task_id,
            robot_id=task.get("assigned_robot_id"),
            message=f"task {task_id} all steps done",
            payload={"task_id": task_id},
        )
        return finished

    evidence_runtime.save_orchestration(conn, task_id, orch)
    dispatch_current_step(conn, task_id)
    event_repo(conn).append(
        event_type="TASK_STEP_DONE",
        task_id=task_id,
        robot_id=task.get("assigned_robot_id"),
        message=f"task {task_id} step advanced to {step_index}",
        payload={"task_id": task_id, "step_index": step_index, "cursor": step_index, "event": event},
    )
    return _task(conn, task_id)


advance_task = advance_on_command_event


def handle_command_event(conn, payload: dict[str, Any]) -> dict[str, Any] | None:
    task_id = payload.get("task_id")
    if task_id is None:
        command_id = payload.get("command_id")
        if not command_id:
            return None
        task_id = evidence_repo(conn).find_task_id_by_leg_command(str(command_id))
        if task_id is None:
            return None
    task = _task(conn, int(task_id))
    if task:
        orch = _orch(task)
        recovery = orch.get("recovery") or {}
        if str(orch.get("phase") or "") == orch_state.PHASE_RECOVERY_RUNNING and recovery.get("active_command_id"):
            from app.services import task_recovery as recovery_service
            result = recovery_service.handle_recovery_command_event(conn, int(task_id), payload)
            if result is not None:
                return result
    return advance_on_command_event(conn, int(task_id), payload)


def poll_running_tasks(conn) -> int:
    advanced = 0
    for task in evidence_runtime.list_orchestrated_running(conn):
        orch = (task.get("preset_snapshot") or {}).get("_orchestration") or {}
        if orch_state.is_hold_phase(orch.get("phase")):
            continue
        steps = orch_state.get_steps(orch)
        step_index = orch_state.get_step_index(orch)
        if step_index >= len(steps):
            continue
        step = steps[step_index]
        if step.get("status") == "dispatching":
            # Crash after the durable claim but before HTTP: retry the exact
            # same command id; Movement receives an idempotency key.
            dispatch_current_step(conn, int(task["task_id"]))
            continue
        if step.get("status") not in {"dispatched", "RUNNING"} or not step.get("command_id"):
            continue
        robot_id = task.get("assigned_robot_id")
        if not robot_id:
            continue
        try:
            status = movement_client.command_status(robot_id, str(step["command_id"]))
        except MovementClientError:
            continue
        state = str(status.get("state") or status.get("status") or "").upper()
        done_events = _step_done_events(str(step.get("kind") or "move_to_point"))
        if state in done_events or state in {"FAILED", "ABORTED", "REJECTED"}:
            if advance_on_command_event(
                conn,
                int(task["task_id"]),
                {"command_id": step["command_id"], "state": state},
                source="task_progress_poller",
            ):
                advanced += 1
    return advanced
