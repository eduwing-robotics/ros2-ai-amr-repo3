"""Small shared contracts for request-scoped ArUco detection."""

import math
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


def processing_due(
    last_processed_monotonic: float,
    now_monotonic: float,
    rate_hz: float,
) -> bool:
    """Return whether a camera frame is due under the detector processing cap."""
    rate = float(rate_hz)
    if not math.isfinite(rate) or rate <= 0.0:
        return True
    elapsed = now_monotonic - last_processed_monotonic
    interval = 1.0 / rate
    return (
        last_processed_monotonic <= 0.0
        or elapsed >= interval
        or math.isclose(elapsed, interval, rel_tol=1e-9, abs_tol=1e-9)
    )
