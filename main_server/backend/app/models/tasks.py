"""Task schemas."""

from pydantic import BaseModel


class Task(BaseModel):
    """관제 작업(task)."""

    task_id: int
    task_type: str
    preset_name: str | None = None
    status: str
    priority: int = 0
    assigned_robot_id: str | None = None
    from_location: str | None = None
    to_location: str | None = None
    created_by: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class TaskCreate(BaseModel):
    """작업 생성 요청."""

    task_type: str = "MOVE"
    preset_name: str | None = None
    priority: int = 0
    from_location: str | None = None
    to_location: str | None = None
    created_by: str | None = "operator"


class TaskAssign(BaseModel):
    """작업 수동 배정 요청."""

    robot_id: str
