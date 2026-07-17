"""Recovery API request validation must fail closed before dispatch."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routers import tasks


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(tasks.router, prefix="/api/v1")
    return TestClient(app)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {
            "cargo_state": "LOADED",
            "strategy": "safe_move",
            "checks": {"site_clear": True, "pose_ok": True},
        },
        {
            "cargo_state": "LOADED",
            "strategy": "safe_move",
            "checks": {"site_clear": True, "pose_ok": True, "cargo_ok": False},
        },
    ],
)
def test_execute_rejects_empty_missing_or_false_safety_checks(
    client: TestClient,
    payload: dict,
) -> None:
    with patch.object(tasks.recovery_service, "execute_recovery") as execute:
        response = client.post("/api/v1/tasks/7/recovery/execute", json=payload)

    assert response.status_code == 422
    execute.assert_not_called()


def test_execute_accepts_all_required_safety_checks_when_true(client: TestClient) -> None:
    payload = {
        "cargo_state": "LOADED",
        "strategy": "safe_move",
        "checks": {"site_clear": True, "pose_ok": True, "cargo_ok": True},
    }
    conn = object()
    transaction = MagicMock()
    transaction.return_value.__enter__.return_value = conn

    with (
        patch.object(tasks, "transaction", transaction),
        patch.object(tasks.recovery_service, "execute_recovery", return_value={"accepted": True}) as execute,
    ):
        response = client.post("/api/v1/tasks/7/recovery/execute", json=payload)

    assert response.status_code == 200
    assert response.json() == {"accepted": True}
    execute.assert_called_once_with(
        conn,
        7,
        cargo_state="LOADED",
        strategy="safe_move",
        checks=payload["checks"],
    )


def test_execute_accepts_original_task_resume_strategy(client: TestClient) -> None:
    payload = {
        "cargo_state": "EMPTY",
        "strategy": "resume_task",
        "checks": {"site_clear": True, "pose_ok": True, "cargo_ok": True},
    }
    conn = object()
    transaction = MagicMock()
    transaction.return_value.__enter__.return_value = conn

    with (
        patch.object(tasks, "transaction", transaction),
        patch.object(tasks.recovery_service, "execute_recovery", return_value={"accepted": True}) as execute,
    ):
        response = client.post("/api/v1/tasks/7/recovery/execute", json=payload)

    assert response.status_code == 200
    execute.assert_called_once_with(
        conn,
        7,
        cargo_state="EMPTY",
        strategy="resume_task",
        checks=payload["checks"],
    )
