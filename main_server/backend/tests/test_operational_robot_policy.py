"""Operational enablement, ESTOP partial-clear, and latest-pose policy tests."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app.api.routers.system import _estop_summary
from app.db.postgres import robot_poses
from app.db.postgres import robots as robot_repository
from app.domains.movement import navigation, router
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


def test_pose_report_updates_latest_state_without_per_pose_event() -> None:
    conn = MagicMock()
    pose = RobotPoseUpdate(
        map_id="map",
        x=1.0,
        y=2.0,
        yaw=0.5,
        source="movement",
        command_id="cmd-1",
        reported_at="2026-07-15T00:00:00Z",
    )
    with (
        patch.object(navigation.robots, "exists", return_value=True),
        patch.object(navigation.robot_poses, "upsert_latest") as upsert,
        patch.object(navigation.robots, "touch") as touch,
    ):
        navigation.report_pose_for_robot(conn, "r1", pose)

    upsert.assert_called_once()
    assert upsert.call_args.args[1] == "r1"
    assert upsert.call_args.args[2]["command_id"] == "cmd-1"
    touch.assert_called_once_with(conn, "r1")


def test_robot_upsert_omitted_enabled_preserves_existing_setting() -> None:
    conn = MagicMock()
    payload = RobotUpsert(robot_id="r1", display_name="r1")

    robot_repository.upsert(conn, payload.model_dump())

    assert payload.enabled is None
    sql, params = conn.execute.call_args.args
    assert "enabled = COALESCE(%s, robots.enabled)" in sql
    assert params[-1] is None


def test_latest_pose_separates_source_age_from_cache_age() -> None:
    now = datetime.now(timezone.utc)
    mapped = robot_poses._map({
        "robot_id": "r1", "map_id": "map", "x": 1.0, "y": 2.0, "yaw": 0.0,
        "reported_at": now - timedelta(seconds=10),
        "received_at": now - timedelta(seconds=1),
    })

    assert 9.0 <= mapped["age_sec"] <= 11.0
    assert 0.0 <= mapped["cache_age_sec"] <= 2.0
