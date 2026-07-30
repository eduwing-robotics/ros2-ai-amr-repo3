from nav_app.services.route_builder import RouteBuildError, build_movement_steps, list_inventory


def test_list_inventory_has_items():
    items = list_inventory()
    assert isinstance(items, list)
    assert len(items) >= 1


def test_build_inbound_route_for_bolt():
    route = build_movement_steps("inbound", "bolt", wait_sec=0.0)
    assert route["route_type"] == "inbound"
    assert route["item"]["item_code"] == "bolt"
    assert len(route["steps"]) >= 3
    assert route["traffic_segments"]


def test_build_unknown_item_raises():
    try:
        build_movement_steps("inbound", "not_a_real_item_xyz")
        assert False, "expected RouteBuildError"
    except RouteBuildError as exc:
        assert "unknown item_name" in str(exc)


def test_build_standby_route_without_item():
    route = build_movement_steps("standby", wait_sec=0.0, return_waypoint="vehicle_1_approach")
    assert route["route_type"] == "standby"
    assert route["steps"]
