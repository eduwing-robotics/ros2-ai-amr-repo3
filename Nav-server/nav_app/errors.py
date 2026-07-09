from typing import Optional


class StageError(RuntimeError):
    def __init__(self, stage: str, reason: str):
        self.stage = stage
        self.reason = reason
        super().__init__(reason)


class CommandAborted(RuntimeError):
    def __init__(
        self,
        reason: str,
        stage: str,
        robot_at: Optional[str] = None,
        resumable: bool = False,
    ):
        self.reason = reason
        self.stage = stage
        self.robot_at = robot_at
        self.resumable = resumable
        super().__init__(reason)
