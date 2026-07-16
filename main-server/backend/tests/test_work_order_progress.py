from app.models.work_orders import WorkOrderTask
from app.services.work_orders_pg import _task_progress


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
        }
    )
    assert progress is not None
    assert progress["current_step_index"] == 1
    assert [step["status"] for step in progress["steps"]] == ["DONE", "DISPATCHED", "PENDING"]
    task = WorkOrderTask(order_id=1, task_id=1, quantity=1, progress=progress)
    assert task.progress is not None
    assert task.progress.steps[1].command_id == "cmd-load"


def test_work_order_progress_is_absent_before_orchestration_starts() -> None:
    assert _task_progress({}) is None
