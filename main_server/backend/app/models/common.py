"""Shared API schema primitives."""

from typing import Literal

from pydantic import BaseModel

TeleopCommand = Literal["forward", "backward", "left", "right", "stop", "w", "x", "a", "d", "s", "space"]


class ApiMessage(BaseModel):
    """작은 성공 응답."""

    ok: bool = True
    message: str = ""
