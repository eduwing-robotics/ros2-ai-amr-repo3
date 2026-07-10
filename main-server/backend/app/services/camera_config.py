"""Camera 서버 설정 보조 함수.

Camera 서버 IP가 바뀌는 환경에서는 LMS_CAMERA_HOST만 바꿔 Main/UI가 보는
기본 API/stream endpoint를 갱신한다. DB에 개별 stream_url이 있으면 그 값을 우선한다.
"""

from __future__ import annotations

from app.core.config import settings
from app.models.schemas import CameraSource


def camera_system_config() -> dict[str, str]:
    """대시보드에 노출할 Camera 서버 설정."""
    return {
        "host": settings.camera_host,
        "api_base_url": settings.camera_api_base_url,
        "rosbridge_url": settings.camera_rosbridge_url,
        "stream_url_template": settings.camera_stream_url_template,
    }


def apply_camera_stream_defaults(cameras: list[CameraSource]) -> list[CameraSource]:
    """DB stream_url이 비어 있으면 환경변수 기반 기본 stream URL을 채운다."""
    return [camera_with_default_stream(camera) for camera in cameras]


def camera_with_default_stream(camera: CameraSource) -> CameraSource:
    if camera.stream_url:
        return camera
    return camera.model_copy(update={"stream_url": default_stream_url(camera)})


def default_stream_url(camera: CameraSource) -> str:
    """template에는 host/source_id/robot_id를 사용할 수 있다."""
    return settings.camera_stream_url_template.format(
        host=settings.camera_host,
        source_id=camera.source_id,
        robot_id=camera.robot_id or "",
    )
