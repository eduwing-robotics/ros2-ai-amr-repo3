"""Operational enablement, ESTOP partial-clear, and latest-pose policy tests."""

from unittest.mock import MagicMock, patch

from app import main as main_app
from app.api.routers import robots as robot_routes
from app.api.routers.system import _estop_summary
from app.db.postgres import robots as robot_repository
from app.domains.movement import router
from app.models.robots import Robot, RobotPoseUpdate, RobotUpsert


def test_estop_summary_ignores_disabled_and_marks_enabled_offline_unknown() -> None:
    robots = [
        Robot(robot_id="r1", display_name="r1", status="IDLE", enabled=True),
        Robot(robot_id="r2", display_name="r2", status="IDLE", enabled=True),
        Robot(robot_id="r3", display_name="r3", status="IDLE", enabled=False),
    ]
    summary = _estop_summary(
        robots,
        {
            "r1": {"ok": True, "robot_online": True, "is_emergency": False},
            "r2": {"ok": False, "robot_online": False, "is_emergency": True},
            "r3": {"ok": False, "robot_online": False, "is_emergency": True},
        },
    )
    assert summary == {"state": "unknown", "active_robots": [], "unknown_robots": ["r2"]}


def test_clear_estop_targets_only_enabled_online_robots() -> None:
    conn = MagicMock()
    rows = [
        {"robot_id": "r1", "enabled": True},
        {"robot_id": "r2", "enabled": True},
        {"robot_id": "r3", "enabled": False},
    ]
    health = {
        "r1": {"ok": True, "robot_online": True},
        "r2": {"ok": False, "robot_online": False},
    }
    with (
        patch.object(router.postgres_robots, "list_robots", return_value=rows),
        patch.object(router, "get_movement_health", return_value=health),
        patch.object(router.movement_client, "clear_estop", return_value={"accepted": True}) as clear,
        patch.object(router, "set_robot_emergency"),
        patch.object(router, "clear_cache"),
        patch.object(router.operational_events, "append"),
    ):
        result = router.clear_estop_all_robots(conn)

    assert [row["state"] for row in result] == ["cleared", "unknown", "disabled"]
    clear.assert_called_once_with("r1")


def test_pose_report_updates_memory_without_transaction() -> None:
    router.pose_runtime.reset()
    router.pose_runtime.configure({"r1"})
    payload = RobotPoseUpdate(
        map_id="map",
        x=1.0,
        y=2.0,
        yaw=0.5,
        source="movement",
        command_id="cmd-1",
        reported_at="2026-07-15T00:00:00Z",
    )

    with patch.object(router, "transaction") as tx:
        result = router.report_robot_pose_for_robot("r1", payload)

    tx.assert_not_called()
    assert result.message == "robot pose accepted"
    snapshot = router.pose_runtime.list_snapshots()[0]
    assert snapshot["robot_id"] == "r1"
    assert snapshot["command_id"] == "cmd-1"
    router.pose_runtime.reset()


def test_pose_list_is_memory_only() -> None:
    router.pose_runtime.reset()
    router.pose_runtime.configure({"r1"})
    router.pose_runtime.ingest("r1", {"map_id": "map", "x": 1.0, "y": 2.0}, source_kind="canonical")

    with (
        patch.object(router, "transaction") as tx,
        patch.object(router.movement_client, "robot_pose") as movement_pose,
    ):
        rows = router.list_robot_poses()

    assert len(rows) == 1
    assert rows[0].robot_id == "r1"
    tx.assert_not_called()
    movement_pose.assert_not_called()
    router.pose_runtime.reset()


def test_runtime_registry_contains_only_enabled_db_robots() -> None:
    conn = MagicMock()
    rows = [
        {"robot_id": "r1", "enabled": True},
        {"robot_id": "r2", "enabled": False},
    ]
    with (
        patch.object(main_app, "transaction") as tx,
        patch.object(main_app.postgres_robots, "list_robots", return_value=rows),
        patch.object(main_app.pose_runtime, "configure") as configure,
    ):
        tx.return_value.__enter__.return_value = conn
        main_app.initialize_pose_runtime()

    assert configure.call_args.args[0] == ["r1"]


def test_disabling_robot_removes_it_from_pose_registry() -> None:
    conn = MagicMock()
    payload = RobotUpsert(robot_id="r1", display_name="r1", enabled=False)
    with (
        patch.object(robot_routes, "transaction") as tx,
        patch.object(robot_routes.robots, "get", return_value={"enabled": True}),
        patch.object(robot_routes.robots, "disable_block_reason", return_value=None),
        patch.object(robot_routes.robots, "upsert"),
        patch.object(robot_routes.operational_events, "append"),
        patch.object(robot_routes.pose_runtime, "unregister_robot") as unregister,
    ):
        tx.return_value.__enter__.return_value = conn
        robot_routes.upsert_robot(payload)

    unregister.assert_called_once_with("r1")


def test_robot_upsert_omitted_enabled_preserves_existing_setting() -> None:
    conn = MagicMock()
    payload = RobotUpsert(robot_id="r1", display_name="r1")

    robot_repository.upsert(conn, payload.model_dump())

    assert payload.enabled is None
    sql, params = conn.execute.call_args.args
    assert "enabled = COALESCE(%s, robots.enabled)" in sql
    assert params[-1] is None
