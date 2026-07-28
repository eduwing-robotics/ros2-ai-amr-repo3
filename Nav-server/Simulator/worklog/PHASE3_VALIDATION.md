# Phase 3 Runtime Validation

Use this checklist after Phase 2 has passed on a host with Docker, ROS 2, and Gazebo available.

## Environment

- Date:
- Host OS:
- Docker version:
- Command used to start simulator:

```bash
cd Simulator
MULTI_NAV_API=1 WAREHOUSE_WORLD=1 docker compose up sim
```

## Required Checks

1. Phase 3 static config passes.

```bash
python scripts/validate_phase3_config.py
```

- Result:
- Evidence:

2. Both Nav API ports are reachable.

```bash
docker compose exec sim bash /workspace/Simulator/scripts/check_multi_api.sh
```

- Result:
- Evidence:

3. Robot 1 simulation topics are available in ROS_DOMAIN_ID=2.

```bash
docker compose exec sim bash /workspace/Simulator/scripts/check_ros_topics.sh
```

- Result:
- Evidence:

4. Domain bridge package is available in the container.

```bash
docker compose exec sim bash -lc "source /opt/ros/jazzy/setup.bash && ros2 pkg prefix domain_bridge"
```

- Result:
- Evidence:

5. Multi-robot Gazebo spawn strategy decision.

- Namespace-based / separate simulator / domain bridge only:
- Decision reason:
- Required follow-up:

## Phase 3 Decision

- Passed / Failed:
- Blocking issue if failed:
- Required follow-up: