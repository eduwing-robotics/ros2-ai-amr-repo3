from nav_app.models import MovementRouteRequest, MovementStep
from nav_app.services.route_helpers import (
    raw_route_preview,
    raw_steps_from_route_request,
    traffic_segments_from_steps,
)


def test_traffic_segments_from_steps_dedupes():
    steps = [
        MovementStep(action="nav2_pose", payload={"traffic_segments": ["inbound_lane", "warehouse_aisle"]}),
        MovementStep(action="wait", payload={"traffic_segments": ["inbound_lane"]}),
    ]
    assert traffic_segments_from_steps(steps) == ["inbound_lane", "warehouse_aisle"]


def test_raw_steps_from_coordinate_request():
    req = MovementRouteRequest(
        command_id="cmd-1",
        robot_name="tb3_1",
        x=1.0,
        y=2.0,
        yaw=0.5,
    )
    steps = raw_steps_from_route_request(req)
    assert steps is not None
    assert steps[0].action == "nav2_pose"
    assert steps[0].payload["goal"]["x"] == 1.0


def test_raw_route_preview_coordinates_mode():
    req = MovementRouteRequest(command_id="cmd-2", robot_name="tb3_1", x=1.0, y=2.0)
    steps = raw_steps_from_route_request(req)
    preview = raw_route_preview(req, steps)
    assert preview["input_mode"] == "coordinates"
    assert preview["traffic_segments"] == []
