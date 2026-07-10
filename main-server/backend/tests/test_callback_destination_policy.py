"""Callback destination policy regressions (SSRF/confused-deputy)."""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.api import helpers
from app.core.config import settings as runtime_settings
from app.models.work_orders import WorkOrderCreate
from app.services import missions, robot_commands


def _settings(**changes):
    defaults = {
        "callback_base_url": "https://main.example",
        "callback_allowlist": ("https://main.example",),
        "callback_allow_http": False,
        "nohardware_mode": False,
        "nohardware_callback_allowlist": (),
    }
    defaults.update(changes)
    return replace(runtime_settings, **defaults)


def test_callback_uses_configured_base_and_ignores_user_override():
    request = MagicMock()
    request.base_url = "https://attacker.example/"
    with patch.object(helpers, "settings", _settings()), patch(
        "app.api.helpers.socket.getaddrinfo", return_value=[(0, 0, 0, "", ("8.8.8.8", 443))]
    ):
        assert helpers.callback_base_url(request, "https://169.254.169.254/latest") == "https://main.example/api/v1"
        assert helpers.command_events_callback_url() == "https://main.example/api/v1/movement/command-events"


def test_work_order_rejects_user_callback_base_url():
    with pytest.raises(ValidationError):
        WorkOrderCreate.model_validate({
            "operation": "inbound", "item_code": "BOX-A", "quantity": 1,
            "callback_base_url": "http://127.0.0.1:2375",
        })


def test_command_and_legacy_route_callbacks_ignore_supplied_destination():
    with patch.object(helpers, "settings", _settings()), patch(
        "app.api.helpers.socket.getaddrinfo", return_value=[(0, 0, 0, "", ("8.8.8.8", 443))]
    ):
        assert robot_commands.resolve_callback_url(None, "https://attacker.example") == (
            "https://main.example/api/v1/movement/command-events"
        )
        request = missions.build_goto_route_request(
            {
                "robot_id": "tb3_1",
                "x": 1.0,
                "y": 2.0,
                "callback_base_url": "https://attacker.example",
            }
        )
    assert request["callback_url"] == "https://main.example/api/v1/movement/command-events"


@pytest.mark.parametrize("base", [
    "https://user:pass@main.example",
    "https://main.example/api/v1?next=https://evil.example",
    "http://main.example",
])
def test_callback_configuration_rejects_credentials_query_and_http(base):
    with patch.object(helpers, "settings", _settings(callback_base_url=base)):
        with pytest.raises(HTTPException) as exc:
            helpers.command_events_callback_url()
    assert exc.value.status_code == 503


def test_callback_configuration_rejects_private_ipv6_and_dns_results():
    with patch.object(helpers, "settings", _settings(callback_base_url="https://[::1]")):
        with pytest.raises(HTTPException):
            helpers.command_events_callback_url()

    with patch.object(helpers, "settings", _settings(callback_base_url="https://main.example")), patch(
        "app.api.helpers.socket.getaddrinfo", return_value=[(0, 0, 0, "", ("10.0.0.8", 443))],
    ):
        with pytest.raises(HTTPException):
            helpers.command_events_callback_url()


def test_nohardware_explicit_localhost_allowlist_is_the_only_private_exception():
    configured = _settings(
        callback_base_url="http://localhost:8088",
        callback_allowlist=(),
        callback_allow_http=True,
        nohardware_mode=True,
        nohardware_callback_allowlist=("http://localhost:8088",),
    )
    with patch.object(helpers, "settings", configured):
        assert helpers.command_events_callback_url() == "http://localhost:8088/api/v1/movement/command-events"


def test_orchestrator_ignores_supplied_callback_base_url():
    from app.services import orchestrator

    task = {"task_id": 17, "status": "ASSIGNED", "assigned_robot_id": "tb3_1"}
    with patch.object(orchestrator, "_task", return_value=task), patch.object(
        orchestrator, "task_repo"
    ) as task_repo, patch.object(orchestrator, "robot_repo") as robot_repo, patch.object(
        orchestrator.evidence_runtime, "build_scenario_from_task", return_value={"map_id": "robot1_map", "steps": []}
    ), patch.object(orchestrator.field_bindings, "assert_robot_live_map", return_value={"active_map_id": "robot1_map"}
    ), patch.object(orchestrator, "plan_command_steps", return_value=[]), patch.object(
        orchestrator.orch_state, "new_orchestration", return_value={}
    ) as new_orchestration, patch.object(orchestrator.evidence_runtime, "save_orchestration"), patch.object(
        orchestrator, "dispatch_current_step", return_value="command-17"
    ), patch.object(orchestrator, "event_repo"), patch(
        "app.api.helpers.callback_base_url", return_value="https://main.example/api/v1"
    ):
        orchestrator.start_task_orchestration(MagicMock(), 17, "http://127.0.0.1:2375")

    new_orchestration.assert_called_once_with([], callback_base_url="https://main.example/api/v1")
    task_repo.return_value.set_status.assert_called_once_with(17, "RUNNING")
    robot_repo.return_value.set_task.assert_called_once_with("tb3_1", "RUNNING", 17)
