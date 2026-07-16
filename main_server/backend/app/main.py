"""LMS Control Rebuild FastAPI entrypoint."""

import asyncio
import contextlib
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import router
from app.core.config import settings
from app.db.connection import init_db, transaction
from app.db.postgres import operational_events
from app.db.postgres import robots as postgres_robots
from app.domains.movement.client import set_robot_emergency
from app.domains.execution.poller import poll_task_progress_loop
from app.domains.movement.pose_monitor import (
    pose_event_writer_loop,
    pose_fallback_poller_loop,
    pose_watchdog_loop,
)
from app.domains.movement.pose_runtime import pose_runtime
from app.domains.safety.hazard_loop import person_hazard_loop


class SpaStaticFiles(StaticFiles):
    """SPA 클라이언트 라우팅 지원: 존재하지 않는 경로는 index.html 로 폴백한다.

    React Router 의 딥링크(/tasks/editor 등)를 새로고침/직접접속해도 200 으로 앱이 뜬다.
    API 경로(/api, /health)는 라우터가 먼저 처리하므로 여기로 오지 않는다.
    """

    async def get_response(self, path: str, scope):  # type: ignore[override]
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                return await super().get_response("index.html", scope)
            raise


def initialize_pose_runtime() -> None:
    """시작 시 enabled 로봇만 읽는다. 이전 DB pose는 복구하지 않는다."""
    with transaction() as conn:
        robot_rows = postgres_robots.list_robots(conn)
    robot_ids = [row["robot_id"] for row in robot_rows if row.get("enabled", True)]
    pose_runtime.configure(
        robot_ids,
        {"map_id": settings.movement_active_map_id},
    )


def initialize_estop_runtime() -> None:
    """Restore safety latches from persisted lifecycle events after a restart."""
    with transaction() as conn:
        robot_rows = postgres_robots.list_robots(conn)
        robot_ids = [row["robot_id"] for row in robot_rows if row.get("enabled", True)]
        states = operational_events.latest_estop_states(conn, robot_ids)
    latched_states = {
        "stop_requested",
        "stop_confirmed",
        "stop_unconfirmed",
        "clear_requested",
        "clear_unconfirmed",
    }
    for robot_id in robot_ids:
        set_robot_emergency(robot_id, states.get(robot_id) in latched_states)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작 시 PostgreSQL DB를 초기화하고 task progress poller를 띄운다."""
    from app.db.connection import require_database_url

    require_database_url()
    init_db()
    initialize_pose_runtime()
    initialize_estop_runtime()
    sweep_task = asyncio.create_task(poll_task_progress_loop())
    hazard_task = asyncio.create_task(person_hazard_loop())
    pose_tasks = [
        asyncio.create_task(pose_watchdog_loop()),
        asyncio.create_task(pose_event_writer_loop()),
        asyncio.create_task(pose_fallback_poller_loop()),
    ]
    app.state.sweep_task = sweep_task
    app.state.hazard_task = hazard_task
    app.state.pose_tasks = pose_tasks
    try:
        yield
    finally:
        for task in [hazard_task, sweep_task, *pose_tasks]:
            task.cancel()
        for task in [hazard_task, sweep_task, *pose_tasks]:
            with contextlib.suppress(asyncio.CancelledError):
                await task


def create_app() -> FastAPI:
    """FastAPI 앱 생성."""
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router, prefix=settings.api_prefix)

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "service": settings.app_name}

    @app.get("/ready")
    def ready() -> dict:
        try:
            with transaction() as conn:
                conn.execute("SELECT 1").fetchone()
        except Exception as exc:
            raise HTTPException(status_code=503, detail="database unavailable") from exc
        sweep_task = getattr(app.state, "sweep_task", None)
        hazard_task = getattr(app.state, "hazard_task", None)
        if sweep_task is not None and sweep_task.done():
            raise HTTPException(status_code=503, detail="task progress poller stopped")
        if settings.person_hazard_enabled and hazard_task is not None and hazard_task.done():
            raise HTTPException(status_code=503, detail="person hazard poller stopped")
        pose_tasks = getattr(app.state, "pose_tasks", [])
        if any(task.done() for task in pose_tasks):
            raise HTTPException(status_code=503, detail="pose runtime worker stopped")
        return {"ok": True, "service": settings.app_name, "database": "ready", "workers": "ready"}

    # 컷오버 완료: React 빌드 산출물(web/dist)만 서빙한다. 개발은 vite dev(:5173)에서 한다.
    # (빌드: cd frontend/web && npm run build)
    web_dist = Path(__file__).resolve().parents[2] / "frontend" / "web" / "dist"
    if web_dist.exists():
        app.mount("/", SpaStaticFiles(directory=web_dist, html=True), name="frontend")

    return app


app = create_app()
