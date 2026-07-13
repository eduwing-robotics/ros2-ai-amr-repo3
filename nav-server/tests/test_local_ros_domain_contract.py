from nav_app.config import loader


def test_local_nav_domain_does_not_change_public_robot_domain(monkeypatch):
    monkeypatch.setattr(loader, "active_robot_profile", lambda: {"ros_domain_id": 2})
    monkeypatch.setenv("NAV_LOCAL_ROS_DOMAIN_ID", "42")
    monkeypatch.setenv("ROS_DOMAIN_ID", "42")

    assert loader.current_ros_domain_id() == 2
    assert loader.process_ros_domain_id() == 42
    assert loader.ensure_process_domain_matches_profile() == 42


def test_local_nav_domain_mismatch_fails_closed(monkeypatch):
    monkeypatch.setattr(loader, "active_robot_profile", lambda: {"ros_domain_id": 2})
    monkeypatch.setenv("NAV_LOCAL_ROS_DOMAIN_ID", "42")
    monkeypatch.setenv("ROS_DOMAIN_ID", "2")

    try:
        loader.ensure_process_domain_matches_profile()
    except RuntimeError as exc:
        assert "NAV_LOCAL_ROS_DOMAIN_ID=42" in str(exc)
    else:
        raise AssertionError("mismatched local ROS domain must fail")
