"""제한된 PostgreSQL DB admin 조회 서비스."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

DBML_TABLES = {
    "items",
    "robots",
    "locations",
    "inventory",
    "tasks",
    "commands",
    "evidence_events",
    "safety_stops",
    "item_change_logs",
    "task_logs",
}

INFRA_TABLES = {
    "cameras",
    "maps",
}

DB_ADMIN_TABLES = DBML_TABLES | INFRA_TABLES

READONLY_TABLES = {
    "evidence_events",
    "item_change_logs",
    "task_logs",
    "safety_stops",
}


def list_tables(conn) -> list[dict[str, Any]]:
    rows = []
    for table_name in sorted(DB_ADMIN_TABLES):
        if not table_exists(conn, table_name):
            continue
        count_row = conn.execute(f"SELECT COUNT(*) AS c FROM {table_name}").fetchone()
        count = int(count_row["c"]) if count_row else 0
        rows.append({
            "table_name": table_name,
            "row_count": count,
            "readonly": table_name in READONLY_TABLES,
            "layer": "dbml" if table_name in DBML_TABLES else "infra",
        })
    return rows


def table_schema(conn, table_name: str) -> dict[str, Any]:
    table = require_table(table_name)
    columns = []
    for row in conn.execute(
        """
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        ORDER BY ordinal_position
        """,
        (table,),
    ).fetchall():
        columns.append({
            "cid": len(columns),
            "name": row["column_name"],
            "type": row["data_type"],
            "notnull": row["is_nullable"] == "NO",
            "default": row["column_default"],
            "pk": False,
        })
    if not columns:
        raise HTTPException(status_code=404, detail="table not found")
    return {
        "table_name": table,
        "readonly": table in READONLY_TABLES,
        "layer": "dbml" if table in DBML_TABLES else "infra",
        "columns": columns,
    }


def table_rows(conn, table_name: str, limit: int = 100) -> dict[str, Any]:
    table = require_table(table_name)
    schema = table_schema(conn, table)
    order_column = preferred_order_column(schema["columns"])
    order_clause = f"ORDER BY {order_column} DESC" if order_column else ""
    safe_limit = max(1, min(limit, 500))
    cur = conn.execute(f"SELECT * FROM {table} {order_clause} LIMIT %s", (safe_limit,))
    rows = []
    for row in cur.fetchall():
        item = dict(row)
        for key, value in item.items():
            if hasattr(value, "isoformat"):
                item[key] = value.isoformat()
        rows.append(item)
    return {
        "table_name": table,
        "readonly": schema["readonly"],
        "layer": schema["layer"],
        "columns": schema["columns"],
        "rows": rows,
    }


def require_table(table_name: str) -> str:
    if table_name not in DB_ADMIN_TABLES:
        raise HTTPException(status_code=404, detail="table not available")
    return table_name


def table_exists(conn, table_name: str) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = %s
        """,
        (table_name,),
    ).fetchone()
    return row is not None


def preferred_order_column(columns: list[dict[str, Any]]) -> str | None:
    names = {column["name"] for column in columns}
    for candidate in (
        "logged_at",
        "changed_at",
        "observed_at",
        "finished_at",
        "created_at",
        "updated_at",
    ):
        if candidate in names:
            return candidate
    return None
