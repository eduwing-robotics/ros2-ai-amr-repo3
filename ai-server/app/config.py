import os
import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .source_registry import SourceRegistry, load_source_registry_cached

SERVICE_DIR = Path(__file__).resolve().parents[1]
# Standalone deploy package root. Keep REPO_ROOT as an alias for code paths
# that historically meant the SmartFactory repository root.
REPO_ROOT = SERVICE_DIR


class Settings(BaseSettings):
    """Runtime configuration for the API-first AI Server."""

    model_config = SettingsConfigDict(
        env_file=(SERVICE_DIR / ".env.local", SERVICE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ai_server_host: str = "127.0.0.1"
    ai_server_port: int = 8100
    ai_server_cors_allow_origins: str = (
        "http://smartfactory-main.local:8088,http://localhost:8088,http://127.0.0.1:8088"
    )
    main_server_url: str = "http://smartfactory-main.local:8088"
    # Required for Main-originated monitor/evidence mutations. Missing secret fails closed.
    ai_no_hardware: bool = False
    main_hmac_secret: str = Field(default_factory=lambda: os.getenv("MAIN_HMAC_SECRET", "").strip() or (secrets.token_urlsafe(32) if os.getenv("AI_NO_HARDWARE", "").lower() in {"1", "true", "yes", "on"} else ""))
    main_hmac_clock_skew_sec: float = 60.0
    # Dedicated, least-privilege credential for the ROS frame gateway.  It may
    # sign only the frame ingest routes and must not be shared with Main.
    vision_gateway_hmac_secret: str = ""
    vision_public_host: str = "<vision-host>"
    vision_stream_gateway_port: int = 8090
    camera_sources: str = "global_cam_01,tb3_1_picam,tb3_2_picam"
    ros_image_topics: str = "/global_camera/image_raw,/tb3_1/camera/image_raw/compressed,/tb3_2/camera/image_raw/compressed"
    vision_sources_registry_path: Path = REPO_ROOT / "config" / "vision" / "sources.yaml"
    vision_event_schema_version: str = "vision-event.v1"
    model_name: str = "opencv-marker-detector"
    policy_version: str = "mvp1"
    wms_emit_enabled: bool = False
    wms_emit_timeout_s: float = 2.0
    wms_emit_retries: int = 0
    wms_vision_events_path: str = "/api/v1/vision/events"
    source_target_fps: float = 10.0
    source_stale_after_s: float = 2.0
    source_offline_after_s: float = 30.0
    event_store_maxlen: int = 200
    vision_model_path: str = ""
    vision_model_task: str = "segment"
    vision_model_conf: float = 0.5
    vision_model_iou: float = 0.5
    vision_model_imgsz: int = 640
    vision_model_device: str = "cpu"
    vision_model_worker_enabled: bool = False
    vision_model_class_map_json: str = '{"bottle":"box","person":"person"}'
    vision_model_unmapped_class: str = "unknown"
    vision_model_max_events: int = 20
    vision_model_source_config_json: str = ""
    contract_schema_path: Path = Field(
        default=REPO_ROOT / "docs" / "contracts" / "vision-event.schema.json"
    )
    lift_roi_evidence_schema_path: Path = Field(
        default=REPO_ROOT / "docs" / "contracts" / "lift-roi-evidence.schema.json"
    )
    evidence_evaluation_schema_path: Path = Field(
        default=REPO_ROOT / "docs" / "contracts" / "evidence-evaluation.v1.schema.json"
    )
    evidence_image_root: Path = Field(default=REPO_ROOT / "var" / "evidence-images")
    evidence_image_base_uri: str = "/api/v1/evidence/images"
    vision_webrtc_enabled: bool = True
    vision_webrtc_sidecar_offer_url_template: str = ""
    vision_webrtc_sidecar_whep_url_template: str = ""
    vision_webrtc_sidecar_browser_url_template: str = ""
    vision_webrtc_sidecar_health_url: str = ""
    vision_webrtc_sidecar_paths_api_url: str = ""
    vision_webrtc_sidecar_health_timeout_s: float = 0.25
    vision_webrtc_sidecar_streams: str = ""
    vision_webrtc_clean_video_streams: str = ""
    vision_webrtc_direct_media_streams: str = ""
    vision_webrtc_compositor_publisher_streams: str = ""
    vision_webrtc_compositor_metrics_dir: Path = Field(
        default=REPO_ROOT / ".run" / "vision" / "compositor-metrics"
    )
    vision_webrtc_compositor_heartbeat_max_age_s: float = 5.0
    vision_webrtc_overlay_refresh_fps: float = 5.0
    vision_webrtc_sidecar_assume_healthy_without_health_url: bool = False
    aruco_pose_profiles_path: Path = Field(
        default=REPO_ROOT / "config" / "perception" / "aruco_pose_profiles.example.json"
    )
    vision_map_roi_enabled: bool = False
    vision_map_roi_source: str = "global_cam_01"
    vision_map_roi_marker_ids: str = "11,12"
    vision_map_roi_min_markers: int = 1
    vision_map_roi_stale_usable_s: float = 180.0
    vision_map_roi_polygon_normalized: str = ""
    vision_map_roi_label: str = "MAP ROI"
    vision_map_roi_freeze_marker_ids: str = ""
    vision_map_roi_freeze_mode: str = "any"
    vision_zone_roi_enabled: bool = False
    vision_zone_roi_config_path: Path = Field(
        default=REPO_ROOT / "config" / "vision" / "zone_rois" / "global_cam_01_lab_draft.json"
    )
    vision_zone_roi_source: str = "global_cam_01"
    sf_runtime_control_enabled: bool = False
    sf_runtime_control_token: str = ""
    sf_runtime_control_run_dir: Path = Field(
        default=REPO_ROOT / ".run" / "vision" / "runtime-control"
    )
    sf_runtime_control_restart_script: Path = Field(
        default=REPO_ROOT / "scripts" / "vision" / "restart_vision_runtime.sh"
    )

    @property
    def source_registry(self) -> SourceRegistry:
        if self.vision_sources_registry_path.exists():
            return load_source_registry_cached(str(self.vision_sources_registry_path))
        return _legacy_source_registry(
            source_ids=[part.strip() for part in self.camera_sources.split(",") if part.strip()],
            image_topics=[
                part.strip() for part in self.ros_image_topics.split(",") if part.strip()
            ],
        )

    @property
    def source_ids(self) -> list[str]:
        return self.source_registry.source_ids

    @property
    def image_topics(self) -> list[str]:
        return [
            source.physical_input.topic
            for source in self.source_registry.sources
            if source.physical_input.topic
        ]


def _legacy_source_registry(*, source_ids: list[str], image_topics: list[str]) -> SourceRegistry:
    # Fallback for older local envs that have not mounted config/vision/sources.yaml.
    from .source_registry import (
        BrowserSurface,
        NormalizedTopics,
        PhysicalInput,
        SourceBudgets,
        SourceDefinition,
        SourceViewDefinition,
    )

    sources: list[SourceDefinition] = []
    for index, source_id in enumerate(source_ids):
        robot_id = None if source_id == "global_cam_01" else source_id.replace("_picam", "")
        kind = "global_rgb" if source_id == "global_cam_01" else "robot_pi_camera"
        frame_id = (
            "global_camera_frame"
            if source_id == "global_cam_01"
            else f"{robot_id}_pi_camera_optical_frame"
        )
        physical_topic = image_topics[index] if index < len(image_topics) else None
        legacy_topic = None
        if source_id == "tb3_1_picam":
            legacy_topic = "/mission/tb3_1/camera/compressed"
        elif source_id == "tb3_2_picam":
            legacy_topic = "/mission/tb3_2/camera/compressed"
        sources.append(
            SourceDefinition(
                source_id=source_id,
                kind=kind,
                robot_id=robot_id,
                frame_id=frame_id,
                enabled=True,
                target_fps=None,
                notes=(
                    "overview/slot/zone evidence"
                    if source_id == "global_cam_01"
                    else "front marker/dock/local item evidence"
                ),
                physical_input=PhysicalInput(
                    topic=physical_topic,
                    message_type=None,
                    content_type=None,
                    preferred_transport=None,
                ),
                browser=BrowserSurface(
                    legacy_topic=legacy_topic,
                    legacy_message_type=None,
                    primary_transport="rosbridge",
                ),
                normalized_topics=NormalizedTopics(
                    image=f"/sf/vision/sources/{source_id}/image/compressed",
                    overlay=f"/sf/vision/sources/{source_id}/overlay/compressed",
                ),
                evidence_event_topic="/sf/vision/events",
                budgets=SourceBudgets(
                    target_fps_semantics="legacy_ai_ingest_default",
                    preview_media_fps=None,
                    ai_monitor_fps=None,
                    evidence_imgsz=None,
                    browser_primary_transport_semantics="legacy_internal_rosbridge_metadata",
                ),
                views=(
                    SourceViewDefinition(
                        view_id="full",
                        kind="full_frame",
                        can_confirm_internal_color_indexing=False,
                    ),
                ),
            )
        )
    return SourceRegistry(schema_version="vision-sources.legacy", sources=tuple(sources))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
