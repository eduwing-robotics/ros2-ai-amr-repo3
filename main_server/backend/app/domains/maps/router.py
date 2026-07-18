"""Map metadata and map asset routes."""

from __future__ import annotations

from fastapi import APIRouter, Response
from fastapi.responses import FileResponse

from app.domains.maps.assets import cached_pgm_to_png, find_map_asset, import_map_assets, list_map_asset_records
from app.domains.movement.navigation import get_runtime_map_context, overlay_nav_dims
from app.models.maps import MapRecord

router = APIRouter(tags=["maps"])


@router.get("/maps", response_model=list[MapRecord])
def list_maps() -> list[MapRecord]:
    """관제 맵 목록. runtime context overlay로 좌표계 진단을 포함한다."""
    ctx = get_runtime_map_context()
    rows = [overlay_nav_dims(m, ctx) for m in list_map_asset_records()]
    return [MapRecord(**m) for m in rows]


@router.get("/map-assets")
def list_map_assets() -> list[dict]:
    """maps 폴더의 ROS map.yaml/map.pgm 파일 목록을 반환한다."""
    return list_map_asset_records()


@router.post("/maps/import-folder")
def import_maps_from_folder() -> dict:
    """maps 폴더의 유일한 ROS 맵 파일을 다시 읽고 검증한다."""
    result = import_map_assets()
    imported = result["imported"]
    return {"ok": True, "count": len(imported), "maps": imported, "skipped": result["skipped"], "removed": result["removed"]}


@router.get("/map-assets/{map_id}/image.png")
def map_asset_image(map_id: str) -> Response:
    """PGM 맵 이미지를 브라우저 표시용 PNG로 변환해 반환한다."""
    asset = find_map_asset(map_id)
    return Response(
        content=cached_pgm_to_png(asset.image_path),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@router.get("/map-assets/{map_id}/map.pgm")
def map_asset_pgm(map_id: str) -> FileResponse:
    """Nav PC가 pull 할 수 있도록 ROS map.pgm 원본을 반환한다."""
    asset = find_map_asset(map_id)
    return FileResponse(
        asset.image_path,
        media_type="application/octet-stream",
        filename=f"{map_id}.pgm",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/map-assets/{map_id}/map.yaml")
def map_asset_yaml(map_id: str) -> FileResponse:
    """Nav PC가 pull 할 수 있도록 ROS map.yaml 원본을 반환한다."""
    asset = find_map_asset(map_id)
    return FileResponse(
        asset.yaml_path,
        media_type="text/yaml",
        filename=f"{map_id}.yaml",
        headers={"Cache-Control": "no-store"},
    )
