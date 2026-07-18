# 기능 책임: Work Order progress·현재 단계 조립을 검증한다. 비책임: 실장비의 물리 동작.
from app.domains.execution.state import RobotTaskExecutionState
from app.domains.work_orders.adapters import robot_task_summary_to_v1
from app.domains.work_orders.assembler import assemble_robot_task_summary


def test_work_order_progress_projects_callback_tracked_steps() -> None:
    execution = RobotTaskExecutionState.wrap(
        {
            "phase": "RUNNING",
            "step_index": 1,
            "steps": [
                {
                    "kind": "leave_dock",
                    "label": "leave_dock",
                    "status": "DONE",
                    "command_id": "cmd-leave",
                    "params": {},
                },
                {
                    "kind": "move_to_point",
                    "label": "scan:INBOUND_02",
                    "status": "DISPATCHED",
                    "command_id": "cmd-load",
                    "transfer_action": "load",
                    "params": {"waypoint_id": "inbound_slot_2_approach"},
                },
                {
                    "kind": "move_to_point",
                    "status": "pending",
                    "command_id": None,
                    "params": {},
                },
            ],
        }
    )
    summary = assemble_robot_task_summary(
        robot_task={
            "task_id": 343,
            "task_type": "INBOUND",
            "quantity": 1,
            "status": "RUNNING",
            "assigned_robot_id": "tb3_2",
        },
        order_id=343,
        execution=execution,
        active_command_id="cmd-load",
        floor=2,
    )

    assert summary.progress is not None
    assert summary.progress.phase == "RUNNING"
    assert summary.progress.current_step_index == 1
    assert [step.status for step in summary.progress.steps] == ["DONE", "DISPATCHED", "PENDING"]
    assert summary.progress.steps[1].transfer_action == "load"

    payload = robot_task_summary_to_v1(summary)
    assert payload["progress"]["steps"][1]["command_id"] == "cmd-load"


def test_work_order_progress_is_absent_before_orchestration_starts() -> None:
    summary = assemble_robot_task_summary(
        robot_task={"task_id": 9, "task_type": "OUTBOUND", "quantity": 1, "status": "QUEUED"},
        order_id=9,
        execution=RobotTaskExecutionState.wrap({}),
        active_command_id=None,
        floor=1,
    )

    assert summary.progress is None
    assert robot_task_summary_to_v1(summary)["progress"] is None


def test_scenario_progress_projects_business_steps() -> None:
    execution = RobotTaskExecutionState.wrap(
        {
            "phase": "RUNNING",
            "step_index": 0,
            "steps": [{
                "kind": "inout_scenario",
                "status": "DISPATCHED",
                "command_id": "scenario-1",
                "route_timeline_current_index": 1,
                "route_timeline": [
                    {"kind": "LEAVE_HOME", "label": "대기 위치 출차", "status": "DONE", "command_id": "scenario-1"},
                    {"kind": "PICKUP_APPROACH", "label": "적재 위치 이동", "status": "RUNNING", "command_id": "scenario-1"},
                    {"kind": "PICKUP_ALIGN", "label": "적재 위치 정밀 접근", "status": "PENDING", "command_id": "scenario-1"},
                ],
            }],
        }
    )
    summary = assemble_robot_task_summary(
        robot_task={"task_id": 1, "task_type": "INBOUND", "quantity": 1, "status": "RUNNING"},
        order_id=1,
        execution=execution,
        active_command_id="scenario-1",
        floor=1,
    )
    assert summary.progress is not None
    assert summary.progress.current_step_index == 1
    assert [step.label for step in summary.progress.steps] == ["대기 위치 출차", "적재 위치 이동", "적재 위치 정밀 접근"]
    assert [step.status for step in summary.progress.steps] == ["DONE", "RUNNING", "PENDING"]
