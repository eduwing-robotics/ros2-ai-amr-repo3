"""Characterization tests for movement callback and estop wiring."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

try:
    from fastapi.testclient import TestClient
except ImportError:
    TestClient = None  # type: ignore[misc, assignment]

from app.core.config import settings
from app.main import app
from app.security import sign_headers
from app.services import movement_callbacks as callbacks
from app.services.movement import (
    MovementClientError,
    robot_emergency_state,
    robot_is_emergency,
    set_robot_emergency,
)


class MovementCallbackServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = MagicMock()
        self.event = MagicMock()
        self.movement = MagicMock()
        self.robot = MagicMock()
        for robot_id in ("r1", "r2", "r3"):
            set_robot_emergency(robot_id, False)

    @patch("app.services.movement_callbacks.orchestrator_service.handle_command_event")
    @patch("app.services.movement_callbacks.event_repo")
    def test_ingest_command_event_appends_but_unknown_command_does_not_advance(self, event_repo, handle_event) -> None:
        event_repo.return_value = self.event
        payload = {"command_id": "cmd-1", "robot_name": "r1", "event": "ACCEPTED"}

        callbacks.ingest_command_event(self.conn, payload)

        self.event.append.assert_called_once()
        kwargs = self.event.append.call_args.kwargs
        self.assertEqual(kwargs["event_type"], "MOVEMENT_COMMAND_ACCEPTED")
        self.assertEqual(kwargs["robot_id"], "r1")
        self.assertEqual(kwargs["command_id"], "cmd-1")
        handle_event.assert_not_called()

    @patch("app.services.movement_callbacks.movement_repo")
    @patch("app.services.movement_callbacks.event_repo")
    def test_ingest_result_records_when_command_id_present(self, event_repo, movement_repo) -> None:
        event_repo.return_value = self.event
        movement_repo.return_value = self.movement
        payload = {"command_id": "cmd-2", "robot_id": "r2", "result": "SUCCESS", "message": "done"}

        callbacks.ingest_result(self.conn, payload)

        self.event.append.assert_called_once()
        self.assertEqual(self.event.append.call_args.kwargs["event_type"], "MOVEMENT_RESULT_SUCCESS")
        self.movement.record_result.assert_called_once_with("cmd-2", "SUCCESS", "done", payload)

    @patch("app.services.movement_callbacks.movement_repo")
    @patch("app.services.movement_callbacks.event_repo")
    def test_ingest_result_skips_record_without_command_id(self, event_repo, movement_repo) -> None:
        event_repo.return_value = self.event
        movement_repo.return_value = self.movement

        callbacks.ingest_result(self.conn, {"result": "FAILED"})

        self.event.append.assert_called_once()
        self.movement.record_result.assert_not_called()

    @patch("app.services.movement_callbacks.evidence_repo")
    @patch("app.services.movement_callbacks.task_repo")
    def test_recovery_active_command_callback_is_orchestration_relevant(
        self,
        task_repo,
        evidence_repo,
    ) -> None:
        task_repo.return_value.get.return_value = {
            "task_id": 42,
            "status": "RUNNING",
            "assigned_robot_id": "r1",
            "preset_snapshot": {
                "_orchestration": {
                    "phase": "RECOVERY_RUNNING",
                    "recovery": {"active_command_id": "cmd-recovery"},
                    "step_index": 0,
                    "steps": [
                        {
                            "status": "dispatched",
                            "command_id": "cmd-interrupted",
                        }
                    ],
                }
            },
        }

        assert callbacks._matches_active_orchestration(
            self.conn,
            {
                "task_id": 42,
                "robot_name": "r1",
                "command_id": "cmd-recovery",
            },
        )
        assert not callbacks._matches_active_orchestration(
            self.conn,
            {
                "task_id": 42,
                "robot_name": "r1",
                "command_id": "cmd-other",
            },
        )
        evidence_repo.return_value.get_orchestration.assert_not_called()

    @patch("app.services.movement_callbacks.task_repo")
    def test_dispatching_cancel_callback_is_orchestration_relevant(self, task_repo) -> None:
        task_repo.return_value.get.return_value = {
            "task_id": 42,
            "status": "RUNNING",
            "assigned_robot_id": "r1",
            "preset_snapshot": {
                "_orchestration": {
                    "phase": "CANCEL_REQUESTED",
                    "stop_request": {"command_id": "cmd-dispatching"},
                    "step_index": 0,
                    "steps": [
                        {
                            "status": "dispatching",
                            "command_id": "cmd-dispatching",
                        }
                    ],
                }
            },
        }

        assert callbacks._matches_active_orchestration(
            self.conn,
            {
                "task_id": 42,
                "robot_name": "r1",
                "command_id": "cmd-dispatching",
            },
        )

    @patch("app.services.movement_callbacks.event_repo")
    def test_ingest_robot_status_records_issue_without_updating_pose(self, event_repo) -> None:
        event_repo.return_value = self.event
        payload = {
            "localized": True,
            "state": "navigating",
            "current_command_id": "cmd-3",
            "pose": {"x": 1.0, "y": 2.0, "yaw": 0.5, "frame_id": "map_a"},
        }

        callbacks.ingest_robot_status(self.conn, "r3", payload)

        self.event.append.assert_called_once()
        self.assertEqual(self.event.append.call_args.kwargs["event_type"], "MOVEMENT_ROBOT_STATUS")

    @patch("app.services.movement_callbacks.movement_client")
    @patch("app.services.movement_callbacks.event_repo")
    @patch("app.services.movement_callbacks.robot_repo")
    def test_estop_all_robots_records_success_and_failure(self, robot_repo, event_repo, movement_client) -> None:
        robot_repo.return_value = self.robot
        event_repo.return_value = self.event
        self.robot.list.return_value = [{"robot_id": "r1"}, {"robot_id": "r2"}]
        movement_client.estop.side_effect = [{"ok": True}, MovementClientError("down")]

        results = callbacks.estop_all_robots(self.conn)

        self.assertEqual(len(results), 2)
        self.assertTrue(results[0]["ok"])
        self.assertFalse(results[1]["ok"])
        self.assertEqual(self.event.append.call_count, 2)
        self.assertEqual(
            [call.kwargs["event_type"] for call in self.event.append.call_args_list],
            ["ROBOT_ESTOP", "ROBOT_ESTOP_UNKNOWN"],
        )
        self.assertTrue(robot_is_emergency("r1"))
        self.assertIsNone(robot_emergency_state("r2"))

    @patch("app.services.movement_callbacks.movement_client")
    @patch("app.services.movement_callbacks.event_repo")
    @patch("app.services.movement_callbacks.robot_repo")
    def test_estop_all_robots_continues_after_unexpected_and_invalid_results(
        self,
        robot_repo,
        event_repo,
        movement_client,
    ) -> None:
        robot_repo.return_value = self.robot
        event_repo.return_value = self.event
        self.robot.list.return_value = [{"robot_id": "r1"}, {"robot_id": "r2"}, {"robot_id": "r3"}]

        def estop(robot_id: str):
            self.assertGreaterEqual(self.conn.commit.call_count, 1)
            if robot_id == "r1":
                raise RuntimeError("unexpected movement failure")
            if robot_id == "r2":
                return ["invalid"]
            return {"message": "stopped"}

        movement_client.estop.side_effect = estop
        with patch(
            "app.services.person_hazard.mark_running_tasks_needs_attention",
            return_value=1,
        ) as hold:
            results = callbacks.estop_all_robots(self.conn)

        hold.assert_called_once_with(self.conn, reason="operator_estop")
        self.assertEqual([row["robot_id"] for row in results], ["r1", "r2", "r3"])
        self.assertEqual([row["ok"] for row in results], [False, False, True])
        self.assertEqual([row["state"] for row in results], ["unknown", "unknown", "active"])
        self.assertIsNone(robot_emergency_state("r1"))
        self.assertIsNone(robot_emergency_state("r2"))
        self.assertTrue(robot_is_emergency("r3"))
        self.assertEqual(
            [call.kwargs["event_type"] for call in self.event.append.call_args_list],
            ["ROBOT_ESTOP_UNKNOWN", "ROBOT_ESTOP_UNKNOWN", "ROBOT_ESTOP"],
        )

    @patch("app.services.movement_callbacks.movement_client")
    @patch("app.services.movement_callbacks.event_repo")
    @patch("app.services.movement_callbacks.robot_repo")
    def test_estop_all_robots_continues_after_audit_write_failure(
        self,
        robot_repo,
        event_repo,
        movement_client,
    ) -> None:
        robot_repo.return_value = self.robot
        event_repo.return_value = self.event
        self.robot.list.return_value = [{"robot_id": "r1"}, {"robot_id": "r2"}]
        movement_client.estop.return_value = {"message": "stopped"}
        self.event.append.side_effect = [RuntimeError("audit unavailable"), None]

        with patch(
            "app.services.person_hazard.mark_running_tasks_needs_attention",
            return_value=1,
        ):
            results = callbacks.estop_all_robots(self.conn)

        self.assertEqual([row["ok"] for row in results], [True, True])
        self.assertEqual(movement_client.estop.call_count, 2)
        self.conn.rollback.assert_called_once_with()

    @patch("app.services.movement_callbacks.movement_client")
    @patch("app.services.movement_callbacks.event_repo")
    @patch("app.services.movement_callbacks.robot_repo")
    def test_estop_all_robots_attempts_every_robot_when_hold_persistence_fails(
        self,
        robot_repo,
        event_repo,
        movement_client,
    ) -> None:
        robot_repo.return_value = self.robot
        event_repo.return_value = self.event
        self.robot.list.return_value = [{"robot_id": "r1"}, {"robot_id": "r2"}]
        movement_client.estop.return_value = {"message": "stopped"}

        with (
            patch(
                "app.services.person_hazard.mark_running_tasks_needs_attention",
                side_effect=RuntimeError("hold database unavailable"),
            ),
            self.assertRaisesRegex(RuntimeError, "hold database unavailable"),
        ):
            callbacks.estop_all_robots(self.conn)

        self.assertEqual(movement_client.estop.call_count, 2)
        self.conn.rollback.assert_called()

    @patch("app.services.movement_callbacks.get_movement_health")
    @patch("app.services.movement_callbacks.movement_client")
    @patch("app.services.movement_callbacks.event_repo")
    @patch("app.services.movement_callbacks.robot_repo")
    def test_clear_estop_all_robots_records_event(
        self, robot_repo, event_repo, movement_client, get_movement_health,
    ) -> None:
        robot_repo.return_value = self.robot
        event_repo.return_value = self.event
        self.robot.list.return_value = [{"robot_id": "r1"}]
        get_movement_health.return_value = {"r1": {"ok": True, "robot_online": True}}
        set_robot_emergency("r1", True)
        movement_client.clear_estop.return_value = {"cleared": True}

        results = callbacks.clear_estop_all_robots(self.conn)

        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["ok"])
        self.assertEqual(self.event.append.call_args.kwargs["event_type"], "ROBOT_CLEAR_ESTOP")
        self.assertFalse(robot_is_emergency("r1"))

    @patch("app.services.movement_callbacks.get_movement_health")
    @patch("app.services.movement_callbacks.movement_client")
    @patch("app.services.movement_callbacks.safety_stop_repo")
    @patch("app.services.movement_callbacks.event_repo")
    @patch("app.services.movement_callbacks.robot_repo")
    def test_clear_estop_includes_disabled_registered_robot(
        self,
        robot_repo,
        event_repo,
        safety_stop_repo,
        movement_client,
        get_movement_health,
    ) -> None:
        robot_repo.return_value = self.robot
        event_repo.return_value = self.event
        safety_stop_repo.return_value.list_active.return_value = []
        self.robot.list.return_value = [
            {"robot_id": "r1", "enabled": True},
            {"robot_id": "r2", "enabled": False},
        ]
        get_movement_health.return_value = {
            "r1": {"ok": True, "robot_online": True},
            "r2": {"ok": True, "robot_online": True},
        }
        movement_client.clear_estop.side_effect = [{"cleared": True}, {"cleared": True}]

        results = callbacks.clear_estop_all_robots(self.conn)

        get_movement_health.assert_called_once_with(["r1", "r2"], force=True)
        self.assertEqual(
            [call.args[0] for call in movement_client.clear_estop.call_args_list],
            ["r1", "r2"],
        )
        self.assertEqual([row["state"] for row in results], ["cleared", "cleared"])

    @patch("app.services.movement_callbacks.get_movement_health")
    @patch("app.services.movement_callbacks.movement_client")
    @patch("app.services.movement_callbacks.safety_stop_repo")
    @patch("app.services.movement_callbacks.event_repo")
    @patch("app.services.movement_callbacks.robot_repo")
    def test_disabled_offline_robot_remains_unknown_and_blocks_global_clear(
        self,
        robot_repo,
        event_repo,
        safety_stop_repo,
        movement_client,
        get_movement_health,
    ) -> None:
        safety = MagicMock()
        robot_repo.return_value = self.robot
        event_repo.return_value = self.event
        safety_stop_repo.return_value = safety
        self.robot.list.return_value = [
            {"robot_id": "r1", "enabled": True},
            {"robot_id": "r2", "enabled": False},
        ]
        get_movement_health.return_value = {
            "r1": {"ok": True, "robot_online": True},
            "r2": {"ok": False, "robot_online": False},
        }
        movement_client.clear_estop.return_value = {"cleared": True}

        results = callbacks.clear_estop_all_robots(self.conn)

        movement_client.clear_estop.assert_called_once_with("r1")
        self.assertEqual(results[1]["state"], "unknown")
        self.assertFalse(results[1]["attempted"])
        safety.list_active.assert_not_called()

    @patch("app.services.movement_callbacks.get_movement_health")
    @patch("app.services.movement_callbacks.movement_client")
    @patch("app.services.movement_callbacks.event_repo")
    @patch("app.services.movement_callbacks.robot_repo")
    def test_failed_clear_keeps_main_emergency_latch(
        self, robot_repo, event_repo, movement_client, get_movement_health,
    ) -> None:
        robot_repo.return_value = self.robot
        event_repo.return_value = self.event
        self.robot.list.return_value = [{"robot_id": "r1"}]
        get_movement_health.return_value = {"r1": {"ok": True, "robot_online": True}}
        set_robot_emergency("r1", True)
        movement_client.clear_estop.side_effect = MovementClientError("still down")

        results = callbacks.clear_estop_all_robots(self.conn)

        self.assertEqual(len(results), 1)
        self.assertFalse(results[0]["ok"])
        self.assertEqual(results[0]["state"], "unknown")
        self.assertTrue(robot_is_emergency("r1"))

    @patch("app.services.movement_callbacks.get_movement_health")
    @patch("app.services.movement_callbacks.movement_client")
    @patch("app.services.movement_callbacks.event_repo")
    @patch("app.services.movement_callbacks.robot_repo")
    def test_failed_clear_promotes_remote_active_snapshot_to_main_latch(
        self, robot_repo, event_repo, movement_client, get_movement_health,
    ) -> None:
        robot_repo.return_value = self.robot
        event_repo.return_value = self.event
        self.robot.list.return_value = [{"robot_id": "r1"}]
        get_movement_health.return_value = {
            "r1": {
                "ok": True,
                "robot_online": True,
                "is_emergency": True,
                "estop_state": "active",
            }
        }
        movement_client.clear_estop.side_effect = MovementClientError("still down")

        results = callbacks.clear_estop_all_robots(self.conn)

        self.assertEqual(results[0]["state"], "unknown")
        self.assertTrue(robot_is_emergency("r1"))

    @patch("app.services.movement_callbacks.get_movement_health")
    @patch("app.services.movement_callbacks.movement_client")
    @patch("app.services.movement_callbacks.event_repo")
    @patch("app.services.movement_callbacks.robot_repo")
    def test_failed_clear_from_clear_snapshot_becomes_unknown(
        self, robot_repo, event_repo, movement_client, get_movement_health,
    ) -> None:
        robot_repo.return_value = self.robot
        event_repo.return_value = self.event
        self.robot.list.return_value = [{"robot_id": "r1"}]
        get_movement_health.return_value = {
            "r1": {
                "ok": True,
                "robot_online": True,
                "is_emergency": False,
                "estop_state": "clear",
            }
        }
        movement_client.clear_estop.side_effect = MovementClientError("still down")

        results = callbacks.clear_estop_all_robots(self.conn)

        self.assertEqual(results[0]["state"], "unknown")
        self.assertIsNone(robot_emergency_state("r1"))


    @patch("app.services.movement_callbacks.get_movement_health")
    @patch("app.services.movement_callbacks.movement_client")
    @patch("app.services.movement_callbacks.safety_stop_repo")
    @patch("app.services.movement_callbacks.event_repo")
    @patch("app.services.movement_callbacks.robot_repo")
    def test_clear_estop_all_robots_closes_active_safety_stops_only_after_all_success(
        self, robot_repo, event_repo, safety_stop_repo, movement_client, get_movement_health,
    ) -> None:
        safety = MagicMock()
        robot_repo.return_value = self.robot
        event_repo.return_value = self.event
        safety_stop_repo.return_value = safety
        self.robot.list.return_value = [{"robot_id": "r1"}, {"robot_id": "r2"}]
        get_movement_health.return_value = {
            "r1": {"ok": True, "robot_online": True},
            "r2": {"ok": True, "robot_online": True},
        }
        movement_client.clear_estop.side_effect = [{"cleared": True}, {"cleared": True}]
        safety.list_active.return_value = [{"id": 10, "status": "OPEN"}, {"id": 11, "status": "HOLDING"}]

        results = callbacks.clear_estop_all_robots(self.conn)

        self.assertTrue(all(row["ok"] for row in results))
        safety.close.assert_any_call(10)
        safety.close.assert_any_call(11)
        close_events = [call.kwargs for call in self.event.append.call_args_list if call.kwargs.get("event_type") == "SAFETY_STOPS_CLOSED"]
        self.assertEqual(close_events[0]["payload"], {"stop_ids": [10, 11]})

    @patch("app.services.movement_callbacks.get_movement_health")
    @patch("app.services.movement_callbacks.movement_client")
    @patch("app.services.movement_callbacks.safety_stop_repo")
    @patch("app.services.movement_callbacks.event_repo")
    @patch("app.services.movement_callbacks.robot_repo")
    def test_clear_estop_partial_failure_keeps_active_safety_stops_open(
        self, robot_repo, event_repo, safety_stop_repo, movement_client, get_movement_health,
    ) -> None:
        safety = MagicMock()
        robot_repo.return_value = self.robot
        event_repo.return_value = self.event
        safety_stop_repo.return_value = safety
        self.robot.list.return_value = [{"robot_id": "r1"}, {"robot_id": "r2"}]
        get_movement_health.return_value = {
            "r1": {"ok": True, "robot_online": True},
            "r2": {"ok": True, "robot_online": True},
        }
        movement_client.clear_estop.side_effect = [{"cleared": True}, MovementClientError("still down")]
        safety.list_active.return_value = [{"id": 10, "status": "OPEN"}]

        results = callbacks.clear_estop_all_robots(self.conn)

        self.assertFalse(all(row["ok"] for row in results))
        safety.list_active.assert_not_called()
        safety.close.assert_not_called()
        self.assertFalse(any(call.kwargs.get("event_type") == "SAFETY_STOPS_CLOSED" for call in self.event.append.call_args_list))


@unittest.skipUnless(TestClient is not None, "httpx not installed — pip install -r requirements-dev.txt")
class MovementCallbackRouteTest(unittest.TestCase):
    def setUp(self) -> None:
        object.__setattr__(settings, "movement_hmac_secret", "test-main-nav-secret")
        object.__setattr__(settings, "operator_token", "test-operator-token")
        self._patches = [
            patch("app.db.pg_connection.require_database_url"),
            patch("app.db.connection.init_db"),
            patch("app.main.asyncio.create_task", return_value=MagicMock()),
        ]
        for p in self._patches:
            p.start()
        self.client = TestClient(app)

    @staticmethod
    def _signed(path: str, payload: dict) -> tuple[bytes, dict[str, str]]:
        body = json.dumps(payload, separators=(",", ":")).encode()
        return body, {"content-type": "application/json", **sign_headers("test-main-nav-secret", "POST", path, body)}

    def tearDown(self) -> None:
        self.client.close()
        for p in reversed(self._patches):
            p.stop()

    @patch("app.api.routers.movement.transaction")
    @patch("app.api.routers.movement.callbacks.ingest_command_event")
    def test_command_events_route_shape(self, ingest, transaction_ctx) -> None:
        conn = MagicMock()
        transaction_ctx.return_value.__enter__.return_value = conn
        payload = {"command_id": "cmd-x", "robot_name": "r1", "event": "DONE"}

        body, headers = self._signed("/api/v1/movement/command-events", payload)
        res = self.client.post("/api/v1/movement/command-events", content=body, headers=headers)

        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["message"], "movement command event saved")
        ingest.assert_called_once_with(conn, payload)

    @patch("app.api.routers.movement.transaction")
    @patch("app.api.routers.movement.callbacks.ingest_result")
    def test_results_route_shape(self, ingest, transaction_ctx) -> None:
        conn = MagicMock()
        transaction_ctx.return_value.__enter__.return_value = conn

        payload = {"command_id": "c1", "result": "OK"}
        body, headers = self._signed("/api/v1/movement/results", payload)
        res = self.client.post("/api/v1/movement/results", content=body, headers=headers)

        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["message"], "movement result saved")
        ingest.assert_called_once()

    @patch("app.api.routers.movement.transaction")
    @patch("app.api.routers.movement.callbacks.ingest_robot_status")
    def test_robot_status_route_shape(self, ingest, transaction_ctx) -> None:

        payload = {"state": "idle"}
        body, headers = self._signed("/api/v1/movement/robots/tb3_1/status", payload)
        res = self.client.post("/api/v1/movement/robots/tb3_1/status", content=body, headers=headers)

        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["message"], "movement robot status accepted")
        ingest.assert_not_called()
        transaction_ctx.assert_not_called()

    @patch("app.api.routers.movement.transaction")
    @patch("app.api.routers.movement.callbacks.ingest_robot_status")
    def test_robot_issue_status_is_persisted(
        self, ingest, transaction_ctx,
    ) -> None:
        conn = MagicMock()
        transaction_ctx.return_value.__enter__.return_value = conn

        payload = {"state": "fault"}
        body, headers = self._signed("/api/v1/movement/robots/tb3_1/status", payload)
        res = self.client.post(
            "/api/v1/movement/robots/tb3_1/status",
            content=body,
            headers=headers,
        )

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["message"], "movement robot status issue saved")
        ingest.assert_called_once_with(conn, "tb3_1", {**payload, "pose": None})

    @patch("app.api.routers.movement.transaction")
    @patch("app.api.routers.movement.callbacks.estop_all_robots")
    def test_estop_route_shape(self, estop_all, transaction_ctx) -> None:
        conn = MagicMock()
        transaction_ctx.return_value.__enter__.return_value = conn
        estop_all.return_value = [{"robot_id": "r1", "ok": True, "response": {}}]

        res = self.client.post("/api/v1/robot/estop", headers={"Authorization": "Bearer test-operator-token"})

        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["robots"][0]["robot_id"], "r1")

    @patch("app.api.routers.movement.transaction")
    @patch("app.api.routers.movement.callbacks.clear_estop_all_robots")
    def test_clear_estop_route_shape(self, clear_all, transaction_ctx) -> None:
        conn = MagicMock()
        transaction_ctx.return_value.__enter__.return_value = conn
        clear_all.return_value = [{"robot_id": "r1", "ok": True, "response": {}}]

        res = self.client.post("/api/v1/robot/clear_estop", headers={"Authorization": "Bearer test-operator-token"})

        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["robots"][0]["robot_id"], "r1")


    @patch("app.api.routers.movement.transaction")
    @patch("app.api.routers.movement.callbacks.clear_estop_all_robots")
    def test_clear_estop_route_reports_partial_failure(self, clear_all, transaction_ctx) -> None:
        conn = MagicMock()
        transaction_ctx.return_value.__enter__.return_value = conn
        clear_all.return_value = [
            {
                "robot_id": "r1",
                "ok": False,
                "attempted": True,
                "state": "unknown",
                "error": "unreachable",
            }
        ]

        res = self.client.post("/api/v1/robot/clear_estop", headers={"Authorization": "Bearer test-operator-token"})

        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["state"], "partial")
        self.assertTrue(body["partial"])
        self.assertEqual(body["unknown_robots"], ["r1"])
        self.assertEqual(body["robots"][0]["error"], "unreachable")


if __name__ == "__main__":
    unittest.main()
