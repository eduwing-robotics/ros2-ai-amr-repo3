"""Canonical orchestration state keys and phases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

PHASE_RUNNING = "RUNNING"
PHASE_DONE = "DONE"
PHASE_FAILED = "FAILED"
PHASE_AWAITING_OPERATOR = "AWAITING_OPERATOR"
PHASE_RECOVERY_RUNNING = "RECOVERY_RUNNING"

HOLD_PHASES = {PHASE_AWAITING_OPERATOR, PHASE_RECOVERY_RUNNING}

EVENT_AWAITING_OPERATOR = "TASK_AWAITING_OPERATOR"


@dataclass(slots=True)
class ExecutionState:
    """Typed view over the persisted orchestration JSON without changing its schema."""

    data: dict[str, Any]

    @classmethod
    def wrap(cls, value: dict[str, Any] | None) -> "ExecutionState":
        return cls(value if isinstance(value, dict) else {})

    @property
    def phase(self) -> str:
        return normalize_phase(str(self.data.get("phase") or ""))

    @phase.setter
    def phase(self, value: str) -> None:
        self.data["phase"] = normalize_phase(value)

    @property
    def steps(self) -> list[dict[str, Any]]:
        value = self.data.get("steps")
        return value if isinstance(value, list) else []

    @steps.setter
    def steps(self, value: list[dict[str, Any]]) -> None:
        self.data["steps"] = value

    @property
    def step_index(self) -> int:
        value = self.data.get("step_index")
        return int(value or 0)

    @step_index.setter
    def step_index(self, value: int) -> None:
        self.data["step_index"] = int(value)

    @property
    def recovery(self) -> dict[str, Any]:
        value = self.data.get("recovery")
        return value if isinstance(value, dict) else {}

    @recovery.setter
    def recovery(self, value: dict[str, Any]) -> None:
        self.data["recovery"] = value

    @property
    def business_completed(self) -> bool:
        return bool(self.data.get("business_completed"))

    @business_completed.setter
    def business_completed(self, value: bool) -> None:
        self.data["business_completed"] = bool(value)

    @property
    def return_status(self) -> str | None:
        value = self.data.get("return_status")
        return str(value) if value is not None else None

    @return_status.setter
    def return_status(self, value: str | None) -> None:
        self.data["return_status"] = value

    def to_dict(self) -> dict[str, Any]:
        return self.data


def normalize_phase(phase: str | None) -> str:
    return str(phase or "")


def get_steps(orch: dict[str, Any]) -> list[dict[str, Any]]:
    return ExecutionState.wrap(orch).steps


def get_step_index(orch: dict[str, Any]) -> int:
    return ExecutionState.wrap(orch).step_index


def set_steps(orch: dict[str, Any], steps: list[dict[str, Any]]) -> None:
    ExecutionState.wrap(orch).steps = steps


def set_step_index(orch: dict[str, Any], index: int) -> None:
    ExecutionState.wrap(orch).step_index = index


def set_phase(orch: dict[str, Any], phase: str) -> None:
    ExecutionState.wrap(orch).phase = phase


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
