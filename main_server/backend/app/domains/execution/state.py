"""Canonical orchestration state keys and phases."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.models.tasks import RobotTaskStepStatus


class RobotTaskOrchestrationPhase(StrEnum):
    """Main-owned orchestration phase for one robot task."""

    RUNNING = "RUNNING"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    AWAITING_OPERATOR = "AWAITING_OPERATOR"
    RECOVERY_RUNNING = "RECOVERY_RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"
    ABORTED = "ABORTED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


HOLD_PHASES = {RobotTaskOrchestrationPhase.AWAITING_OPERATOR, RobotTaskOrchestrationPhase.RECOVERY_RUNNING}

EVENT_AWAITING_OPERATOR = "TASK_AWAITING_OPERATOR"


@dataclass(slots=True)
class RobotTaskExecutionState:
    """Typed view over the persisted orchestration JSON without changing its schema."""

    data: dict[str, Any]

    @classmethod
    def wrap(cls, value: dict[str, Any] | None) -> "RobotTaskExecutionState":
        return cls(value if isinstance(value, dict) else {})

    @property
    def phase(self) -> str:
        return normalize_phase(str(self.data.get("phase") or ""))

    def transition_to(self, phase: str | RobotTaskOrchestrationPhase) -> str:
        """Set a known orchestration phase while preserving the stored string contract."""

        normalized = normalize_phase(phase)
        try:
            known_phase = RobotTaskOrchestrationPhase(normalized)
        except ValueError as exc:
            raise ValueError(f"unknown robot task orchestration phase: {normalized}") from exc
        self.data["phase"] = known_phase.value
        return known_phase.value

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

    def replace_recovery(self, value: dict[str, Any]) -> dict[str, Any]:
        recovery = dict(value)
        self.recovery = recovery
        return recovery

    def update_recovery(self, **changes: Any) -> dict[str, Any]:
        recovery = dict(self.recovery)
        recovery.update(changes)
        self.recovery = recovery
        return recovery

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

    def advance_step(self) -> int:
        self.step_index += 1
        return self.step_index

    def mark_business_completed(self, *, at_step: int) -> None:
        self.business_completed = True
        self.data["business_completed_at_step"] = int(at_step)
        self.return_status = "RETURNING_HOME"
        self.data["parking_error"] = None

    def to_dict(self) -> dict[str, Any]:
        return self.data


def normalize_phase(phase: str | None) -> str:
    return str(phase or "").upper()


def normalize_robot_task_step_status(status: object) -> str:
    """Normalize persisted legacy lowercase step states at the execution boundary."""

    return str(status or "").upper()


def is_dispatched_robot_task_step(step: dict[str, Any]) -> bool:
    return normalize_robot_task_step_status(step.get("status")) == RobotTaskStepStatus.DISPATCHED


def cargo_state_after_steps(steps: list[dict[str, Any]]) -> str:
    """Derive cargo state from completed transfer steps across old and waypoint flows."""

    loaded = False
    for step in steps:
        if normalize_robot_task_step_status(step.get("status")) != "DONE":
            continue
        action = str(
            step.get("transfer_action")
            or (step.get("params") or {}).get("action")
            or ""
        ).lower()
        if action == "load":
            loaded = True
        elif action == "unload":
            loaded = False
    return "LOADED" if loaded else "EMPTY"


def get_steps(orch: dict[str, Any]) -> list[dict[str, Any]]:
    return RobotTaskExecutionState.wrap(orch).steps


def get_step_index(orch: dict[str, Any]) -> int:
    return RobotTaskExecutionState.wrap(orch).step_index


def set_steps(orch: dict[str, Any], steps: list[dict[str, Any]]) -> None:
    RobotTaskExecutionState.wrap(orch).steps = steps


def set_step_index(orch: dict[str, Any], index: int) -> None:
    RobotTaskExecutionState.wrap(orch).step_index = index


def set_phase(orch: dict[str, Any], phase: str) -> None:
    RobotTaskExecutionState.wrap(orch).transition_to(phase)


def is_hold_phase(phase: str | None) -> bool:
    return (
        normalize_phase(phase) in {RobotTaskOrchestrationPhase.AWAITING_OPERATOR, RobotTaskOrchestrationPhase.RECOVERY_RUNNING} or str(phase or "") in HOLD_PHASES
    )


def new_orchestration(steps: list[dict[str, Any]], *, callback_base_url: str | None = None) -> dict[str, Any]:
    return {
        "steps": steps,
        "step_index": 0,
        "phase": RobotTaskOrchestrationPhase.RUNNING,
        "callback_base_url": callback_base_url,
    }
