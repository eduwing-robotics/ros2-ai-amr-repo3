"""Read-only DB admin viewer routes."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.db.connection import transaction
from app.services.db_admin import list_tables as db_list_tables
from app.services.db_admin import table_rows as db_table_rows
from app.services.db_admin import table_schema as db_table_schema

router = APIRouter(prefix="/db", tags=["db-admin"])


@router.get("/tables")
def list_db_tables() -> list[dict]:
    """DB admin용 테이블 목록. allowlist에 포함된 테이블만 반환한다."""
    with transaction() as conn:
        return db_list_tables(conn)


@router.get("/tables/{table_name}/schema")
def get_db_table_schema(table_name: str) -> dict:
    """DB admin용 컬럼 메타데이터."""
    with transaction() as conn:
        return db_table_schema(conn, table_name)


@router.get("/tables/{table_name}/rows")
def get_db_table_rows(table_name: str, limit: int = Query(default=100, ge=1, le=500)) -> dict:
    """DB admin용 row 조회. 기본은 읽기 전용 viewer다."""
    with transaction() as conn:
        return db_table_rows(conn, table_name, limit=limit)
