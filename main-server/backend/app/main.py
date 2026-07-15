"""LMS Control Rebuild FastAPI entrypoint."""

import asyncio
import contextlib
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import router
from app.core.config import settings
from app.db.connection import init_db, transaction
from app.db.repo_bridge import robot_repo
from app.services import person_hazard
from app.services.person_hazard_loop import person_hazard_loop
from app.services.pose_monitor import pose_event_writer_loop, pose_fallback_poller_loop, pose_watchdog_loop
from app.services.pose_runtime import pose_runtime
from app.services.runtime_map_context import get_runtime_map_context
from app.services.task_progress_poller import poll_task_progress_loop


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
    """Register enabled robots without restoring any persisted starting pose."""
    with transaction() as conn:
        rows = robot_repo(conn).list()
    context = get_runtime_map_context().to_map_state()
    pose_runtime.configure(
        [row["robot_id"] for row in rows if row.get("enabled", True)],
        context,
    )


def initialize_person_hazard_safety() -> int:
    """Hold persisted in-flight motion before any startup poller can advance it."""
    with transaction() as conn:
        return person_hazard.reconcile_startup_person_hazard_safety(conn)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작 시 PostgreSQL DB를 초기화하고 task progress poller를 띄운다."""
    from app.db.pg_connection import require_database_url
    from app.services.field_bindings import load_field_bindings

    # A missing or incomplete field binding is a deployment error, not a task
    # routing fallback.  Validate before starting background work.
    load_field_bindings()
    require_database_url()
    init_db()
    initialize_pose_runtime()
    initialize_person_hazard_safety()
    sweep_task = asyncio.create_task(poll_task_progress_loop())
    hazard_task = asyncio.create_task(person_hazard_loop())
    pose_tasks = [
        asyncio.create_task(pose_watchdog_loop()),
        asyncio.create_task(pose_event_writer_loop()),
        asyncio.create_task(pose_fallback_poller_loop()),
    ]
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

    # 컷오버 완료: React 빌드 산출물(web/dist)만 서빙한다. 개발은 vite dev(:5173)에서 한다.
    # (빌드: cd frontend/web && npm run build)
    web_dist = Path(__file__).resolve().parents[2] / "frontend" / "web" / "dist"
    if web_dist.exists():
        app.mount("/", SpaStaticFiles(directory=web_dist, html=True), name="frontend")

    return app


app = create_app()
