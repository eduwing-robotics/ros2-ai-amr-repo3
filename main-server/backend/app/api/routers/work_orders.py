"""Work order routes for inbound/outbound operations."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from app.api.helpers import callback_base_url
from app.db.connection import transaction, write_transaction
from app.models.schemas import (
    WorkOrder,
    WorkOrderCreate,
    WorkOrderPreview,
    WorkOrderPreviewRequest,
    WorkOrderPriorityUpdate,
)
from app.security import require_operator
from app.services import work_orders as work_order_service

router = APIRouter(tags=["work-orders"])


@router.get("/work-orders", response_model=list[WorkOrder])
def list_work_orders(
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[WorkOrder]:
    """입고/출고 업무 요청 목록."""
    with transaction() as conn:
        return [WorkOrder(**order) for order in work_order_service.list_work_orders(conn, limit=limit, status=status)]


@router.get("/work-orders/{order_id}", response_model=WorkOrder)
def get_work_order(order_id: int) -> WorkOrder:
    """입고/출고 업무 요청 상세."""
    with transaction() as conn:
        return WorkOrder(**work_order_service.get_work_order(conn, order_id))


@router.post("/work-orders/{order_id}/cancel", response_model=WorkOrder, dependencies=[Depends(require_operator)])
def cancel_work_order(order_id: int) -> WorkOrder:
    """예약/배정 상태의 입출고 업무 요청을 원자적으로 취소한다."""
    with write_transaction() as conn:
        return WorkOrder(**work_order_service.cancel_work_order(conn, order_id))


@router.post("/work-orders/{order_id}/priority", response_model=WorkOrder, dependencies=[Depends(require_operator)])
def set_work_order_priority(order_id: int, payload: WorkOrderPriorityUpdate) -> WorkOrder:
    """대기 작업오더의 우선순위를 조정한다(높을수록 먼저 배정)."""
    with write_transaction() as conn:
        return WorkOrder(**work_order_service.set_work_order_priority(conn, order_id, payload.priority))


@router.post("/work-orders/preview", response_model=WorkOrderPreview, dependencies=[Depends(require_operator)])
def preview_work_order(payload: WorkOrderPreviewRequest) -> WorkOrderPreview:
    """품목·수량 기반 슬롯·존 계획 미리보기 (work order/task 미생성)."""
    with transaction() as conn:
        return WorkOrderPreview(**work_order_service.preview_work_order(conn, payload.model_dump()))


@router.post("/work-orders", response_model=WorkOrder, dependencies=[Depends(require_operator)])
def create_work_order(payload: WorkOrderCreate, request: Request) -> WorkOrder:
    """품목/수량 기반 입고/출고 요청을 task/mission으로 변환한다."""
    resolved_callback = callback_base_url(request)
    with write_transaction() as conn:
        return WorkOrder(**work_order_service.create_work_order(
            conn,
            payload.model_dump(),
            callback_base_url=resolved_callback,
        ))
