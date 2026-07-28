# Phase 4 LMS Integration Validation

Use this checklist after Phase 2 has passed and the LMS/Main backend can run on the same host or reach the simulator host.

## Main Backend Environment

Start Main/LMS with Movement API URLs pointing at the simulator Nav APIs.

```bash
LMS_MOVEMENT_CLIENT_MODE=http \
LMS_MOVEMENT_ACTIVE_MAP_ID=robot1_map \
LMS_MOVEMENT_BASE_URLS=tb3_1=http://localhost:8001/movement-api/v1,tb3_2=http://localhost:8002/movement-api/v1 \
./start.sh
```

If Main runs outside the simulator host, replace `localhost` with the simulator host address.

## Required Checks

1. Simulator Nav API is up.

```bash
docker compose exec sim bash /workspace/Simulator/scripts/check_multi_api.sh
```

- Result:
- Evidence:

2. Main can read Movement map/nav state.

```bash
bash scripts/smoke_lms_integration.sh
```

- Result:
- Evidence:

3. Main dry-run route preview through `/api/v1/robot-commands` succeeds.

- Result:
- Evidence:

4. Optional command dispatch reaches Gazebo/Nav2.

```bash
SEND_COMMAND=1 bash scripts/smoke_lms_integration.sh
```

- Result:
- Evidence:

5. UI confirms map pose/command status.

- Page/view:
- Result:
- Evidence:

## Phase 4 Decision

- Passed / Failed:
- Blocking issue if failed:
- Required follow-up: