"""Work order API adapter over PG MVP tasks (PHASE_59)."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.db.mvp_repositories import (
    DEFAULT_FLOOR,
    MvpCommandRepository,
    MvpEventRepository,
    MvpEvidenceRepository,
    MvpItemRepository,
    MvpLocationRepository,
    MvpTaskRepository,
)
from app.services import evidence_runtime
from app.services import orchestration_state as orch_state
from app.services import tasks as task_service
from app.services.movement import MovementClientError, movement_client
from app.services.work_order_planner import (
    MAX_WORK_ORDER_QUANTITY as MAX_WORK_ORDER_QUANTITY,
)
from app.services.work_order_planner import (
    plan_work_order,
    validated_quantity,
)
from app.services.work_order_planner import (
    preview_work_order as preview_work_order,
)


def create_work_order(conn, payload: dict[str, Any], callback_base_url: str | None = None) -> dict[str, Any]:
    item_code = payload["item_code"]
    operation = payload["operation"]
    quantity = validated_quantity(int(payload["quantity"]))
    auto_start = bool(payload.get("auto_start", False))
    execution_mode = str(payload.get("execution_mode") or "physical")
    admit_nonphysical = bool(payload.get("admit_nonphysical", False))
    if execution_mode == "synthetic_hil":
        from app.core.config import settings

        if not settings.nonphysical_task_admission_enabled:
            raise HTTPException(status_code=409, detail="nonphysical_task_admission_disabled")

    if not MvpItemRepository(conn).exists(item_code):
        raise HTTPException(status_code=404, detail="item not found")

    # Preview is deliberately optimistic.  Creation serializes and revalidates
    # the selected resource so two PostgreSQL connections cannot both turn the
    # same preview into an active task claim.
    plan = _claim_work_order_plan(conn, payload)
    planned_entries = plan["_planned_entries"]

    batch_id = None
    task_ids: list[int] = []
    for entry in planned_entries:
        slot = entry["slot"]
        floor = int(entry["plan_summary"].get("floor") or DEFAULT_FLOOR)
        task_id = _create_mvp_task(
            conn, operation, item_code, slot, floor, entry["plan_summary"], payload,
        )
        task_ids.append(task_id)
        batch_id = batch_id or task_id

    MvpEventRepository(conn).append(
        event_type="WORK_ORDER_CREATED",
        message=f"work order batch {batch_id} created ({operation} {item_code} x{quantity})",
        payload={"order_id": batch_id, "task_ids": task_ids, **payload},
    )

    robot_id = payload.get("robot_id")
    if robot_id:
        for task_id in task_ids:
            task_service.assign_work_order_robot(
                conn,
                task_id,
                str(robot_id),
                execution_mode=execution_mode,
            )
    elif auto_start:
        task_service.auto_assign(conn, source="work_order")

    mission_results: list[dict[str, Any]] = []
    start_failed: list[dict[str, Any]] = []
    if auto_start:
        for task_id in task_ids:
            task = MvpTaskRepository(conn).get(task_id)
            if task and task.get("status") == task_service.ASSIGNED_STATUS:
                try:
                    mission_results.append(task_service.start_task_mission(
                        conn,
                        task_id,
                        callback_base_url=callback_base_url,
                        source="work_order",
                        execution_mode=execution_mode,
                        admit_nonphysical=admit_nonphysical,
                    ))
                except HTTPException as exc:
                    if execution_mode == "synthetic_hil":
                        # The requested backend is part of this work order's
                        # meaning. Roll the transaction back rather than leave
                        # an ambiguous physical-looking queued task behind.
                        raise
                    start_failed.append({"task_id": task_id, "detail": exc.detail})

    order = _response(conn, batch_id or task_ids[0], mission_results=mission_results or None)
    if start_failed:
        order["start_failed"] = start_failed
    return order


def _claim_work_order_plan(conn, payload: dict[str, Any]) -> dict[str, Any]:
    """Lock, then re-plan until the locked resource remains the chosen one."""
    operation = str(payload["operation"])
    item_code = str(payload["item_code"])
    tasks = MvpTaskRepository(conn)
    # A contender can first choose a now-stale auto slot.  After waiting on its
    # lock it re-plans, locks the new resource, and only creates once stable.
    # Each loop holds only transaction-scoped advisory locks, so a maximum of
    # one lock per candidate resource is acquired.
    for _ in range(32):
        plan = plan_work_order(conn, payload)
        entry = plan["_planned_entries"][0]
        slot_id = str(entry["slot"]["slot_id"])
        floor = int(entry["plan_summary"].get("floor") or DEFAULT_FLOOR)
        tasks.lock_work_order_resource(operation, item_code, slot_id, floor)
        current = plan_work_order(conn, payload)
        current_entry = current["_planned_entries"][0]
        current_slot = str(current_entry["slot"]["slot_id"])
        current_floor = int(current_entry["plan_summary"].get("floor") or DEFAULT_FLOOR)
        if (current_slot, current_floor) == (slot_id, floor):
            return current
    raise RuntimeError("work_order_resource_claim_retry_exhausted")


def get_work_order(conn, order_id: int) -> dict[str, Any]:
    return _response(conn, order_id)


def cancel_work_order(conn, order_id: int) -> dict[str, Any]:
    task = MvpTaskRepository(conn).get(order_id)
    if not task or task.get("task_type") not in {"INBOUND", "OUTBOUND"}:
        raise HTTPException(status_code=404, detail="work order not found")
    status = str(task.get("status") or "").upper()
    if status in {"RUNNING", "IN_PROGRESS"}:
        raise HTTPException(status_code=409, detail="work_order_running_requires_recovery")
    if status not in {"CREATED", "QUEUED", "ASSIGNED"}:
        raise HTTPException(status_code=409, detail=f"work_order_not_cancellable(status={status})")
    task_service.cancel_task(conn, order_id, source="work_order")
    return _response(conn, order_id)


def _stop_response(
    order_id: int,
    *,
    command_id: str | None,
    cargo_state: str,
    business_completed: bool,
    accepted: bool,
    status: str = "CANCEL_REQUESTED",
) -> dict[str, Any]:
    return {
        "order_id": order_id,
        "task_id": order_id,
        "status": status,
        "accepted": accepted,
        "command_id": command_id,
        "cargo_state": cargo_state,
        "business_completed": business_completed,
    }


def _locked_orchestration(
    conn,
    order_id: int,
    fallback: dict[str, Any],
) -> dict[str, Any]:
    """Read the latest orchestration under the shared task claim lock."""
    if getattr(conn, "is_postgres", False) is True:
        locked = MvpEvidenceRepository(conn).lock_orchestration(order_id)
        return locked if isinstance(locked, dict) else {}
    return fallback


def _manual_stop_from_durable_hold(
    conn,
    order_id: int,
    *,
    robot_id: str,
    command_id: str | None,
    business_completed: bool,
    fallback: dict[str, Any],
) -> dict[str, Any]:
    movement: dict[str, Any] = {}
    error: str | None = None
    try:
        response = movement_client.manual_stop(robot_id, {"robot_name": robot_id})
        if isinstance(response, dict):
            movement = response
    except Exception as exc:
        error = str(exc)

    confirmed = movement.get("accepted") is True and movement.get("stopped") is True
    MvpEventRepository(conn).append(
        event_type="WORK_ORDER_MANUAL_STOP_RESULT",
        task_id=order_id,
        robot_id=robot_id,
        message=f"work order {order_id} manual stop {'confirmed' if confirmed else 'unconfirmed'}",
        payload={
            "command_id": command_id,
            "cargo_state": "UNKNOWN",
            "confirmed": confirmed,
            "state": movement.get("state"),
            "error": error,
        },
    )
    if confirmed:
        latest = _locked_orchestration(conn, order_id, fallback)
        if orch_state.normalize_phase(latest.get("phase")) == orch_state.PHASE_AWAITING_OPERATOR:
            recovery = dict(latest.get("recovery") or {})
            if recovery.get("reason") == "operator_safe_stop_no_active_command":
                recovery["stop_confirmed"] = True
                latest["recovery"] = recovery
                evidence_runtime.save_orchestration(conn, order_id, latest)
    conn.commit()
    return _stop_response(
        order_id,
        command_id=command_id,
        cargo_state="UNKNOWN",
        business_completed=business_completed,
        accepted=confirmed,
        status="AWAITING_OPERATOR",
    )


def _request_recovery_work_order_stop(
    conn,
    order_id: int,
    *,
    robot_id: str,
    orch: dict[str, Any],
    business_completed: bool,
) -> dict[str, Any]:
    """Cancel the recovery command itself, never the interrupted old step."""
    from app.services import task_recovery as recovery_service

    recovery = dict(orch.get("recovery") or {})
    command_id = str(recovery.get("active_command_id") or "")
    if not command_id:
        raise HTTPException(status_code=409, detail="work_order_has_no_active_command")
    with recovery_service.recovery_command_guard(
        conn,
        order_id,
        command_id,
        fallback=orch,
    ) as locked_orch:
        if locked_orch is None:
            latest = evidence_runtime.attach_orchestration(MvpTaskRepository(conn).get(order_id), conn)
            latest_orch = (latest.get("preset_snapshot") or {}).get("_orchestration") if latest else None
            if (
                isinstance(latest_orch, dict)
                and orch_state.normalize_phase(latest_orch.get("phase"))
                == orch_state.PHASE_AWAITING_OPERATOR
            ):
                return _stop_response(
                    order_id,
                    command_id=command_id,
                    cargo_state="UNKNOWN",
                    business_completed=business_completed,
                    accepted=True,
                    status="AWAITING_OPERATOR",
                )
            raise HTTPException(status_code=409, detail="recovery command no longer active")
        recovery = dict(locked_orch.get("recovery") or {})
        if recovery.get("stop_requested") is not True:
            recovery["stop_requested"] = True
            recovery["cargo_state"] = "UNKNOWN"
            locked_orch["recovery"] = recovery
            evidence_runtime.save_orchestration(conn, order_id, locked_orch)
            MvpEventRepository(conn).append(
                event_type="WORK_ORDER_STOP_REQUESTED",
                task_id=order_id,
                robot_id=robot_id,
                message=f"work order {order_id} recovery stop requested",
                payload={"command_id": command_id, "cargo_state": "UNKNOWN", "recovery": True},
            )
            conn.commit()

    try:
        movement = movement_client.cancel_command(robot_id, command_id)
    except MovementClientError:
        return _stop_response(
            order_id,
            command_id=command_id,
            cargo_state="UNKNOWN",
            business_completed=business_completed,
            accepted=False,
        )

    state = str(movement.get("state") or "").upper()
    if state == "CANCELED":
        state = "CANCELLED"
    if not movement.get("accepted", True) and not state:
        state = "STOP_UNCONFIRMED"
    if state in recovery_service.RECOVERY_TERMINAL_EVENTS:
        recovery_service.handle_recovery_command_event(
            conn,
            order_id,
            {"command_id": command_id, "state": state},
            source="operator_safe_stop",
        )

    latest = evidence_runtime.attach_orchestration(MvpTaskRepository(conn).get(order_id), conn)
    latest_orch = (latest.get("preset_snapshot") or {}).get("_orchestration") if latest else None
    if (
        isinstance(latest_orch, dict)
        and orch_state.normalize_phase(latest_orch.get("phase"))
        == orch_state.PHASE_AWAITING_OPERATOR
    ):
        return _stop_response(
            order_id,
            command_id=command_id,
            cargo_state="UNKNOWN",
            business_completed=business_completed,
            accepted=state != "STOP_UNCONFIRMED",
            status="AWAITING_OPERATOR",
        )
    return _stop_response(
        order_id,
        command_id=command_id,
        cargo_state="UNKNOWN",
        business_completed=business_completed,
        accepted=movement.get("accepted", True) is True,
    )


def request_work_order_stop(conn, order_id: int) -> dict[str, Any]:
    """Cancel the active signed Nav command and persist recovery context once."""
    tasks = MvpTaskRepository(conn)
    task = evidence_runtime.attach_orchestration(tasks.get(order_id), conn)
    if not task or task.get("task_type") not in {"INBOUND", "OUTBOUND"}:
        raise HTTPException(status_code=404, detail="work order not found")
    fallback = (task.get("preset_snapshot") or {}).get("_orchestration") or {}
    orch = _locked_orchestration(conn, order_id, fallback)
    if getattr(conn, "is_postgres", False) is True:
        task = tasks.get(order_id)
    if not task or task.get("task_type") not in {"INBOUND", "OUTBOUND"}:
        raise HTTPException(status_code=404, detail="work order not found")
    if str(task.get("status") or "").upper() != "RUNNING":
        raise HTTPException(status_code=409, detail="work_order_stop_requires_running")

    robot_id = task.get("assigned_robot_id") or task.get("robot_id")
    if not robot_id:
        raise HTTPException(status_code=409, detail="work_order_has_no_active_command")
    robot_id = str(robot_id)
    business_completed = bool(orch.get("business_completed"))
    if orch_state.normalize_phase(orch.get("phase")) == orch_state.PHASE_RECOVERY_RUNNING:
        return _request_recovery_work_order_stop(
            conn,
            order_id,
            robot_id=robot_id,
            orch=orch,
            business_completed=business_completed,
        )
    steps = orch_state.get_steps(orch)
    step_index = orch_state.get_step_index(orch)
    step = steps[step_index] if 0 <= step_index < len(steps) else {}
    command_id = step.get("command_id")
    command_id_text = str(command_id) if command_id else None
    recovery = dict(orch.get("recovery") or {})
    phase = orch_state.normalize_phase(orch.get("phase"))
    if phase == orch_state.PHASE_AWAITING_OPERATOR:
        if (
            recovery.get("reason") != "operator_safe_stop_no_active_command"
            or recovery.get("stop_confirmed") is True
        ):
            conn.rollback()
            return _stop_response(
                order_id,
                command_id=command_id_text,
                cargo_state=str(recovery.get("cargo_state") or "UNKNOWN"),
                business_completed=business_completed,
                accepted=recovery.get("stop_confirmed") is not False,
                status="AWAITING_OPERATOR",
            )
        conn.commit()
        return _manual_stop_from_durable_hold(
            conn,
            order_id,
            robot_id=robot_id,
            command_id=command_id_text,
            business_completed=business_completed,
            fallback=orch,
        )

    step_status = str(step.get("status") or "").upper()
    exact_command_active = bool(command_id_text) and step_status in {
        "DISPATCHING",
        "DISPATCHED",
        "RUNNING",
    }
    if not exact_command_active:
        orch_state.set_phase(orch, orch_state.PHASE_AWAITING_OPERATOR)
        orch["recovery"] = {
            "reason": "operator_safe_stop_no_active_command",
            "robot_id": robot_id,
            "cargo_state": "UNKNOWN",
            "stop_requested": True,
            "stop_confirmed": False,
        }
        evidence_runtime.save_orchestration(conn, order_id, orch)
        MvpEventRepository(conn).append(
            event_type=orch_state.EVENT_AWAITING_OPERATOR,
            task_id=order_id,
            robot_id=robot_id,
            message=f"work order {order_id} held before manual stop",
            payload={"cargo_state": "UNKNOWN", "command_id": command_id_text},
        )
        conn.commit()
        return _manual_stop_from_durable_hold(
            conn,
            order_id,
            robot_id=robot_id,
            command_id=command_id_text,
            business_completed=business_completed,
            fallback=orch,
        )

    previous = orch.get("stop_request") or {}
    stop_intent_persisted = (
        orch_state.normalize_phase(orch.get("phase")) == orch_state.PHASE_CANCEL_REQUESTED
        and str(previous.get("command_id") or "") == str(command_id)
    )
    if stop_intent_persisted:
        cargo_state = str(previous.get("cargo_state") or "UNKNOWN")
        business_completed = bool(previous.get("business_completed"))
    else:
        transfer_action = str(
            step.get("transfer_action") or (step.get("params") or {}).get("action") or ""
        ).strip().lower()
        transfer_in_progress = (
            str(step.get("kind") or "").lower() == "dock_transfer"
            and transfer_action in {"load", "unload"}
        )
        if transfer_in_progress:
            cargo_state = "UNKNOWN"
        elif business_completed:
            cargo_state = "EMPTY"
        else:
            cargo_state = orch_state.cargo_state_after_steps(steps)

        # Persist and commit stop intent before the synchronous Nav call. Nav
        # may deliver its terminal callback before returning the HTTP response;
        # that callback must observe the cargo policy it completes. A later
        # request reissues the same idempotent cancel if this process dies after
        # the commit but before delivery.
        orch_state.set_phase(orch, orch_state.PHASE_CANCEL_REQUESTED)
        orch["stop_request"] = {
            "command_id": str(command_id),
            "robot_id": str(robot_id),
            "cargo_state": cargo_state,
            "business_completed": business_completed,
            "accepted": True,
        }
        evidence_runtime.save_orchestration(conn, order_id, orch)
        MvpEventRepository(conn).append(
            event_type="WORK_ORDER_STOP_REQUESTED",
            task_id=order_id,
            robot_id=str(robot_id),
            message=f"work order {order_id} safe stop requested",
            payload={"command_id": command_id, "cargo_state": cargo_state},
        )
        conn.commit()

    try:
        response = movement_client.cancel_command(robot_id, str(command_id))
        movement = response if isinstance(response, dict) else {}
    except Exception as exc:
        movement = {
            "accepted": False,
            "state": "STOP_UNCONFIRMED",
            "error": str(exc),
        }

    movement_state = str(movement.get("state") or "").upper()
    accepted = movement.get("accepted") is True or movement_state in {
        "CANCELED",
        "CANCELLED",
        "STOPPED",
    }
    if not accepted or movement_state == "STOP_UNCONFIRMED":
        latest_orch = _locked_orchestration(conn, order_id, orch)
        latest_phase = orch_state.normalize_phase(latest_orch.get("phase"))

        # A synchronous callback may already have completed the stop. Never
        # overwrite that newer terminal/hold state with this request's stale
        # CANCEL_REQUESTED snapshot.
        if latest_phase != orch_state.PHASE_CANCEL_REQUESTED:
            recovery = latest_orch.get("recovery") or {}
            conn.rollback()
            return _stop_response(
                order_id,
                command_id=str(command_id),
                cargo_state=str(recovery.get("cargo_state") or cargo_state),
                business_completed=business_completed,
                accepted=latest_phase != orch_state.PHASE_AWAITING_OPERATOR,
                status=(
                    "AWAITING_OPERATOR"
                    if latest_phase == orch_state.PHASE_AWAITING_OPERATOR
                    else "CANCEL_REQUESTED"
                ),
            )

        orch_state.set_phase(latest_orch, orch_state.PHASE_AWAITING_OPERATOR)
        latest_orch["recovery"] = {
            "reason": "physical_stop_unconfirmed",
            "robot_id": str(robot_id),
            "cargo_state": "UNKNOWN",
            "command_id": str(command_id),
        }
        evidence_runtime.save_orchestration(conn, order_id, latest_orch)
        MvpEventRepository(conn).append(
            event_type=orch_state.EVENT_AWAITING_OPERATOR,
            task_id=order_id,
            robot_id=str(robot_id),
            message=f"work order {order_id} physical stop unconfirmed",
            payload={
                "command_id": command_id,
                "cargo_state": "UNKNOWN",
                "movement": movement,
            },
        )
        conn.commit()

        estop_ok = False
        estop_error: str | None = None
        try:
            response = movement_client.estop(robot_id)
            estop_ok = isinstance(response, dict)
            if not estop_ok:
                estop_error = "invalid_estop_response"
        except Exception as exc:
            estop_error = str(exc)
        MvpEventRepository(conn).append(
            event_type="WORK_ORDER_ESTOP_RESULT",
            task_id=order_id,
            robot_id=robot_id,
            message=f"work order {order_id} fail-closed E-stop {'confirmed' if estop_ok else 'unconfirmed'}",
            payload={
                "command_id": command_id,
                "cargo_state": "UNKNOWN",
                "estop_ok": estop_ok,
                "error": estop_error,
            },
        )
        conn.commit()
        return _stop_response(
            order_id,
            command_id=str(command_id),
            cargo_state="UNKNOWN",
            business_completed=business_completed,
            accepted=False,
            status="AWAITING_OPERATOR",
        )

    latest_task = evidence_runtime.attach_orchestration(tasks.get(order_id), conn)
    latest_orch = (latest_task.get("preset_snapshot") or {}).get("_orchestration") if latest_task else None
    if (
        isinstance(latest_orch, dict)
        and orch_state.normalize_phase(latest_orch.get("phase"))
        == orch_state.PHASE_AWAITING_OPERATOR
    ):
        recovery = latest_orch.get("recovery") or {}
        return _stop_response(
            order_id,
            command_id=str(command_id),
            cargo_state=str(recovery.get("cargo_state") or cargo_state),
            business_completed=business_completed,
            accepted=True,
            status="AWAITING_OPERATOR",
        )

    return _stop_response(
        order_id,
        command_id=str(command_id),
        cargo_state=cargo_state,
        business_completed=business_completed,
        accepted=accepted,
    )


def stop_work_order(conn, order_id: int) -> dict[str, Any]:
    return request_work_order_stop(conn, order_id)


def set_work_order_priority(conn, order_id: int, priority: int) -> dict[str, Any]:
    """대기(CREATED/QUEUED) 작업오더의 우선순위를 조정한다(높을수록 먼저 배정).

    이미 배정·진행·종료된 오더는 순서 조정 의미가 없으므로 거부한다.
    """
    task = MvpTaskRepository(conn).get(order_id)
    if not task or task.get("task_type") not in {"INBOUND", "OUTBOUND"}:
        raise HTTPException(status_code=404, detail="work order not found")
    status = str(task.get("status") or "").upper()
    if status not in {"CREATED", "QUEUED"}:
        raise HTTPException(status_code=409, detail=f"work_order_priority_locked(status={status})")
    priority = max(0, min(int(priority), 1000))
    MvpTaskRepository(conn).set_priority(order_id, priority)
    MvpEventRepository(conn).append(
        event_type="WORK_ORDER_PRIORITY_SET",
        message=f"work order {order_id} priority set to {priority}",
        payload={"order_id": order_id, "priority": priority},
    )
    return _response(conn, order_id)


def list_work_orders(conn, limit: int = 50, status: str | None = None) -> list[dict[str, Any]]:
    tasks = MvpTaskRepository(conn)
    rows = tasks.list(limit=limit * 5)
    inbound_out = [r for r in rows if r.get("task_type") in {"INBOUND", "OUTBOUND"}]
    orders: list[dict[str, Any]] = []
    seen: set[int] = set()
    for row in inbound_out:
        oid = int(row["task_id"])
        if oid in seen:
            continue
        seen.add(oid)
        order = _response(conn, oid)
        if status and order.get("status") != status:
            continue
        orders.append(order)
        if len(orders) >= limit:
            break
    return orders


def _plan_summary_for_task(conn, task_id: int) -> dict[str, Any] | None:
    import json

    row = conn.execute(
        """
        SELECT data_json FROM evidence_events
        WHERE event_type = 'WORK_ORDER_TASK_CREATED'
          AND (task_id = %s OR (data_json->>'task_id')::bigint = %s)
        ORDER BY observed_at DESC LIMIT 1
        """,
        (task_id, task_id),
    ).fetchone()
    if not row:
        return None
    data = row.get("data_json") or {}
    if isinstance(data, str):
        data = json.loads(data)
    summary = data.get("plan_summary")
    return summary if isinstance(summary, dict) else None


def _zones_from_task(conn, task: dict[str, Any], operation: str, plan_summary: dict[str, Any] | None) -> tuple[str, str]:
    if plan_summary:
        src = plan_summary.get("source_zone") or ""
        tgt = plan_summary.get("target_zone") or ""
        if src or tgt:
            return str(src), str(tgt)
    from_id = task.get("from_location_id") or task.get("from_location")
    to_id = task.get("to_location_id") or task.get("to_location")
    if operation == "inbound":
        return str(from_id or ""), str(to_id or task.get("slot_id") or "")
    return str(from_id or task.get("slot_id") or ""), str(to_id or "")


def _active_command_id(conn, task_id: int) -> str | None:
    from app.services import evidence_runtime

    task = evidence_runtime.attach_orchestration(MvpTaskRepository(conn).get(task_id), conn)
    if not task:
        return None
    orch = (task.get("preset_snapshot") or {}).get("_orchestration") or {}
    recovery = orch.get("recovery") or {}
    if str(orch.get("phase") or "") == "RECOVERY_RUNNING" and recovery.get("active_command_id"):
        return str(recovery["active_command_id"])
    from app.services import orchestration_state as orch_state
    steps = orch_state.get_steps(orch)
    step_index = orch_state.get_step_index(orch)
    if 0 <= step_index < len(steps):
        step = steps[step_index]
        if step.get("status") == "dispatched" and step.get("command_id"):
            return str(step["command_id"])
    return None


def _task_progress(
    orch: dict[str, Any],
    recipe_steps: list[dict[str, Any]] | None = None,
    task_phase: str | None = None,
) -> dict[str, Any] | None:
    from app.services import orchestration_state as orch_state

    steps = orch_state.get_steps(orch)
    if not steps and not recipe_steps:
        return None
    current = orch_state.get_step_index(orch)
    projected = []
    for index, step in enumerate(steps):
        projected.append(
            {
                "step_index": index,
                "kind": str(step.get("kind") or "unknown"),
                "label": step.get("label"),
                "status": str(step.get("status") or "pending").upper(),
                "command_id": step.get("command_id"),
                "transfer_action": step.get("transfer_action"),
                "failure_reason": step.get("failure_reason") or step.get("error") or step.get("reason"),
            }
        )
    logical_steps = [
        {
            "step_index": index,
            "kind": str(row.get("command_type") or "unknown"),
            "label": None,
            "status": str(row.get("status") or "PENDING").upper(),
            "command_id": row.get("runtime_command_id"),
            "failure_reason": None,
            "command_def_id": row.get("command_def_id") or row.get("command_id"),
            "sequence_no": row.get("sequence_no"),
            "command_type": row.get("command_type"),
            "target_system": row.get("target_system"),
            "required_evidence_type": row.get("required_evidence_type"),
            "evidence_count": int(row.get("evidence_count") or 0),
            "runtime_command_id": row.get("runtime_command_id"),
            "target": row.get("target"),
            "transfer_action": row.get("transfer_action"),
            "human_hazard_monitor": bool(row.get("human_hazard_monitor")),
            "last_observed_at": row.get("last_observed_at"),
        }
        for index, row in enumerate(recipe_steps or [])
    ]
    current_recipe_index = next(
        (index for index, step in enumerate(logical_steps) if str(step.get("status") or "").upper() != "DONE"),
        max(0, len(logical_steps) - 1),
    )
    recovery = orch.get("recovery") if isinstance(orch.get("recovery"), dict) else {}
    return {
        "phase": str(orch.get("phase") or task_phase or "QUEUED").upper(),
        "current_step_index": max(0, min(current, len(projected) - 1)) if projected else 0,
        "steps": projected,
        "current_recipe_index": current_recipe_index,
        "recipe_steps": logical_steps,
        "recovery_reason": recovery.get("reason"),
        "cargo_state": recovery.get("cargo_state"),
    }


def _response(conn, order_id: int, mission_results: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    task = MvpTaskRepository(conn).get(order_id)
    if not task or task.get("task_type") not in {"INBOUND", "OUTBOUND"}:
        raise HTTPException(status_code=404, detail="work order not found")
    operation = task["task_type"].lower()
    status = _map_order_status(task["status"])
    plan_summary = _plan_summary_for_task(conn, order_id)
    attached = evidence_runtime.attach_orchestration(task, conn) or task
    orch = (attached.get("preset_snapshot") or {}).get("_orchestration") or {}
    execution_mode = str((orch.get("provenance") or {}).get("execution_mode") or "physical")
    business_completed = bool(orch.get("business_completed"))
    return_status = orch.get("return_status")
    parking_error = orch.get("parking_error")
    source_zone, target_zone = _zones_from_task(conn, task, operation, plan_summary)
    task_floor = int((task.get("to_floor") if operation == "inbound" else task.get("from_floor")) or DEFAULT_FLOOR)
    item_code = str(task.get("item_code") or task.get("item_id") or "")
    item = MvpItemRepository(conn).get(item_code) if item_code else None
    wo_task = {
        "order_id": order_id,
        "task_id": order_id,
        "slot_id": task.get("slot_id"),
        "floor": task_floor,
        "quantity": int(task.get("quantity") or 1),
        "priority": int(task.get("priority") or 0),
        "status": task.get("status"),
        "assigned_robot_id": task.get("assigned_robot_id"),
        "command_id": _active_command_id(conn, order_id),
        "slot_label": (plan_summary or {}).get("slot_label") or task.get("slot_id"),
        "source_zone": source_zone,
        "target_zone": target_zone,
        "selection_reason": (plan_summary or {}).get("selection_reason"),
        "available_qty_at_plan": (plan_summary or {}).get("available_qty_at_plan"),
        "business_completed": business_completed,
        "return_status": return_status,
        "parking_error": parking_error,
        "progress": _task_progress(
            orch,
            MvpCommandRepository(conn).progress_for_task(order_id, str(task["task_type"])),
            task_phase=str(task.get("status") or "QUEUED"),
        ),
    }
    order = {
        "order_id": order_id,
        "operation": operation,
        "item_code": item_code,
        "item_name": item.get("item_name") if item else None,
        "aruco_marker_id": item.get("aruco_marker_id") if item else None,
        "quantity": int(task.get("quantity") or 1),
        "status": status,
        "created_by": "operator",
        "created_at": task.get("created_at"),
        "tasks": [wo_task],
        "business_completed": business_completed,
        "return_status": return_status,
        "parking_error": parking_error,
        "execution_mode": execution_mode,
    }
    if mission_results is not None:
        order["mission_results"] = mission_results
    return order


def _map_order_status(task_status: str) -> str:
    s = task_status.upper()
    if s in {"COMPLETED", "DONE"}:
        return "DONE"
    if s in {"CREATED", "QUEUED"}:
        return "QUEUED"
    return s


def _create_mvp_task(
    conn,
    operation: str,
    item_code: str,
    slot: dict[str, Any],
    floor: int,
    plan_summary: dict[str, Any],
    payload: dict[str, Any] | None = None,
) -> int:
    locs = MvpLocationRepository(conn)
    payload = payload or {}
    inbound = locs.get_inbound(payload.get("inbound_waypoint_id"))
    outbound = locs.get_outbound(payload.get("outbound_waypoint_id"))
    task_qty = validated_quantity(int(payload.get("quantity") or 1))
    task_type = operation.upper()
    if task_type == "INBOUND":
        from_location_id, to_location_id = inbound["slot_id"], slot["slot_id"]
    else:
        from_location_id, to_location_id = slot["slot_id"], outbound["slot_id"]
    data = {
        "task_type": task_type,
        "status": "QUEUED",
        "item_id": item_code,
        "quantity": task_qty,
        "from_location_id": from_location_id,
        "from_floor": floor,
        "to_location_id": to_location_id,
        "to_floor": floor,
        # priority: 높을수록 먼저 배정(list_assignable이 priority DESC 정렬). 미지정 시 0(보통).
        "priority": int(payload.get("priority") or 0),
    }
    task_id = MvpTaskRepository(conn).create(data)
    MvpEventRepository(conn).append(
        event_type="WORK_ORDER_TASK_CREATED",
        message=f"task {task_id} created ({operation})",
        payload={"order_id": task_id, "task_id": task_id, "operation": operation, "item_code": item_code, "slot_id": slot["slot_id"], "floor": floor, "plan_summary": plan_summary},
    )
    return task_id
