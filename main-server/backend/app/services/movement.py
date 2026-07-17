"""Movement 서버 전달 경계.

Main/LMS 서버는 docs/reference/MAIN_SERVER_COMMUNICATION_SPEC.md의 Movement 수동 조작 API를 호출한다.
로봇별 Nav API 포트가 다르므로 robot_id에 따라 base URL을 선택한다.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.core.config import settings
from app.security import sign_headers
from app.services.api_logs import begin_call, finish_call
from app.services.robot_mapping import movement_robot_key


class MovementClientError(RuntimeError):
    """Movement 서버 호출 실패."""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


# fake 모드 비상정지 상태 (robot_id -> is_emergency)
_emergency_by_robot: dict[str, bool | None] = {}
# fake 모드 command 상태 (command_id -> meta)
_fake_commands: dict[str, dict[str, Any]] = {}


def robot_is_emergency(robot_id: str) -> bool:
    return robot_emergency_state(robot_id) is True


def robot_emergency_state(robot_id: str) -> bool | None:
    return _emergency_by_robot.get(robot_id, False)


def set_robot_emergency(robot_id: str, is_emergency: bool | None) -> None:
    _emergency_by_robot[robot_id] = is_emergency


class MovementClient:
    """Movement client interface."""

    mode = "base"

    def manual_rotate(self, robot_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """로봇을 좌/우로 짧게 회전시킨다."""
        raise NotImplementedError

    def manual_translate(self, robot_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """로봇을 전진/후진으로 짧게 이동시킨다."""
        raise NotImplementedError

    def manual_start(self, robot_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """버튼 홀드 방식 수동 조작을 시작한다."""
        raise NotImplementedError

    def manual_stop(self, robot_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """진행 중인 수동 조작을 정지한다."""
        raise NotImplementedError

    def mission_preview(self, robot_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Movement 서버에 mission preview를 요청한다."""
        raise NotImplementedError

    def mission_start(self, robot_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Movement 서버에 mission 실행을 요청한다."""
        raise NotImplementedError

    def route_preview(self, robot_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Movement 서버에 route/coordinate preview를 요청한다."""
        raise NotImplementedError

    def route_command(self, robot_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Movement 서버에 route/coordinate 실행을 요청한다."""
        raise NotImplementedError

    def dock_transfer(self, robot_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """게이트 도킹 블록(아루코 정밀 도킹 + 리프트 상/하차)을 트리거한다. MOVEMENT_SERVER_REQUIREMENTS §10.2."""
        raise NotImplementedError

    def aruco_align(self, robot_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """무리프트 정밀 정렬(주차·충전). GATE_DOCKING aruco_align (S4)."""
        raise NotImplementedError

    def aruco_latest(self, robot_id: str, marker_id: int) -> dict[str, Any]:
        """ArUco 검출 readout — 수동 정렬 테스트용(PHASE_19)."""
        raise NotImplementedError

    def command_status(self, robot_id: str, command_id: str) -> dict[str, Any]:
        """Movement 서버에서 command 상태를 조회한다."""
        raise NotImplementedError

    def cancel_command(self, robot_id: str, command_id: str) -> dict[str, Any]:
        """Cancel a command through the canonical Movement command endpoint."""
        raise NotImplementedError

    def robot_pose(self, robot_id: str) -> dict[str, Any]:
        """Movement 서버에서 최신 robot pose를 조회한다."""
        raise NotImplementedError

    def localization(self, robot_id: str) -> dict[str, Any]:
        """Movement 서버에서 localization 진단 상태를 조회한다."""
        raise NotImplementedError

    def initial_pose(self, robot_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Movement 서버에 초기 pose 설정을 요청한다."""
        raise NotImplementedError

    def restart_localization(self, robot_id: str) -> dict[str, Any]:
        """Discard the prior pose belief and restart observe-only localization."""
        raise NotImplementedError

    def nav_state(self, robot_id: str) -> dict[str, Any]:
        """Movement 서버에서 Nav2/command 상태를 조회한다."""
        raise NotImplementedError

    def map_state(self, robot_id: str | None = None) -> dict[str, Any]:
        """Movement 서버에서 active map 상태를 조회한다."""
        raise NotImplementedError

    def estop(self, robot_id: str) -> dict[str, Any]:
        """로봇 비상 정지를 요청한다."""
        raise NotImplementedError

    def clear_estop(self, robot_id: str) -> dict[str, Any]:
        """비상 정지 상태를 해제한다."""
        raise NotImplementedError

    def robot_command(self, robot_id: str, envelope: dict[str, Any]) -> dict[str, Any]:
        """네이티브 POST /robot-commands envelope 패스스루 (PHASE_18-A)."""
        raise NotImplementedError


class FakeMovementClient(MovementClient):
    """시연용 fake Movement client."""

    mode = "fake"

    def manual_rotate(self, robot_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._accepted(robot_id, body, endpoint="manual/rotate")

    def manual_translate(self, robot_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._accepted(robot_id, body, endpoint="manual/translate")

    def manual_start(self, robot_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._accepted(robot_id, body, endpoint="manual/start")

    def manual_stop(self, robot_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._accepted(robot_id, body, endpoint="manual/stop", stopped=True)

    def mission_preview(self, robot_id: str, body: dict[str, Any]) -> dict[str, Any]:
        steps = body.get("steps") or []
        return self._accepted(robot_id, body, endpoint="missions/preview", ok=True, step_count=len(steps), validated_steps=steps, warnings=[])

    def mission_start(self, robot_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._accepted(robot_id, body, endpoint="missions", state="ACCEPTED", step_count=len(body.get("steps") or []))

    def route_preview(self, robot_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._accepted(robot_id, body, endpoint="routes/preview", state="PREVIEWED", input_mode="coordinates")

    def route_command(self, robot_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._accepted(robot_id, body, endpoint="routes/commands", state="ACCEPTED", input_mode="coordinates")

    def dock_transfer(self, robot_id: str, body: dict[str, Any]) -> dict[str, Any]:
        # body의 aruco_marker_id·action·level을 그대로 에코해 마커가 실려 전달됨을 확인한다.
        return self._accepted(robot_id, body, endpoint="dock/transfer", state="ACCEPTED")

    def aruco_align(self, robot_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._accepted(robot_id, body, endpoint="aruco/align", state="ACCEPTED")

    def robot_command(self, robot_id: str, envelope: dict[str, Any]) -> dict[str, Any]:
        command_id = str(envelope.get("command_id") or f"fake-{robot_id}")
        kind = str(envelope.get("kind") or "unknown")
        _fake_commands[command_id] = {
            "robot_id": robot_id,
            "kind": kind,
            "state": "ACCEPTED",
            "dry_run": bool(envelope.get("dry_run")),
        }
        return self._accepted(robot_id, envelope, endpoint="robot-commands", state="ACCEPTED", command_id=command_id)

    def aruco_latest(self, robot_id: str, marker_id: int) -> dict[str, Any]:
        return {
            "robot_id": robot_id,
            "marker_id": marker_id,
            "detections": [
                {
                    "marker_id": marker_id,
                    "center_error_norm": 0.11,
                    "marker_width_px": 68,
                    "estimated_distance_m": 0.32,
                }
            ],
            "source": self.mode,
        }

    def command_status(self, robot_id: str, command_id: str) -> dict[str, Any]:
        meta = _fake_commands.get(command_id)
        state = "DONE" if meta else "DONE"
        return {
            "command_id": command_id,
            "robot_name": robot_id,
            "state": state,
            "message": "fake command status",
            "dry_run": bool(meta.get("dry_run")) if meta else True,
            "mode": self.mode,
            "kind": meta.get("kind") if meta else None,
        }

    def cancel_command(self, robot_id: str, command_id: str) -> dict[str, Any]:
        meta = _fake_commands.setdefault(command_id, {"robot_id": robot_id, "kind": "unknown"})
        meta["state"] = "CANCELED"
        return self._accepted(robot_id, {}, endpoint=f"robot-commands/{command_id}/cancel", state="CANCELED")

    def robot_pose(self, robot_id: str) -> dict[str, Any]:
        return {
            "robot_name": robot_id,
            "robot_id": robot_id,
            "localized": True,
            "pose": {
                "source": "fake",
                "frame_id": "map",
                "x": 0.0,
                "y": 0.0,
                "yaw": 0.0,
                "age_sec": 0.0,
            },
        }

    def localization(self, robot_id: str) -> dict[str, Any]:
        pose = self.robot_pose(robot_id)
        return {
            **pose,
            "ok": True,
            "robot_online": True,
            "localization_required": True,
            "initial_pose_required": False,
            "reason": "ok",
        }

    def initial_pose(self, robot_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._accepted(robot_id, body, endpoint="robots/initial-pose", accepted=True, message="fake initial pose accepted")

    def restart_localization(self, robot_id: str) -> dict[str, Any]:
        return self._accepted(
            robot_id,
            {},
            endpoint="robots/localization/global-search",
            accepted=True,
            search={"strategy": "observe_only", "motion_started": False},
        )

    def nav_state(self, robot_id: str) -> dict[str, Any]:
        emergency_state = robot_emergency_state(robot_id)
        emergency = emergency_state is True
        emergency_unknown = emergency_state is None
        return {
            "robot_name": robot_id,
            "robot_online": not emergency_unknown,
            "command_accepting": not emergency and not emergency_unknown,
            "nav2_ready": True,
            "navigator_status": "ESTOP" if emergency else "UNKNOWN" if emergency_unknown else "IDLE",
            "is_emergency": emergency,
            "estop_state": "active" if emergency else "unknown" if emergency_unknown else "clear",
            "current_command_id": None,
            "localized": True,
            "reason": "estop" if emergency else "estop_unknown" if emergency_unknown else "ok",
            "active_commands": [],
        }

    def estop(self, robot_id: str) -> dict[str, Any]:
        _emergency_by_robot[robot_id] = True
        return self._accepted(robot_id, {}, endpoint="robot/estop", is_emergency=True)

    def clear_estop(self, robot_id: str) -> dict[str, Any]:
        _emergency_by_robot[robot_id] = False
        return self._accepted(robot_id, {}, endpoint="robot/clear_estop", is_emergency=False)

    def map_state(self, robot_id: str | None = None) -> dict[str, Any]:
        return {
            "active_map_id": settings.movement_active_map_id,
            "frame_id": "map",
            "source": "fake",
        }

    def _accepted(self, robot_id: str, body: dict[str, Any], endpoint: str, **extra: Any) -> dict[str, Any]:
        return {
            "accepted": True,
            "robot_name": robot_id,
            "dry_run": True,
            "mode": self.mode,
            "endpoint": endpoint,
            **body,
            **extra,
        }


class HttpMovementClient(MovementClient):
    """Movement 수동 조작 API를 호출하는 client."""

    mode = "http"

    def __init__(
        self,
        base_urls: dict[str, str],
        timeout_sec: float,
    ):
        self.base_urls = {k: v.rstrip("/") for k, v in base_urls.items()}
        self.timeout_sec = timeout_sec

    @staticmethod
    def _api_origin(base: str) -> str:
        """movement-api/v1 prefix를 제거해 서버 루트(origin)를 반환한다."""
        base = base.rstrip("/")
        suffix = "/movement-api/v1"
        return base[: -len(suffix)] if base.endswith(suffix) else base

    def _bases_for(self, robot_id: str) -> list[str]:
        key = movement_robot_key(robot_id)
        primary = self.base_urls.get(key)
        if not primary:
            raise MovementClientError(
                f"movement endpoint is not configured for robot={robot_id}",
                status_code=503,
            )
        return [primary]

    def _base_for(self, robot_id: str) -> str:
        return self._bases_for(robot_id)[0]

    def manual_rotate(self, robot_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._post_json_for_robot(robot_id, "/manual/rotate", body, kind="manual_rotate")

    def manual_translate(self, robot_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._post_json_for_robot(robot_id, "/manual/translate", body, kind="manual_translate")

    def manual_start(self, robot_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._post_json_for_robot(robot_id, "/manual/start", body, kind="manual_start")

    def manual_stop(self, robot_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._post_json_for_robot(robot_id, "/manual/stop", body, kind="manual_stop")

    def mission_preview(self, robot_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._post_json_for_robot(robot_id, "/missions/preview", body, kind="mission_preview")

    def mission_start(self, robot_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._post_json_for_robot(robot_id, "/missions", body, kind="mission_start")

    def route_preview(self, robot_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._post_json_for_robot(robot_id, "/routes/preview", body, kind="route_preview")

    def route_command(self, robot_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._post_json_for_robot(robot_id, "/routes/commands", body, kind="route_command")

    def command_status(self, robot_id: str, command_id: str) -> dict[str, Any]:
        """GET only the canonical Movement command endpoint."""
        last_error: MovementClientError | None = None
        for base in self._bases_for(robot_id):
            origin = self._api_origin(base)
            try:
                return self._get_json(
                    f"{origin}/robot-commands/{command_id}",
                    robot_id,
                    kind="command_status",
                )
            except MovementClientError as exc:
                if exc.status_code is not None:
                    raise
                last_error = exc
        raise last_error or MovementClientError(
            f"movement command status not found: {command_id}",
            status_code=404,
        )

    def cancel_command(self, robot_id: str, command_id: str) -> dict[str, Any]:
        """Cancel through the canonical signed Movement command endpoint."""
        last_error: MovementClientError | None = None
        for base in self._bases_for(robot_id):
            try:
                return self._post_json(
                    f"{self._api_origin(base)}/robot-commands/{command_id}/cancel",
                    {},
                    kind="command_cancel",
                )
            except MovementClientError as exc:
                if exc.status_code is not None:
                    raise
                last_error = exc
        raise last_error or MovementClientError("movement unreachable")

    def robot_pose(self, robot_id: str) -> dict[str, Any]:
        return self._get_json_for_robot(robot_id, f"/robots/{robot_id}/pose", kind="robot_pose")

    def localization(self, robot_id: str) -> dict[str, Any]:
        return self._get_json_for_robot(robot_id, f"/robots/{robot_id}/localization", kind="localization")

    def initial_pose(self, robot_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._post_json_for_robot(robot_id, f"/robots/{robot_id}/initial-pose", body, kind="initial_pose")

    def restart_localization(self, robot_id: str) -> dict[str, Any]:
        return self._post_json_for_robot(
            robot_id,
            f"/robots/{robot_id}/localization/global-search",
            {
                "strategy": "observe_only",
                "allow_motion": False,
                "restart_existing": True,
                "source": "main_ui_relocalize",
            },
            kind="restart_localization",
        )

    def nav_state(self, robot_id: str) -> dict[str, Any]:
        return self._get_json_for_robot(robot_id, f"/robots/{robot_id}/nav-state", kind="nav_state")

    def map_state(self, robot_id: str | None = None) -> dict[str, Any]:
        target_robot = robot_id or next(iter(self.base_urls), "")
        return self._get_json_for_robot(target_robot, "/map-state", kind="map_state")

    def estop(self, robot_id: str) -> dict[str, Any]:
        result = self._post_json(
            f"{self._api_origin(self._base_for(robot_id))}/robot/estop",
            {},
            kind="estop",
        )
        _emergency_by_robot[robot_id] = True
        return result

    def clear_estop(self, robot_id: str) -> dict[str, Any]:
        result = self._post_json(
            f"{self._api_origin(self._base_for(robot_id))}/robot/clear_estop",
            {},
            kind="clear_estop",
        )
        _emergency_by_robot[robot_id] = False
        return result

    def aruco_latest(self, robot_id: str, marker_id: int) -> dict[str, Any]:
        return self._get_json_for_robot(
            robot_id,
            f"/aruco/latest?marker_id={marker_id}",
            kind="aruco_latest",
        )

    def robot_command(self, robot_id: str, envelope: dict[str, Any]) -> dict[str, Any]:
        """핸드오프 §4: POST /robot-commands (서버 루트, movement-api/v1 prefix 없음)."""
        key = movement_robot_key(robot_id)
        body = {**envelope, "robot_id": key, "robot_name": key}
        return self._post_json(
            f"{self._api_origin(self._base_for(robot_id))}/robot-commands",
            body,
            kind="robot_command",
        )

    def _get_json_for_robot(self, robot_id: str, path: str, *, kind: str) -> dict[str, Any]:
        rel = path if path.startswith("/") else f"/{path}"
        return self._get_json(f"{self._base_for(robot_id)}{rel}", robot_id, kind=kind)

    def _post_json_for_robot(self, robot_id: str, path: str, payload: dict[str, Any], *, kind: str) -> dict[str, Any]:
        rel = path if path.startswith("/") else f"/{path}"
        return self._post_json(f"{self._base_for(robot_id)}{rel}", payload, kind=kind)

    def _post_json(self, url: str, payload: dict[str, Any], *, kind: str) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        if not settings.movement_hmac_secret:
            raise MovementClientError("Main↔Nav HMAC secret is not configured", status_code=503)
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        headers.update(sign_headers(settings.movement_hmac_secret, "POST", url, body))
        req = Request(
            url,
            data=body,
            headers=headers,
            method="POST",
        )
        ctx = begin_call("movement", kind, "POST", url, source=payload.get("robot_name"))
        try:
            with urlopen(req, timeout=self.timeout_sec) as res:
                raw = res.read().decode("utf-8")
            finish_call(ctx, True, 200, "accepted")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            finish_call(ctx, False, exc.code, detail)
            raise MovementClientError(f"movement HTTP {exc.code}: {detail}", status_code=exc.code) from exc
        except URLError as exc:
            finish_call(ctx, False, "unreachable", str(exc.reason))
            raise MovementClientError(f"movement unreachable: {exc.reason}") from exc
        except TimeoutError as exc:
            finish_call(ctx, False, "timeout", "movement request timed out")
            raise MovementClientError("movement request timed out") from exc

        return json.loads(raw) if raw else {}

    def _get_json(self, url: str, robot_id: str, *, kind: str) -> dict[str, Any]:
        req = Request(url, headers={"Accept": "application/json"}, method="GET")
        ctx = begin_call("movement", kind, "GET", url, source=robot_id)
        try:
            with urlopen(req, timeout=self.timeout_sec) as res:
                raw = res.read().decode("utf-8")
            finish_call(ctx, True, 200, "ok")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            finish_call(ctx, False, exc.code, detail)
            raise MovementClientError(f"movement HTTP {exc.code}: {detail}", status_code=exc.code) from exc
        except URLError as exc:
            finish_call(ctx, False, "unreachable", str(exc.reason))
            raise MovementClientError(f"movement unreachable: {exc.reason}") from exc
        except TimeoutError as exc:
            finish_call(ctx, False, "timeout", "movement request timed out")
            raise MovementClientError("movement request timed out") from exc

        return json.loads(raw) if raw else {}


def create_movement_client() -> MovementClient:
    """환경 변수에 따라 fake/http client를 만든다."""
    mode = settings.movement_client_mode.strip().lower()
    if mode == "http":
        return HttpMovementClient(
            settings.movement_base_urls,
            settings.movement_timeout_sec,
        )
    if mode == "fake":
        return FakeMovementClient()
    raise RuntimeError(f"unsupported LMS_MOVEMENT_CLIENT_MODE={settings.movement_client_mode}")


movement_client = create_movement_client()
