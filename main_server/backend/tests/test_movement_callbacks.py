# 기능 책임: Movement callback 멱등성·인증·ESTOP 상태 적용을 검증한다. 비책임: 실장비의 물리 동작.
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

from app.api.routers import movement_callbacks as callback_routes
from app.domains.execution import callback_workflow
from app.domains.movement import callbacks
from app.domains.movement import router as routes
from app.domains.movement.client import MovementClientError, robot_is_emergency, set_robot_emergency
from app.main import app


class MovementStatusFreshnessTest(unittest.TestCase):
    def test_stale_pose_does_not_count_as_fresh_telemetry(self) -> None:
        self.assertFalse(
            callbacks.robot_status_is_fresh({"robot_online": True, "localized": True, "pose": {"age_sec": 30.0}})
        )

    def test_live_pose_counts_as_fresh_telemetry(self) -> None:
        self.assertTrue(
            callbacks.robot_status_is_fresh({"robot_online": True, "localized": True, "pose": {"age_sec": 0.2}})
        )


class MovementCallbackServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = MagicMock()
        self.event = MagicMock()
        self.movement = MagicMock()
        self.robot = MagicMock()
        for robot_id in ("r1", "r2", "r3"):
            set_robot_emergency(robot_id, False)

    @patch("app.domains.movement.callbacks.operational_events")
    def test_ingest_command_event_appends_and_forwards(self, operational_events) -> None:
        apply_event = MagicMock(return_value=True)
        operational_events.callback_event_exists = self.event.callback_event_exists
        payload = {"command_id": "cmd-1", "robot_name": "r1", "event": "ACCEPTED"}

        callbacks.ingest_command_event(self.conn, payload, apply_event)

        apply_event.assert_called_once_with(self.conn, payload)

    @patch("app.domains.movement.callbacks.operational_events")
    def test_duplicate_event_id_is_acknowledged_without_reapply(self, operational_events) -> None:
        apply_event = MagicMock()
        operational_events.callback_event_exists = self.event.callback_event_exists
        self.event.callback_event_exists.return_value = True
        result = callbacks.ingest_command_event(
            self.conn,
            {"command_id": "cmd-1", "robot_name": "r1", "event": "DONE", "event_id": "evt-1"},
            apply_event,
        )
        self.assertTrue(result["duplicate"])
        apply_event.assert_not_called()

    @patch("app.domains.movement.callbacks.advisory_xact_lock_for_key")
    @patch("app.domains.movement.callbacks.operational_events")
    def test_event_id_is_locked_and_task_id_is_linked(self, operational_events, advisory_lock) -> None:
        apply_event = MagicMock(return_value=True)
        operational_events.callback_event_exists.return_value = False
        payload = {
            "event_id": "exec-344:6:completed",
            "command_id": "cmd-344",
            "task_id": 344,
            "robot_name": "tb3_2",
            "event": "STEP_COMPLETED",
        }
        callbacks.ingest_command_event(self.conn, payload, apply_event)

        lock_args = advisory_lock.call_args.args
        self.assertIs(lock_args[0], self.conn)
        self.assertEqual(lock_args[1], callbacks.MOVEMENT_CALLBACK_LOCK_NAMESPACE)
        self.assertIsInstance(lock_args[2], int)
        apply_event.assert_called_once_with(self.conn, payload)

    @patch("app.domains.execution.callback_workflow.orchestrator.handle_command_event")
    @patch("app.domains.execution.callback_workflow.operational_events")
    def test_event_write_failure_does_not_advance_execution(self, operational_events, handle_event) -> None:
        operational_events.append.side_effect = RuntimeError("event write failed")

        with self.assertRaisesRegex(RuntimeError, "event write failed"):
            callback_workflow.apply_command_event(
                self.conn, {"command_id": "cmd-1", "robot_name": "r1", "event": "DONE"}
            )

        handle_event.assert_not_called()

    @patch("app.domains.movement.callbacks.pose_runtime")
    def test_ingest_robot_status_updates_pose_memory_when_localized(self, pose_runtime) -> None:
        payload = {
            "localized": True,
            "state": "navigating",
            "current_command_id": "cmd-3",
            "pose": {"x": 1.0, "y": 2.0, "yaw": 0.5, "frame_id": "map_a"},
        }

        callbacks.ingest_robot_status_pose("r3", payload)

        pose_runtime.ingest.assert_called_once()
        self.assertEqual(pose_runtime.ingest.call_args.args[0], "r3")
        self.assertEqual(pose_runtime.ingest.call_args.kwargs["source_kind"], "status")
        self.assertFalse(callbacks.robot_status_requires_event(payload))

    @patch("app.domains.movement.callbacks.pose_runtime")
    def test_localization_only_status_updates_pose_quality(self, pose_runtime) -> None:
        callbacks.ingest_robot_status_pose("r3", {"localized": False})
        pose_runtime.update_localization.assert_called_once_with("r3", False)

    @patch("app.domains.movement.callbacks.operational_events")
    def test_normal_robot_status_heartbeat_is_not_an_issue(self, operational_events) -> None:
        payload = {"state": "navigating", "localized": True}
        self.assertFalse(callbacks.robot_status_requires_event(payload))
        operational_events.append.assert_not_called()

    @patch("app.domains.movement.callbacks.operational_events")
    def test_ingest_robot_status_error_appends_latest_failure_cause(self, operational_events) -> None:
        operational_events.latest_failure_message.return_value = "step 0 nav2_pose failed"

        self.assertTrue(callbacks.robot_status_requires_event({"state": "error"}))
        callbacks.ingest_robot_status(self.conn, "r3", {"state": "error"})

        operational_events.latest_failure_message.assert_called_once_with(self.conn, "r3")
        self.assertEqual(
            operational_events.append.call_args.kwargs["message"],
            "error — 직전 실패: step 0 nav2_pose failed",
        )
        self.assertEqual(
            operational_events.append.call_args.kwargs["event_type"],
            "MOVEMENT_ROBOT_STATUS_ISSUE",
        )

    @patch("app.domains.movement.router.movement_client")
    @patch("app.domains.movement.router.operational_events")
    @patch("app.domains.movement.router.postgres_robots")
    def test_estop_all_robots_records_success_and_failure(self, robots, operational_events, movement_client) -> None:
        robots.list_robots = self.robot.list
        operational_events.append = self.event.append
        self.robot.list.return_value = [{"robot_id": "r1"}, {"robot_id": "r2"}]
        movement_client.estop.side_effect = [{"ok": True}, MovementClientError("down")]

        results = routes.estop_all_robots(self.conn)

        self.assertEqual(len(results), 2)
        self.assertTrue(results[0]["ok"])
        self.assertFalse(results[1]["ok"])
        self.assertEqual(self.event.append.call_count, 4)
        event_types = [call.kwargs["event_type"] for call in self.event.append.call_args_list]
        self.assertEqual(
            event_types,
            [
                "ROBOT_ESTOP_REQUESTED",
                "ROBOT_ESTOP_CONFIRMED",
                "ROBOT_ESTOP_REQUESTED",
                "ROBOT_ESTOP_UNCONFIRMED",
            ],
        )
        self.assertTrue(robot_is_emergency("r1"))
        self.assertTrue(robot_is_emergency("r2"))

    @patch("app.domains.movement.router.get_movement_health")
    @patch("app.domains.movement.router.movement_client")
    @patch("app.domains.movement.router.operational_events")
    @patch("app.domains.movement.router.postgres_robots")
    def test_clear_estop_all_robots_records_event(
        self, robots, operational_events, movement_client, get_movement_health
    ) -> None:
        robots.list_robots = self.robot.list
        operational_events.append = self.event.append
        self.robot.list.return_value = [{"robot_id": "r1"}]
        get_movement_health.return_value = {"r1": {"ok": True, "robot_online": True}}
        set_robot_emergency("r1", True)
        movement_client.clear_estop.return_value = {"cleared": True}

        results = routes.clear_estop_all_robots(self.conn)

        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["ok"])
        self.assertEqual(self.event.append.call_args.kwargs["event_type"], "ROBOT_CLEAR_ESTOP_CONFIRMED")
        self.assertFalse(robot_is_emergency("r1"))

    @patch("app.domains.movement.router.get_movement_health")
    @patch("app.domains.movement.router.movement_client")
    @patch("app.domains.movement.router.operational_events")
    @patch("app.domains.movement.router.postgres_robots")
    def test_failed_clear_keeps_main_emergency_latch(
        self, robots, operational_events, movement_client, get_movement_health
    ) -> None:
        robots.list_robots = self.robot.list
        operational_events.append = self.event.append
        self.robot.list.return_value = [{"robot_id": "r1"}]
        get_movement_health.return_value = {"r1": {"ok": True, "robot_online": True}}
        set_robot_emergency("r1", True)
        movement_client.clear_estop.side_effect = MovementClientError("still down")

        results = routes.clear_estop_all_robots(self.conn)

        self.assertEqual(len(results), 1)
        self.assertFalse(results[0]["ok"])
        self.assertTrue(robot_is_emergency("r1"))


@unittest.skipUnless(TestClient is not None, "httpx not installed — pip install -r requirements-dev.txt")
class MovementCallbackRouteTest(unittest.TestCase):
    def setUp(self) -> None:
        self._patches = [
            patch("app.db.connection.require_database_url"),
            patch("app.main.init_db"),
            patch("app.main.initialize_pose_runtime"),
            patch("app.main.asyncio.create_task", return_value=MagicMock()),
        ]
        for p in self._patches:
            p.start()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        for p in reversed(self._patches):
            p.stop()

    @patch("app.api.routers.movement_callbacks.transaction")
    @patch("app.api.routers.movement_callbacks.callbacks.ingest_command_event")
    def test_command_events_route_shape(self, ingest, transaction_ctx) -> None:
        conn = MagicMock()
        transaction_ctx.return_value.__enter__.return_value = conn
        payload = {"command_id": "cmd-x", "robot_name": "r1", "event": "DONE"}
        ingest.return_value = {"message": "movement command event saved"}

        res = self.client.post("/api/v1/movement/command-events", json=payload)

        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["message"], "movement command event saved")
        ingest.assert_called_once_with(conn, payload, callback_routes.callback_workflow.apply_command_event)

    @patch("app.main.transaction")
    @patch("app.main.operational_events")
    def test_command_event_requires_command_robot_and_state(self, events, transaction_ctx) -> None:
        conn = MagicMock()
        transaction_ctx.return_value.__enter__.return_value = conn
        events.should_append_callback_validation_failure.return_value = True

        res = self.client.post("/api/v1/movement/command-events", json={"task_id": 42, "event": "DONE"})

        self.assertEqual(res.status_code, 422)
        events.append.assert_called_once()
        self.assertEqual(events.append.call_args.kwargs["event_type"], "MOVEMENT_CALLBACK_VALIDATION_FAILED")

    @patch("app.api.routers.movement_callbacks.transaction")
    @patch("app.api.routers.movement_callbacks.callbacks.ingest_command_event")
    def test_callback_token_is_required_when_configured(self, ingest, transaction_ctx) -> None:
        conn = MagicMock()
        transaction_ctx.return_value.__enter__.return_value = conn
        ingest.return_value = {"message": "movement command event saved"}
        payload = {"command_id": "cmd-secure", "robot_name": "r1", "event": "RUNNING"}
        configured = MagicMock(movement_callback_token="shared-secret")
        with patch.object(routes, "settings", configured):
            denied = self.client.post("/api/v1/movement/command-events", json=payload)
            allowed = self.client.post(
                "/api/v1/movement/command-events", json=payload, headers={"X-Movement-Callback-Token": "shared-secret"}
            )
        self.assertEqual(denied.status_code, 401)
        self.assertEqual(allowed.status_code, 200)

    def test_legacy_results_route_is_removed(self) -> None:
        operation = app.openapi().get("paths", {}).get("/api/v1/movement/results", {})
        self.assertNotIn("post", operation)

    @patch("app.domains.movement.router.transaction")
    @patch("app.domains.movement.router.callbacks.ingest_robot_status")
    def test_robot_status_route_shape(self, ingest, transaction_ctx) -> None:
        conn = MagicMock()
        transaction_ctx.return_value.__enter__.return_value = conn

        res = self.client.post("/api/v1/movement/robots/tb3_1/status", json={"state": "idle"})

        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["message"], "movement robot status accepted")
        ingest.assert_not_called()
        transaction_ctx.assert_not_called()

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


def test_duplicate_robot_status_issue_is_suppressed() -> None:
    conn = MagicMock()
    with patch.object(callbacks.operational_events, "should_append_robot_status_issue", return_value=False), patch.object(
        callbacks.operational_events, "append"
    ) as append:
        saved = callbacks.ingest_robot_status(conn, "r3", {"state": "offline", "localized": False})
    assert saved is False
    append.assert_not_called()
