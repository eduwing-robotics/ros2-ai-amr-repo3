from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.services import inventory_ops


def _task(quantity: int = 1) -> dict[str, object]:
    return {
        "task_id": 41,
        "task_type": "INBOUND",
        "status": "RUNNING",
        "item_id": "PART-GEAR",
        "quantity": quantity,
        "from_location_id": "INBOUND_01",
        "from_floor": 1,
        "to_location_id": "STORAGE_S1",
        "to_floor": 1,
    }


def _repos(task: dict[str, object], quantities: list[int]):
    tasks = MagicMock()
    tasks.get.return_value = task
    inventory = MagicMock()
    inventory.get_quantity.side_effect = quantities
    event = MagicMock()
    return tasks, inventory, event


def test_inbound_completion_moves_present_staging_inventory() -> None:
    tasks, inventory, event = _repos(_task(), [1, 0])
    inventory.adjust.side_effect = [0, 1]

    with (
        patch.object(inventory_ops, "MvpTaskRepository", return_value=tasks),
        patch.object(inventory_ops, "MvpInventoryRepository", return_value=inventory),
        patch.object(inventory_ops, "MvpEventRepository", return_value=event),
    ):
        inventory_ops.apply_on_task_complete(MagicMock(), 41)

    assert inventory.adjust.call_args_list[0].args == ("INBOUND_01", "PART-GEAR", -1, 1)
    assert inventory.adjust.call_args_list[1].args == ("STORAGE_S1", "PART-GEAR", 1, 1)
    assert [call.kwargs["event_type"] for call in inventory.append_change_log.call_args_list] == [
        "INBOUND_STAGING_CONSUMED",
        "INBOUND_COMPLETE",
    ]
    assert tasks.append_task_log.call_args.kwargs["snapshot"]["staging_quantity_after"] == 0


def test_external_inbound_without_staging_row_keeps_existing_behavior() -> None:
    tasks, inventory, event = _repos(_task(), [0, 0])
    inventory.adjust.return_value = 1

    with (
        patch.object(inventory_ops, "MvpTaskRepository", return_value=tasks),
        patch.object(inventory_ops, "MvpInventoryRepository", return_value=inventory),
        patch.object(inventory_ops, "MvpEventRepository", return_value=event),
    ):
        inventory_ops.apply_on_task_complete(MagicMock(), 41)

    inventory.adjust.assert_called_once_with("STORAGE_S1", "PART-GEAR", 1, 1)
    assert inventory.append_change_log.call_args.kwargs["event_type"] == "INBOUND_COMPLETE"


def test_partial_staging_quantity_blocks_ambiguous_completion() -> None:
    tasks, inventory, event = _repos(_task(quantity=2), [1])

    with (
        patch.object(inventory_ops, "MvpTaskRepository", return_value=tasks),
        patch.object(inventory_ops, "MvpInventoryRepository", return_value=inventory),
        patch.object(inventory_ops, "MvpEventRepository", return_value=event),
        pytest.raises(HTTPException) as exc_info,
    ):
        inventory_ops.apply_on_task_complete(MagicMock(), 41)

    assert exc_info.value.detail == "insufficient_inbound_staging_inventory"
    inventory.adjust.assert_not_called()
