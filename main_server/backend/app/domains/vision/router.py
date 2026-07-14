"""Vision proxy routes."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Body, HTTPException, Query, Response
from fastapi.responses import StreamingResponse

from app.db.connection import transaction
from app.db.postgres import cameras
from app.domains.vision.client import (
    VisionUpstreamError,
    fetch_bridge_status,
    fetch_image,
    fetch_overlay_meta,
    fetch_person_hazard_latest,
    fetch_person_monitor_state,
    fetch_person_monitors,
    fetch_stream_transports,
    open_mjpeg_stream,
    post_webrtc_offer,
    put_person_monitor_state,
)
from app.models.person_hazard import validate_person_hazard_payload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vision", tags=["vision"])


def _require_known_source(source: str) -> None:
    """등록된 camera_sources.source_id만 프록시한다(open proxy/SSRF 방지)."""
    with transaction() as conn:
        known = {
            c["source_id"]
            for c in cameras.list_cameras(
                conn,
            )
        }
    if source not in known:
        raise HTTPException(status_code=404, detail="unknown camera source")


def _proxy_vision(fetch, source: str) -> Response:
    """vision_proxy fetch 결과를 binary로 통과시키고 upstream 오류를 매핑한다."""
    _require_known_source(source)
    try:
        body, content_type = fetch(source)
    except VisionUpstreamError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return Response(content=body, media_type=content_type, headers={"Cache-Control": "no-store"})


def _validate_webrtc_answer(body: bytes) -> None:
    """WebRTC answer가 미디어 전용인지 확인한다(부수효과 없음)."""
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except json.JSONDecodeError:
        return
    if not isinstance(payload, dict):
        return
    if payload.get("media_only") is False:
        logger.warning("vision webrtc offer response media_only=false")
    side = payload.get("side_effects")
    if isinstance(side, dict):
        for key in ("db_writes", "evidence_truth_mutated", "ros_control_published"):
            if side.get(key):
                logger.warning("vision webrtc offer unexpected side_effect: %s=%s", key, side.get(key))
    if payload.get("motion_command_allowed"):
        logger.warning("vision webrtc offer motion_command_allowed=true")


@router.get("/streams")
def vision_streams(
    source: str = Query(...),
    view: str = Query(default="full"),
) -> Response:
    """Vision stream transport 발견 JSON을 프록시한다 (WebRTC/MJPEG 후보)."""
    _require_known_source(source)
    try:
        body, content_type = fetch_stream_transports(source, view)
    except VisionUpstreamError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return Response(content=body, media_type=content_type, headers={"Cache-Control": "no-store"})


@router.post("/streams/{source_id}/webrtc/offer")
def vision_webrtc_offer(
    source_id: str,
    view: str = Query(default="full"),
    payload: dict = Body(...),
) -> Response:
    """WebRTC SDP offer를 Vision에 중계하고 answer를 반환한다 (시그널링만, DB 무쓰기)."""
    _require_known_source(source_id)
    try:
        body, content_type = post_webrtc_offer(source_id, view, payload)
    except VisionUpstreamError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    _validate_webrtc_answer(body)
    return Response(content=body, media_type=content_type, headers={"Cache-Control": "no-store"})


@router.get("/frame/latest/image")
def vision_frame_image(source: str = Query(...)) -> Response:
    """AI 서버의 source latest 원본 frame image를 프록시한다."""
    return _proxy_vision(lambda s: fetch_image("frame", s), source)


@router.get("/overlay/latest/image")
def vision_overlay_image(source: str = Query(...)) -> Response:
    """AI 서버의 source latest overlay image를 프록시한다."""
    return _proxy_vision(lambda s: fetch_image("overlay", s), source)


@router.get("/overlay/latest")
def vision_overlay_meta(source: str = Query(...)) -> Response:
    """AI 서버의 overlay 메타데이터 JSON(staleness/visual_state)을 프록시한다."""
    return _proxy_vision(fetch_overlay_meta, source)


@router.get("/bridge/status")
def vision_bridge_status() -> Response:
    """Vision stream bridge 상태 JSON을 프록시한다."""
    try:
        body, content_type = fetch_bridge_status()
    except VisionUpstreamError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return Response(content=body, media_type=content_type, headers={"Cache-Control": "no-store"})


def _proxy_vision_stream(kind: str, source: str, max_fps: int, view: str) -> StreamingResponse:
    """등록된 source의 MJPEG stream만 Main origin으로 중계한다."""
    _require_known_source(source)
    try:
        chunks, content_type = open_mjpeg_stream(kind, source, max_fps, view=view)
    except VisionUpstreamError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return StreamingResponse(
        chunks,
        media_type=content_type,
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.get("/overlay/stream")
def vision_overlay_stream(
    source: str = Query(...),
    view: str = Query(default="full"),
    max_fps: int = Query(default=30, ge=1, le=30),
) -> StreamingResponse:
    """Vision stream bridge의 AI overlay MJPEG stream을 프록시한다."""
    return _proxy_vision_stream("overlay", source, max_fps, view)


@router.get("/frame/stream")
def vision_frame_stream(
    source: str = Query(...),
    view: str = Query(default="full"),
    max_fps: int = Query(default=30, ge=1, le=30),
) -> StreamingResponse:
    """Vision stream bridge의 raw/frame MJPEG stream을 프록시한다(bridge가 제공할 때 사용)."""
    return _proxy_vision_stream("frame", source, max_fps, view)


@router.get("/monitors")
def vision_monitors() -> Response:
    try:
        payload = fetch_person_monitors()
    except VisionUpstreamError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return Response(content=json.dumps(payload), media_type="application/json", headers={"Cache-Control": "no-store"})


@router.get("/monitors/person_drive/state")
def vision_person_monitor_state(robot_id: str = Query(...)) -> Response:
    try:
        payload = fetch_person_monitor_state(robot_id)
    except VisionUpstreamError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return Response(content=json.dumps(payload), media_type="application/json", headers={"Cache-Control": "no-store"})


@router.put("/monitors/person_drive/state")
def vision_person_monitor_put(body: dict = Body(...)) -> Response:
    try:
        payload = put_person_monitor_state(body)
    except VisionUpstreamError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return Response(content=json.dumps(payload), media_type="application/json", headers={"Cache-Control": "no-store"})


@router.get("/hazards/person/latest")
def vision_person_hazard_latest(robot_id: str = Query(...)) -> Response:
    try:
        payload = fetch_person_hazard_latest(robot_id)
        if payload.get("event") is not None:
            validate_person_hazard_payload(payload, expected_robot_id=robot_id)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except VisionUpstreamError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return Response(content=json.dumps(payload), media_type="application/json", headers={"Cache-Control": "no-store"})
