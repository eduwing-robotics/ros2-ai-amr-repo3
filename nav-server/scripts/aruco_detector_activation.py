"""Small shared contract for request-scoped ArUco camera activation."""

import os
from pathlib import Path
from typing import Union


PathValue = Union[str, os.PathLike]


def _activation_path(value: PathValue) -> Path | None:
    text = str(value or "").strip()
    return Path(text) if text else None


def activation_requested(value: PathValue, *, default: bool) -> bool:
    path = _activation_path(value)
    return bool(default) if path is None else path.is_file()


def set_activation(value: PathValue, enabled: bool) -> bool:
    path = _activation_path(value)
    if path is None:
        return False
    if enabled:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text("enabled\n", encoding="utf-8")
        os.replace(temporary, path)
    else:
        path.unlink(missing_ok=True)
    return True
