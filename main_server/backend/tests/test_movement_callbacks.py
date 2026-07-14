"""Characterization tests for movement callback and estop wiring."""

from __future__ import annotations

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

from app.domains.movement import router as callbacks
from app.domains.movement.client import MovementClientError, robot_is_emergency, set_robot_emergency
from app.main import app


class MovementCallbackServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = MagicMock()
        self.event = MagicMock()
        self.movement = MagicMock()
        self.robot = MagicMock()
        for robot_id in ("r1", "r2", "r3"):
            set_robot_emergency(robot_id, False)

    @patch("app.domains.movement.router.orchestrator_service.handle_command_event")
    @patch("app.domains.movement.router.event_repo")
    def test_ingest_command_event_appends_and_forwards(self, event_repo, handle_event) -> None:
        event_repo.return_value = self.event
        payload = {"command_id": "cmd-1", "robot_name": "r1", "event": "ACCEPTED"}

        callbacks.ingest_command_event(self.conn, payload)

        self.event.append.assert_called_once()
        kwargs = self.event.append.call_args.kwargs
        self.assertEqual(kwargs["event_type"], "MOVEMENT_COMMAND_ACCEPTED")
        self.assertEqual(kwargs["robot_id"], "r1")
        self.assertEqual(kwargs["command_id"], "cmd-1")
        handle_event.assert_called_once_with(self.conn, payload)

    @patch("app.domains.movement.router.orchestrator_service.handle_command_event")
    @patch("app.domains.movement.router.event_repo")
    def test_duplicate_event_id_is_acknowledged_without_reapply(self, event_repo, handle_event) -> None:
        event_repo.return_value = self.event
        self.event.callback_event_exists.return_value = True
        result = callbacks.ingest_command_event(
            self.conn,
            {"command_id": "cmd-1", "robot_name": "r1", "event": "DONE", "event_id": "evt-1"},
        )
        self.assertTrue(result["duplicate"])
        self.event.append.assert_not_called()
        handle_event.assert_not_called()

    @patch("app.domains.movement.router.movement_repo")
    @patch("app.domains.movement.router.event_repo")
    def test_ingest_result_records_when_command_id_present(self, event_repo, movement_repo) -> None:
        event_repo.return_value = self.event
        movement_repo.return_value = self.movement
        payload = {"command_id": "cmd-2", "robot_id": "r2", "result": "SUCCESS", "message": "done"}

        callbacks.ingest_result(self.conn, payload)

        self.event.append.assert_called_once()
        self.assertEqual(self.event.append.call_args.kwargs["event_type"], "MOVEMENT_RESULT_SUCCESS")
        self.movement.record_result.assert_called_once_with("cmd-2", "SUCCESS", "done", payload)

    @patch("app.domains.movement.router.movement_repo")
    @patch("app.domains.movement.router.event_repo")
    def test_ingest_result_skips_record_without_command_id(self, event_repo, movement_repo) -> None:
        event_repo.return_value = self.event
        movement_repo.return_value = self.movement

        callbacks.ingest_result(self.conn, {"result": "FAILED"})

        self.event.append.assert_called_once()
        self.movement.record_result.assert_not_called()

    @patch("app.domains.movement.router.report_pose_for_robot")
    @patch("app.domains.movement.router.event_repo")
    def test_ingest_robot_status_updates_pose_when_localized(self, event_repo, report_pose) -> None:
        event_repo.return_value = self.event
        payload = {
            "localized": True,
            "state": "navigating",
            "current_command_id": "cmd-3",
            "pose": {"x": 1.0, "y": 2.0, "yaw": 0.5, "frame_id": "map_a"},
        }

        callbacks.ingest_robot_status(self.conn, "r3", payload)

        report_pose.assert_called_once()
        self.event.append.assert_called_once()
        self.assertEqual(self.event.append.call_args.kwargs["event_type"], "MOVEMENT_ROBOT_STATUS")

    @patch("app.domains.movement.router.movement_client")
    @patch("app.domains.movement.router.event_repo")
    @patch("app.domains.movement.router.robot_repo")
    def test_estop_all_robots_records_success_and_failure(self, robot_repo, event_repo, movement_client) -> None:
        robot_repo.return_value = self.robot
        event_repo.return_value = self.event
        self.robot.list.return_value = [{"robot_id": "r1"}, {"robot_id": "r2"}]
        movement_client.estop.side_effect = [{"ok": True}, MovementClientError("down")]

        results = callbacks.estop_all_robots(self.conn)

        self.assertEqual(len(results), 2)
        self.assertTrue(results[0]["ok"])
        self.assertFalse(results[1]["ok"])
        self.assertEqual(self.event.append.call_count, 1)
        self.assertEqual(self.event.append.call_args.kwargs["event_type"], "ROBOT_ESTOP")
        self.assertTrue(robot_is_emergency("r1"))
        self.assertTrue(robot_is_emergency("r2"))

    @patch("app.domains.movement.router.movement_client")
    @patch("app.domains.movement.router.event_repo")
    @patch("app.domains.movement.router.robot_repo")
    def test_clear_estop_all_robots_records_event(self, robot_repo, event_repo, movement_client) -> None:
        robot_repo.return_value = self.robot
        event_repo.return_value = self.event
        self.robot.list.return_value = [{"robot_id": "r1"}]
        set_robot_emergency("r1", True)
        movement_client.clear_estop.return_value = {"cleared": True}

        results = callbacks.clear_estop_all_robots(self.conn)

        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["ok"])
        self.assertEqual(self.event.append.call_args.kwargs["event_type"], "ROBOT_CLEAR_ESTOP")
        self.assertFalse(robot_is_emergency("r1"))

    @patch("app.domains.movement.router.movement_client")
    @patch("app.domains.movement.router.event_repo")
    @patch("app.domains.movement.router.robot_repo")
    def test_failed_clear_keeps_main_emergency_latch(self, robot_repo, event_repo, movement_client) -> None:
        robot_repo.return_value = self.robot
        event_repo.return_value = self.event
        self.robot.list.return_value = [{"robot_id": "r1"}]
        set_robot_emergency("r1", True)
        movement_client.clear_estop.side_effect = MovementClientError("still down")

        results = callbacks.clear_estop_all_robots(self.conn)

        self.assertEqual(len(results), 1)
        self.assertFalse(results[0]["ok"])
        self.assertTrue(robot_is_emergency("r1"))


@unittest.skipUnless(TestClient is not None, "httpx not installed — pip install -r requirements-dev.txt")
class MovementCallbackRouteTest(unittest.TestCase):
    def setUp(self) -> None:
        self._patches = [
            patch("app.db.connection.require_database_url"),
            patch("app.db.connection.init_db"),
            patch("app.main.asyncio.create_task", return_value=MagicMock()),
        ]
        for p in self._patches:
            p.start()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        for p in reversed(self._patches):
            p.stop()

    @patch("app.domains.movement.router.transaction")
    @patch("app.domains.movement.router.ingest_command_event")
    def test_command_events_route_shape(self, ingest, transaction_ctx) -> None:
        conn = MagicMock()
        transaction_ctx.return_value.__enter__.return_value = conn
        payload = {"command_id": "cmd-x", "robot_name": "r1", "event": "DONE"}
        ingest.return_value = {"message": "movement command event saved"}

        res = self.client.post("/api/v1/movement/command-events", json=payload)

        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["message"], "movement command event saved")
        ingest.assert_called_once_with(conn, payload)

    def test_command_event_requires_command_robot_and_state(self) -> None:
        res = self.client.post("/api/v1/movement/command-events", json={"task_id": 42, "event": "DONE"})
        self.assertEqual(res.status_code, 422)

    @patch("app.domains.movement.router.transaction")
    @patch("app.domains.movement.router.ingest_command_event")
    def test_callback_token_is_required_when_configured(self, ingest, transaction_ctx) -> None:
        conn = MagicMock()
        transaction_ctx.return_value.__enter__.return_value = conn
        ingest.return_value = {"message": "movement command event saved"}
        payload = {"command_id": "cmd-secure", "robot_name": "r1", "event": "RUNNING"}
        configured = MagicMock(movement_callback_token="shared-secret")
        with patch.object(callbacks, "settings", configured):
            denied = self.client.post("/api/v1/movement/command-events", json=payload)
            allowed = self.client.post(
                "/api/v1/movement/command-events", json=payload, headers={"X-Movement-Callback-Token": "shared-secret"}
            )
        self.assertEqual(denied.status_code, 401)
        self.assertEqual(allowed.status_code, 200)

    @patch("app.domains.movement.router.transaction")
    @patch("app.domains.movement.router.ingest_result")
    def test_results_route_shape(self, ingest, transaction_ctx) -> None:
        conn = MagicMock()
        transaction_ctx.return_value.__enter__.return_value = conn
        ingest.return_value = {"message": "movement result saved"}

        res = self.client.post(
            "/api/v1/movement/results", json={"command_id": "c1", "robot_name": "r1", "result": "OK"}
        )

        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["message"], "movement result saved")
        ingest.assert_called_once()

    @patch("app.domains.movement.router.transaction")
    @patch("app.domains.movement.router.ingest_robot_status")
    def test_robot_status_route_shape(self, ingest, transaction_ctx) -> None:
        conn = MagicMock()
        transaction_ctx.return_value.__enter__.return_value = conn

        res = self.client.post("/api/v1/movement/robots/tb3_1/status", json={"state": "idle"})

        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["message"], "movement robot status saved")
        ingest.assert_called_once_with(conn, "tb3_1", {"state": "idle"})

    @patch("app.domains.movement.router.transaction")
    @patch("app.domains.movement.router.estop_all_robots")
    def test_estop_route_shape(self, estop_all, transaction_ctx) -> None:
        conn = MagicMock()
        transaction_ctx.return_value.__enter__.return_value = conn
        estop_all.return_value = [{"robot_id": "r1", "ok": True, "response": {}}]

        res = self.client.post("/api/v1/robot/estop")

        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["robots"][0]["robot_id"], "r1")

    @patch("app.domains.movement.router.transaction")
    @patch("app.domains.movement.router.clear_estop_all_robots")
    def test_clear_estop_route_shape(self, clear_all, transaction_ctx) -> None:
        conn = MagicMock()
        transaction_ctx.return_value.__enter__.return_value = conn
        clear_all.return_value = [{"robot_id": "r1", "ok": True, "response": {}}]

        res = self.client.post("/api/v1/robot/clear_estop")

        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["robots"][0]["robot_id"], "r1")

    @patch("app.domains.movement.router.transaction")
    @patch("app.domains.movement.router.clear_estop_all_robots")
    def test_clear_estop_route_reports_partial_failure(self, clear_all, transaction_ctx) -> None:
        conn = MagicMock()
        transaction_ctx.return_value.__enter__.return_value = conn
        clear_all.return_value = [{"robot_id": "r1", "ok": False, "error": "unreachable"}]

        res = self.client.post("/api/v1/robot/clear_estop")

        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["robots"][0]["error"], "unreachable")


if __name__ == "__main__":
    unittest.main()
