"""Map metadata and map asset routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse

from app.db.connection import transaction
from app.db.repo_bridge import event_repo, map_repo
from app.models.schemas import ApiMessage, MapRecord, MapUpsert
from app.security import require_admin
from app.services.map_assets import find_map_asset, import_map_assets, list_map_asset_records, pgm_to_png
from app.services.movement_map_sync import sync_from_movement
from app.services.runtime_map_context import get_runtime_map_context, overlay_nav_dims

router = APIRouter(tags=["maps"])


@router.get("/maps", response_model=list[MapRecord])
def list_maps() -> list[MapRecord]:
    """관제 맵 목록. runtime context overlay로 좌표계 진단을 포함한다."""
    ctx = get_runtime_map_context()
    with transaction() as conn:
        rows = [overlay_nav_dims(m, ctx) for m in map_repo(conn).list()]
    return [MapRecord(**m) for m in rows]


@router.get("/map-assets")
def list_map_assets() -> list[dict]:
    """maps 폴더의 ROS map.yaml/map.pgm 파일 목록을 반환한다."""
    return list_map_asset_records()


@router.post("/maps/import-folder", dependencies=[Depends(require_admin)])
def import_maps_from_folder() -> dict:
    """maps 폴더의 ROS 맵을 DB maps 테이블에 등록/갱신한다."""
    with transaction() as conn:
        result = import_map_assets(conn)
    imported = result["imported"]
    return {"ok": True, "count": len(imported), "maps": imported, "skipped": result["skipped"], "removed": result["removed"]}


@router.post("/maps/sync-from-movement", dependencies=[Depends(require_admin)])
def sync_maps_from_movement() -> dict:
    """Movement active map-state로 maps/ 자산·DB를 동기화한다 (권장: Nav2와 동일 map_id·메타)."""
    with transaction() as conn:
        return sync_from_movement(conn)


@router.get("/map-assets/{map_id}/image.png")
def map_asset_image(map_id: str) -> Response:
    """PGM 맵 이미지를 브라우저 표시용 PNG로 변환해 반환한다."""
    asset = find_map_asset(map_id)
    return Response(content=pgm_to_png(asset.image_path), media_type="image/png", headers={"Cache-Control": "no-store"})


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


@router.post("/maps", response_model=ApiMessage, dependencies=[Depends(require_admin)])
def upsert_map(payload: MapUpsert) -> ApiMessage:
    """맵 메타데이터를 생성하거나 수정한다."""
    with transaction() as conn:
        map_repo(conn).upsert(payload.model_dump())
        event_repo(conn).append(
            event_type="DB_MAP_UPSERT",
            message=f"map upserted: {payload.map_id}",
            payload=payload.model_dump(),
        )
    return ApiMessage(message="map saved")


@router.delete("/maps/{map_id}", response_model=ApiMessage, dependencies=[Depends(require_admin)])
def delete_map(map_id: str) -> ApiMessage:
    """맵 메타데이터를 삭제한다."""
    with transaction() as conn:
        deleted = map_repo(conn).delete(map_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="map not found")
        event_repo(conn).append(event_type="DB_MAP_DELETE", message=f"map deleted: {map_id}")
    return ApiMessage(message="map deleted")
