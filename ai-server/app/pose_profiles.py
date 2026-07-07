from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from .docking import CameraIntrinsics


class PoseProfileError(ValueError):
    """Raised when a configured ArUco pose profile is unavailable or invalid."""


@dataclass(frozen=True)
class ArucoPoseProfile:
    name: str
    source: str | None
    marker_id: str | None
    marker_size_m: float
    intrinsics: CameraIntrinsics
    description: str = ""

    def applies_to(self, *, source: str, marker_id: str) -> bool:
        if self.source is not None and self.source != source:
            return False
        if self.marker_id is not None and self.marker_id != marker_id:
            return False
        return True


def _required_number(mapping: dict[str, Any], key: str, *, profile_name: str) -> float:
    value = mapping.get(key)
    if not isinstance(value, int | float):
        raise PoseProfileError(f"pose profile {profile_name!r} requires numeric {key}")
    return float(value)


def _optional_string(mapping: dict[str, Any], key: str) -> str | None:
    value = mapping.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or value.strip() == "":
        return None
    return value


def _parse_profile(name: str, data: Any) -> ArucoPoseProfile:
    if not isinstance(data, dict):
        raise PoseProfileError(f"pose profile {name!r} must be an object")
    camera = data.get("camera")
    if not isinstance(camera, dict):
        raise PoseProfileError(f"pose profile {name!r} requires camera object")

    marker_size_m = _required_number(data, "marker_size_m", profile_name=name)
    if marker_size_m <= 0:
        raise PoseProfileError(f"pose profile {name!r} marker_size_m must be positive")

    fx = _required_number(camera, "fx", profile_name=name)
    fy = _required_number(camera, "fy", profile_name=name)
    cx = _required_number(camera, "cx", profile_name=name)
    cy = _required_number(camera, "cy", profile_name=name)
    if fx <= 0 or fy <= 0:
        raise PoseProfileError(f"pose profile {name!r} fx/fy must be positive")

    dist_raw = camera.get("dist_coeffs", [])
    if dist_raw is None:
        dist_coeffs: tuple[float, ...] = ()
    elif isinstance(dist_raw, list) and all(isinstance(item, int | float) for item in dist_raw):
        dist_coeffs = tuple(float(item) for item in dist_raw)
    else:
        raise PoseProfileError(f"pose profile {name!r} dist_coeffs must be a number list")

    return ArucoPoseProfile(
        name=name,
        source=_optional_string(data, "source"),
        marker_id=_optional_string(data, "marker_id"),
        marker_size_m=marker_size_m,
        intrinsics=CameraIntrinsics(fx=fx, fy=fy, cx=cx, cy=cy, dist_coeffs=dist_coeffs),
        description=_optional_string(data, "description") or "",
    )


@lru_cache(maxsize=8)
def load_pose_profiles(path: str) -> dict[str, ArucoPoseProfile]:
    profile_path = Path(path)
    if not profile_path.exists():
        raise PoseProfileError(f"pose profile file not found: {profile_path}")
    try:
        payload = json.loads(profile_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PoseProfileError(f"pose profile file is not valid JSON: {profile_path}") from exc

    profiles_raw = payload.get("profiles") if isinstance(payload, dict) else None
    if not isinstance(profiles_raw, dict):
        raise PoseProfileError("pose profile file requires top-level profiles object")

    profiles: dict[str, ArucoPoseProfile] = {}
    for name, data in profiles_raw.items():
        if not isinstance(name, str) or name.strip() == "":
            raise PoseProfileError("pose profile names must be non-empty strings")
        profiles[name] = _parse_profile(name, data)
    return profiles


def get_pose_profile(name: str, *, path: str | Path) -> ArucoPoseProfile:
    normalized = name.strip()
    if not normalized:
        raise PoseProfileError("pose_profile must be non-empty")
    profiles = load_pose_profiles(str(Path(path)))
    try:
        return profiles[normalized]
    except KeyError as exc:
        raise PoseProfileError(f"unknown pose_profile: {normalized}") from exc
