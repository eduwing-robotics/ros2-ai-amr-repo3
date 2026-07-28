# Phase 2 Runtime Validation

Use this checklist after running the simulator on a host with Docker, ROS 2, and Gazebo available.

## Environment

- Date:
- Host OS:
- Docker version:
- Command used to start simulator:

```bash
cd Simulator
WAREHOUSE_WORLD=1 docker compose up sim
```

## Required Checks

1. Container starts without process exits.
   - Evidence:

2. Gazebo publishes robot topics.

```bash
docker compose exec sim bash /workspace/Simulator/scripts/check_ros_topics.sh
```

- Result:
- Evidence:

3. Nav API reports robot and map state.

```bash
docker compose exec sim bash /workspace/Simulator/scripts/check_api.sh
```

- Result:
- Evidence:

4. Combined smoke check passes.

```bash
docker compose exec sim bash /workspace/Simulator/scripts/smoke_demo.sh
```

- Result:
- Evidence:

5. Optional movement check sends a `nav2_pose` goal.

```bash
docker compose exec sim bash -lc "SEND_GOAL=1 /workspace/Simulator/scripts/smoke_demo.sh"
```

- Goal used:
- Result:
- Evidence:

## Phase 2 Decision

- Passed / Failed:
- Blocking issue if failed:
- Required follow-up: