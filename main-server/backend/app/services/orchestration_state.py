"""Orchestration state key/phase compatibility (Phase 4c).

Writers use steps / step_index / AWAITING_OPERATOR.
Readers accept legacy legs / cursor / NEEDS_ATTENTION.
"""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

PHASE_RUNNING = "RUNNING"
PHASE_DONE = "DONE"
PHASE_FAILED = "FAILED"
PHASE_AWAITING_OPERATOR = "AWAITING_OPERATOR"
PHASE_RECOVERY_RUNNING = "RECOVERY_RUNNING"
PHASE_ADVANCING = "ADVANCING"

# Legacy aliases accepted on read
PHASE_NEEDS_ATTENTION_LEGACY = "NEEDS_ATTENTION"
_LEGACY_AWAITING = PHASE_NEEDS_ATTENTION_LEGACY

HOLD_PHASES = {PHASE_AWAITING_OPERATOR, PHASE_RECOVERY_RUNNING, _LEGACY_AWAITING}

EVENT_AWAITING_OPERATOR = "TASK_AWAITING_OPERATOR"
# Legacy event type still emitted alongside for older UIs/logs
EVENT_NEEDS_ATTENTION_LEGACY = "TASK_NEEDS_ATTENTION"


def normalize_phase(phase: str | None) -> str:
    value = str(phase or "")
    if value == _LEGACY_AWAITING:
        return PHASE_AWAITING_OPERATOR
    return value


def get_steps(orch: dict[str, Any]) -> list[dict[str, Any]]:
    steps = orch.get("steps")
    if isinstance(steps, list):
        return steps
    legs = orch.get("legs")
    if isinstance(legs, list):
        return legs
    return []


def get_step_index(orch: dict[str, Any]) -> int:
    if "step_index" in orch and orch.get("step_index") is not None:
        return int(orch.get("step_index") or 0)
    return int(orch.get("cursor") or 0)


def set_steps(orch: dict[str, Any], steps: list[dict[str, Any]]) -> None:
    orch["steps"] = steps
    # Keep legacy key in sync during transition so old readers still work.
    orch["legs"] = steps


def set_step_index(orch: dict[str, Any], index: int) -> None:
    orch["step_index"] = int(index)
    orch["cursor"] = int(index)


def set_phase(orch: dict[str, Any], phase: str) -> None:
    normalized = normalize_phase(phase)
    orch["phase"] = normalized
    if normalized == PHASE_AWAITING_OPERATOR:
        # Dual-write legacy for one release window of external consumers.
        pass


def is_hold_phase(phase: str | None) -> bool:
    return normalize_phase(phase) in {PHASE_AWAITING_OPERATOR, PHASE_RECOVERY_RUNNING} or str(phase or "") in HOLD_PHASES


def new_orchestration(steps: list[dict[str, Any]], *, callback_base_url: str | None = None) -> dict[str, Any]:
    return {
        "steps": steps,
        "step_index": 0,
        "legs": steps,
        "cursor": 0,
        "phase": PHASE_RUNNING,
        "callback_base_url": callback_base_url,
    }


def deterministic_step_command_id(task_id: int, robot_id: str, step: dict[str, Any], step_index: int) -> str:
    """Stable command identity for a task step, including retries after a crash."""
    kind = str(step.get("kind") or "move_to_point")
    seq = int(step.get("seq") or step_index + 1)
    fingerprint = sha256(
        json.dumps({"kind": kind, "params": step.get("params") or {}}, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:12]
    return f"task-{task_id}-{robot_id}-{kind}-step-{seq}-{fingerprint}"
