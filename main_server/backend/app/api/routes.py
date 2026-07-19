"""LMS MVP API routes — router aggregation only."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routers.comm import router as comm_router
from app.api.routers.map_runtime import router as map_runtime_router
from app.api.routers.movement_callbacks import router as movement_callbacks_router
from app.api.routers.robots import router as robots_router
from app.api.routers.scenario import router as scenario_router
from app.api.routers.system import router as system_router
from app.domains.admin.router import router as db_admin_router
from app.domains.execution.router import router as tasks_router
from app.domains.maps.router import router as maps_router
from app.domains.movement.router import router as movement_router
from app.domains.records.router import router as records_router
from app.domains.vision.router import router as vision_router
from app.domains.vision.sources_router import router as cameras_router
from app.domains.warehouse.router import router as inventory_router
from app.domains.work_orders.router import router as work_orders_router

router = APIRouter()
router.include_router(system_router)
router.include_router(movement_router)
router.include_router(movement_callbacks_router)
router.include_router(cameras_router)
router.include_router(comm_router)
router.include_router(db_admin_router)
router.include_router(inventory_router)
router.include_router(maps_router)
router.include_router(map_runtime_router)
router.include_router(records_router)
router.include_router(robots_router)
router.include_router(scenario_router)
router.include_router(tasks_router)
router.include_router(vision_router)
router.include_router(work_orders_router)
