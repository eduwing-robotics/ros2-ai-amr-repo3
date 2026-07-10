"""LMS MVP API routes — router aggregation only."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routers.cameras import router as cameras_router
from app.api.routers.comm import router as comm_router
from app.api.routers.db_admin import router as db_admin_router
from app.api.routers.inventory import router as inventory_router
from app.api.routers.maps import router as maps_router
from app.api.routers.movement import router as movement_router
from app.api.routers.records import router as records_router
from app.api.routers.robot_commands import router as robot_commands_router
from app.api.routers.robot_poses import router as robot_poses_router
from app.api.routers.robots import router as robots_router
from app.api.routers.scenario import router as scenario_router
from app.api.routers.system import router as system_router
from app.api.routers.tasks import router as tasks_router
from app.api.routers.teleop import router as teleop_router
from app.api.routers.vision import router as vision_router
from app.api.routers.work_orders import router as work_orders_router

router = APIRouter()
router.include_router(system_router)
router.include_router(teleop_router)
router.include_router(movement_router)
router.include_router(robot_commands_router)
router.include_router(robot_poses_router)
router.include_router(cameras_router)
router.include_router(comm_router)
router.include_router(db_admin_router)
router.include_router(inventory_router)
router.include_router(maps_router)
router.include_router(records_router)
router.include_router(robots_router)
router.include_router(scenario_router)
router.include_router(tasks_router)
router.include_router(vision_router)
router.include_router(work_orders_router)
