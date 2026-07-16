"""Movement 서버 전달 경계.

Main/LMS 서버는 docs/reference/MAIN_SERVER_COMMUNICATION_SPEC.md의 Movement 수동 조작 API를 호출한다.
로봇별 Nav API 포트가 다르므로 robot_id에 따라 base URL을 선택한다.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from app.core.api_logs import begin_call, finish_call
from app.core.config import settings
from app.core.http_security import (
    MAX_JSON_RESPONSE_BYTES,
    UpstreamResponseTooLarge,
    read_error_detail,
    read_limited,
    validate_service_base_url,
)

_emergency_by_robot: dict[str, bool] = {}


def robot_is_emergency(robot_id: str) -> bool:
    return _emergency_by_robot.get(robot_id, False)


def set_robot_emergency(robot_id: str, is_emergency: bool) -> None:
    _emergency_by_robot[robot_id] = is_emergency


def movement_robot_key(robot_id: str) -> str:
    """DB robot ID를 Movement HTTP routing ID로 변환한다."""
    return settings.movement_robot_keys.get(robot_id, robot_id)


class MovementClientError(RuntimeError):
    """Movement 서버 호출 실패."""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


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

    def dock_transfer(self, robot_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """게이트 도킹 블록(아루코 정밀 도킹 + 리프트 상/하차)을 트리거한다. MOVEMENT_SERVER_REQUIREMENTS §10.2."""
        raise NotImplementedError

    def aruco_align(self, robot_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """무리프트 정밀 정렬(주차·충전). GATE_DOCKING aruco_align (S4)."""
        raise NotImplementedError

    def aruco_latest(self, robot_id: str, marker_id: int) -> dict[str, Any]:
        """ArUco 검출 readout — 수동 정렬 테스트용."""
        raise NotImplementedError

    def command_status(self, robot_id: str, command_id: str) -> dict[str, Any]:
        last_error: MovementClientError | None = None
        for base in self._bases_for(robot_id):
            try:
                return self._get_json(
                    f"{self._api_origin(base)}/robot-commands/{command_id}", robot_id, kind="command_status"
                )
            except MovementClientError as exc:
                if exc.status_code is not None:
                    raise
                last_error = exc
        raise last_error or MovementClientError("movement unreachable")

    def cancel_command(self, robot_id: str, command_id: str) -> dict[str, Any]:
        last_error: MovementClientError | None = None
        for base in self._bases_for(robot_id):
            try:
                return self._post_json(
                    f"{self._api_origin(base)}/robot-commands/{command_id}/cancel", {}, kind="command_cancel"
                )
            except MovementClientError as exc:
                if exc.status_code is not None:
                    raise
                last_error = exc
        raise last_error or MovementClientError("movement unreachable")

    def robot_pose(self, robot_id: str) -> dict[str, Any]:
        """Movement 서버에서 최신 robot pose를 조회한다."""
        raise NotImplementedError

    def localization(self, robot_id: str) -> dict[str, Any]:
        """Movement 서버에서 localization 진단 상태를 조회한다."""
        raise NotImplementedError

    def initial_pose(self, robot_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Movement 서버에 초기 pose 설정을 요청한다."""
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
        """네이티브 POST /robot-commands envelope 패스스루."""
        raise NotImplementedError

    def inout_scenario_command(self, robot_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Scenario API v1 입출고 전체 명령을 한 번에 실행한다."""
        raise NotImplementedError

    def inout_scenario_status(self, robot_id: str, command_id: str) -> dict[str, Any]:
        """Scenario API v1 명령 상태를 조회한다."""
        raise NotImplementedError

    def inout_scenario_safe_stop(
        self, robot_id: str, command_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        """Scenario API v1 명령에 안전 정지를 요청한다."""
        raise NotImplementedError


class HttpMovementClient(MovementClient):
    """Movement 수동 조작 API를 호출하는 client."""

    mode = "http"

    def __init__(
        self,
        base_urls: dict[str, str],
        fallback_urls: dict[str, str],
        fallback_url: str,
        timeout_sec: float,
    ):
        self.base_urls = {k: validate_service_base_url(v) for k, v in base_urls.items()}
        self.fallback_urls = {k: validate_service_base_url(v) for k, v in fallback_urls.items() if v}
        self.fallback_url = validate_service_base_url(fallback_url)
        if timeout_sec <= 0 or timeout_sec > 30:
            raise ValueError("movement timeout must be greater than 0 and at most 30 seconds")
        self.timeout_sec = timeout_sec

    @staticmethod
    def _api_origin(base: str) -> str:
        """movement-api/v1 prefix를 제거해 서버 루트(origin)를 반환한다."""
        base = base.rstrip("/")
        suffix = "/movement-api/v1"
        return base[: -len(suffix)] if base.endswith(suffix) else base

    def _bases_for(self, robot_id: str) -> list[str]:
        key = movement_robot_key(robot_id)
        primary = self.base_urls.get(key, self.fallback_url)
        fallback = self.fallback_urls.get(key, "")
        bases = [primary]
        if fallback and fallback != primary:
            bases.append(fallback)
        return bases

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

    def command_status(self, robot_id: str, command_id: str) -> dict[str, Any]:
        """GET /robot-commands/{id} from the canonical Movement API root."""
        last_error: MovementClientError | None = None
        for base in self._bases_for(robot_id):
            url = f"{self._api_origin(base)}/robot-commands/{command_id}"
            try:
                return self._get_json(url, robot_id, kind="command_status")
            except MovementClientError as exc:
                if exc.status_code is not None:
                    raise
                last_error = exc
        raise last_error or MovementClientError(
            f"movement command status not found: {command_id}",
            status_code=404,
        )

    def cancel_command(self, robot_id: str, command_id: str) -> dict[str, Any]:
        """Cancel through the canonical Movement command endpoint."""
        last_error: MovementClientError | None = None
        for base in self._bases_for(robot_id):
            url = f"{self._api_origin(base)}/robot-commands/{command_id}/cancel"
            try:
                return self._post_json(url, {}, kind="command_cancel")
            except MovementClientError as exc:
                if exc.status_code is not None:
                    raise
                last_error = exc
        raise last_error or MovementClientError("movement command cancel unavailable", status_code=404)

    def robot_pose(self, robot_id: str) -> dict[str, Any]:
        return self._get_json_for_robot(robot_id, f"/robots/{robot_id}/pose", kind="robot_pose")

    def localization(self, robot_id: str) -> dict[str, Any]:
        return self._get_json_for_robot(robot_id, f"/robots/{robot_id}/localization", kind="localization")

    def initial_pose(self, robot_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._post_json_for_robot(robot_id, f"/robots/{robot_id}/initial-pose", body, kind="initial_pose")

    def nav_state(self, robot_id: str) -> dict[str, Any]:
        return self._get_json_for_robot(robot_id, f"/robots/{robot_id}/nav-state", kind="nav_state")

    def map_state(self, robot_id: str | None = None) -> dict[str, Any]:
        target_robot = robot_id or next(iter(self.base_urls), "")
        return self._get_json_for_robot(target_robot, "/map-state", kind="map_state")

    def estop(self, robot_id: str) -> dict[str, Any]:
        result = self._post_json_for_robot(robot_id, "/robot/estop", {}, kind="estop")
        set_robot_emergency(robot_id, True)
        return result

    def clear_estop(self, robot_id: str) -> dict[str, Any]:
        result = self._post_json_for_robot(robot_id, "/robot/clear_estop", {}, kind="clear_estop")
        set_robot_emergency(robot_id, False)
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
        last_error: MovementClientError | None = None
        for base in self._bases_for(robot_id):
            url = f"{self._api_origin(base)}/robot-commands"
            try:
                return self._post_json(
                    url,
                    body,
                    kind="robot_command",
                    headers={"Idempotency-Key": str(body.get("command_id") or "")},
                )
            except MovementClientError as exc:
                if exc.status_code is not None:
                    raise
                last_error = exc
        raise last_error or MovementClientError("movement unreachable")

    def inout_scenario_command(self, robot_id: str, body: dict[str, Any]) -> dict[str, Any]:
        last_error: MovementClientError | None = None
        for base in self._bases_for(robot_id):
            try:
                return self._post_json(
                    f"{base}/scenario-commands",
                    body,
                    kind="inout_scenario_command",
                    headers={"Idempotency-Key": str(body.get("command_id") or "")},
                )
            except MovementClientError as exc:
                if exc.status_code is not None:
                    raise
                last_error = exc
        raise last_error or MovementClientError("movement unreachable")

    def inout_scenario_status(self, robot_id: str, command_id: str) -> dict[str, Any]:
        command = quote(command_id, safe="")
        last_error: MovementClientError | None = None
        for base in self._bases_for(robot_id):
            try:
                return self._get_json(
                    f"{base}/scenario-commands/{command}",
                    robot_id,
                    kind="inout_scenario_status",
                )
            except MovementClientError as exc:
                if exc.status_code is not None:
                    raise
                last_error = exc
        raise last_error or MovementClientError("movement unreachable")

    def inout_scenario_safe_stop(
        self, robot_id: str, command_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        command = quote(command_id, safe="")
        last_error: MovementClientError | None = None
        for base in self._bases_for(robot_id):
            try:
                return self._post_json(
                    f"{base}/scenario-commands/{command}/safe-stop",
                    body,
                    kind="inout_scenario_safe_stop",
                    headers={"Idempotency-Key": str(body.get("request_id") or "")},
                )
            except MovementClientError as exc:
                if exc.status_code is not None:
                    raise
                last_error = exc
        raise last_error or MovementClientError("movement unreachable")

    def _get_json_for_robot(self, robot_id: str, path: str, *, kind: str) -> dict[str, Any]:
        last_error: MovementClientError | None = None
        rel = path if path.startswith("/") else f"/{path}"
        for base in self._bases_for(robot_id):
            try:
                return self._get_json(f"{base}{rel}", robot_id, kind=kind)
            except MovementClientError as exc:
                if exc.status_code is not None:
                    raise
                last_error = exc
        raise last_error or MovementClientError("movement unreachable")

    def _post_json_for_robot(self, robot_id: str, path: str, payload: dict[str, Any], *, kind: str) -> dict[str, Any]:
        last_error: MovementClientError | None = None
        rel = path if path.startswith("/") else f"/{path}"
        for base in self._bases_for(robot_id):
            try:
                return self._post_json(f"{base}{rel}", payload, kind=kind)
            except MovementClientError as exc:
                if exc.status_code is not None:
                    raise
                last_error = exc
        raise last_error or MovementClientError("movement unreachable")

    def _post_json(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        kind: str,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return self._request_json(
            url,
            method="POST",
            kind=kind,
            source=payload.get("robot_name"),
            payload=payload,
            success_message="accepted",
            extra_headers=headers,
        )

    def _get_json(self, url: str, robot_id: str, *, kind: str) -> dict[str, Any]:
        return self._request_json(url, method="GET", kind=kind, source=robot_id, success_message="ok")

    def _request_json(
        self,
        url: str,
        *,
        method: str,
        kind: str,
        source: str | None,
        payload: dict[str, Any] | None = None,
        success_message: str,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        headers.update(extra_headers or {})
        req = Request(url, data=body, headers=headers, method=method)
        ctx = begin_call("movement", kind, method, url, source=source)
        try:
            with urlopen(req, timeout=self.timeout_sec) as res:
                raw = read_limited(res, max_bytes=MAX_JSON_RESPONSE_BYTES).decode("utf-8")
            finish_call(ctx, True, 200, success_message)
        except HTTPError as exc:
            read_error_detail(exc)
            safe_detail = f"movement upstream HTTP {exc.code}"
            finish_call(ctx, False, exc.code, safe_detail)
            raise MovementClientError(safe_detail, status_code=exc.code) from exc
        except URLError as exc:
            finish_call(ctx, False, "unreachable", "movement unreachable")
            raise MovementClientError("movement unreachable") from exc
        except TimeoutError as exc:
            finish_call(ctx, False, "timeout", "movement request timed out")
            raise MovementClientError("movement request timed out") from exc
        except UpstreamResponseTooLarge as exc:
            finish_call(ctx, False, 502, "movement response too large")
            raise MovementClientError("movement response too large", status_code=502) from exc
        except UnicodeDecodeError as exc:
            finish_call(ctx, False, 502, "movement response is not valid JSON")
            raise MovementClientError("movement response is not valid JSON", status_code=502) from exc

        try:
            return json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            finish_call(ctx, False, 502, "movement response is not valid JSON")
            raise MovementClientError("movement response is not valid JSON", status_code=502) from exc


def create_movement_client() -> MovementClient:
    """실 Movement HTTP client를 만든다."""
    return HttpMovementClient(
        settings.movement_base_urls,
        settings.movement_fallback_base_urls,
        settings.movement_base_url,
        settings.movement_timeout_sec,
    )


movement_client = create_movement_client()
