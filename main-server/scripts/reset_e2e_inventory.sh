#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="${1:-reset}"

if [[ "$MODE" != "reset" && "$MODE" != "--show" ]]; then
  echo "Usage: ./scripts/reset_e2e_inventory.sh [--show]" >&2
  exit 2
fi

cd "$ROOT/backend"
SF_E2E_INVENTORY_MODE="$MODE" ./.venv/bin/python <<'PY'
from __future__ import annotations

import os

from app.db.connection import transaction


PLACEMENTS = (
    (22, "INBOUND_01", 1),
    (23, "INBOUND_02", 1),
    (20, "STORAGE_S3", 1),
    (24, "STORAGE_S3", 2),
    (27, "STORAGE_S4", 1),
    (29, "STORAGE_S4", 2),
)


def print_inventory(conn) -> None:
    rows = conn.execute(
        """
        SELECT item.aruco_marker_id, inv.item_id, inv.location_id, inv.floor, inv.quantity
        FROM inventory AS inv
        JOIN items AS item ON item.id = inv.item_id
        ORDER BY item.aruco_marker_id, inv.location_id, inv.floor
        """
    ).fetchall()
    print("marker\titem\tlocation\tfloor\tquantity")
    for row in rows:
        print(
            f"A{row['aruco_marker_id']}\t{row['item_id']}\t{row['location_id']}\t"
            f"{row['floor']}\t{row['quantity']}"
        )


with transaction() as conn:
    if os.environ["SF_E2E_INVENTORY_MODE"] == "--show":
        print_inventory(conn)
        raise SystemExit(0)

    active = conn.execute(
        """
        SELECT id, status FROM tasks
        WHERE status IN ('CREATED', 'PENDING', 'QUEUED', 'ASSIGNED', 'RUNNING')
        ORDER BY id
        """
    ).fetchall()
    if active:
        summary = ", ".join(f"#{row['id']}:{row['status']}" for row in active)
        raise SystemExit(f"active tasks exist; stop or finish them before inventory reset: {summary}")

    marker_ids = tuple(marker_id for marker_id, _, _ in PLACEMENTS)
    placeholders = ", ".join(["%s"] * len(marker_ids))
    item_rows = conn.execute(
        f"SELECT id, aruco_marker_id FROM items WHERE aruco_marker_id IN ({placeholders})",
        marker_ids,
    ).fetchall()
    items_by_marker = {int(row["aruco_marker_id"]): str(row["id"]) for row in item_rows}
    missing_markers = sorted(set(marker_ids) - set(items_by_marker))
    if missing_markers:
        raise SystemExit(f"missing item marker registrations: {missing_markers}")

    required_locations = {location_id for _, location_id, _ in PLACEMENTS}
    location_placeholders = ", ".join(["%s"] * len(required_locations))
    location_rows = conn.execute(
        f"SELECT id FROM locations WHERE id IN ({location_placeholders})",
        tuple(sorted(required_locations)),
    ).fetchall()
    found_locations = {str(row["id"]) for row in location_rows}
    missing_locations = sorted(required_locations - found_locations)
    if missing_locations:
        raise SystemExit(f"missing E2E locations: {missing_locations}")

    conn.execute("DELETE FROM inventory")
    conn.executemany(
        """
        INSERT INTO inventory (item_id, location_id, floor, quantity)
        VALUES (%s, %s, %s, 1)
        """,
        [
            (items_by_marker[marker_id], location_id, floor)
            for marker_id, location_id, floor in PLACEMENTS
        ],
    )
    print_inventory(conn)
PY
