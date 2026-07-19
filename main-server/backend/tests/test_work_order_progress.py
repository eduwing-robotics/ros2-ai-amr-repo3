from unittest.mock import MagicMock

from app.models.work_orders import WorkOrderTask
from app.services.work_orders_pg import _assigned_robot_id, _task_progress


def test_work_order_progress_projects_callback_tracked_steps() -> None:
    progress = _task_progress(
        {
            "phase": "RUNNING",
            "step_index": 1,
            "steps": [
                {"kind": "leave_dock", "status": "DONE", "command_id": "cmd-leave"},
                {"kind": "move_to_point", "status": "dispatched", "command_id": "cmd-load", "transfer_action": "load"},
                {"kind": "aruco_align", "status": "pending"},
            ],
        },
        [
            {
                "command_id": 31,
                "command_def_id": 31,
                "sequence_no": 1,
                "command_type": "move_to_point",
                "target_system": "movement",
                "required_evidence_type": "ARRIVED",
                "status": "DONE",
                "evidence_count": 2,
                "runtime_command_id": "cmd-load",
                "target": "inbound_scan",
                "human_hazard_monitor": True,
            },
            {
                "command_id": 32,
                "command_def_id": 32,
                "sequence_no": 2,
                "command_type": "verify_post_pick_up",
                "target_system": "vision",
                "required_evidence_type": "ITEM_PICKED",
                "status": "HOLD",
                "evidence_count": 2,
                "runtime_command_id": "vision-1",
                "human_hazard_monitor": False,
            },
        ],
    )
    assert progress is not None
    assert progress["current_step_index"] == 1
    assert [step["status"] for step in progress["steps"]] == ["DONE", "DISPATCHED", "PENDING"]
    assert progress["current_recipe_index"] == 1
    assert [step["kind"] for step in progress["recipe_steps"]] == [
        "move_to_point",
        "verify_post_pick_up",
    ]
    task = WorkOrderTask(order_id=1, task_id=1, quantity=1, progress=progress)
    assert task.progress is not None
    assert task.progress.steps[1].command_id == "cmd-load"
    assert task.progress.recipe_steps[1].target_system == "vision"
    assert task.progress.recipe_steps[1].command_def_id == 32
    assert task.progress.recipe_steps[0].human_hazard_monitor is True


def test_terminal_work_order_recovers_last_assigned_robot_from_runtime_evidence() -> None:
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = {"robot_id": "tb3_2"}

    robot_id = _assigned_robot_id(conn, {"task_id": 142, "assigned_robot_id": None})

    assert robot_id == "tb3_2"
    sql, params = conn.execute.call_args.args
    assert "evidence_events" in sql
    assert params == (142, "142")


def test_live_assignment_wins_without_history_query() -> None:
    conn = MagicMock()

    robot_id = _assigned_robot_id(conn, {"task_id": 143, "assigned_robot_id": "tb3_1"})

    assert robot_id == "tb3_1"
    conn.execute.assert_not_called()


def test_work_order_progress_is_absent_without_runtime_or_recipe() -> None:
    assert _task_progress({}) is None


def test_work_order_progress_projects_recipe_before_orchestration_starts() -> None:
    progress = _task_progress(
        {},
        [
            {
                "command_id": 31,
                "sequence_no": 1,
                "command_type": "move_to_point",
                "target_system": "movement",
                "required_evidence_type": "ARRIVED",
                "status": "PENDING",
                "target": "storage_scan",
            },
            {
                "command_id": 32,
                "sequence_no": 2,
                "command_type": "verify_post_pick_up",
                "target_system": "vision",
                "required_evidence_type": "ITEM_PICKED",
                "status": "PENDING",
            },
        ],
        task_phase="ASSIGNED",
    )

    assert progress is not None
    assert progress["phase"] == "ASSIGNED"
    assert progress["steps"] == []
    assert progress["current_step_index"] == 0
    assert progress["current_recipe_index"] == 0
    assert [step["status"] for step in progress["recipe_steps"]] == ["PENDING", "PENDING"]
