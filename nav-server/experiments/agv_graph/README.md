# AGV Graph Experiment

This bundle is an isolated, non-production experiment for an AGV-style 4-neighbor graph planner and orthogonal follower. It is not wired into the Movement API dispatch contract and must not be used as production runtime evidence.

## Contents

- `agv_grid_planner.py` - 4-neighbor grid planning primitives and motion segment generation.
- `agv_graph_builder.py` - waypoint graph loading, building, and validation helpers.
- `agv_orthogonal_follower.py` - ROS 2 follower that executes cardinal rotate/drive segments.
- `validate_agv_graph.py` - map and graph validator using follower-compatible inflation.
- `launch/agv_follower.launch.py` - experiment launch file.
- `config/agv_follower.yaml` - experiment follower parameters.
- `map/agv_waypoint_graph.yaml` - experiment waypoint graph.

## Validate

Inspect the validator options:

```bash
python3 experiments/agv_graph/validate_agv_graph.py --help
```

Run the current graph against the current map:

```bash
python3 experiments/agv_graph/validate_agv_graph.py \
  --map-yaml map/robot2_map.yaml \
  --graph experiments/agv_graph/map/agv_waypoint_graph.yaml
```

As of 2026-07-30, the full validation command runs but reports `graph_errors=36`
against `map/robot2_map.yaml`. Treat this as experiment evidence, not a runtime
approval.

## Launch

```bash
source /opt/ros/jazzy/setup.bash
ros2 launch ./experiments/agv_graph/launch/agv_follower.launch.py --show-args
```

`--show-args` verifies launch-file resolution without starting the follower. Remove
that flag only for a controlled ROS 2 experiment session.
