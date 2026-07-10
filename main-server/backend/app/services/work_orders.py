"""입고/출고 work order API — PostgreSQL tasks facade (PHASE_60/61)."""

from __future__ import annotations

from app.services.work_orders_pg import (
    cancel_work_order,
    create_work_order,
    get_work_order,
    list_work_orders,
    plan_work_order,
    preview_work_order,
    set_work_order_priority,
)

MAX_WORK_ORDER_QUANTITY = 50

__all__ = [
    "MAX_WORK_ORDER_QUANTITY",
    "cancel_work_order",
    "create_work_order",
    "preview_work_order",
    "plan_work_order",
    "get_work_order",
    "list_work_orders",
    "set_work_order_priority",
]
