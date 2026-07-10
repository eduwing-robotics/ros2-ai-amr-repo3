# Main Operator Guide

Use the Movement API endpoint for the selected robot only after the Navigation
PC and Vision operator have completed their readiness checks.

## Select and verify the endpoint

Set the selected API base URL and inspect its health response:

```bash
export NAV_BASE="http://<nav-host>:8001"
curl -fsS "$NAV_BASE/movement-api/v1/health" | python3 -m json.tool
```

Before submitting a command, confirm that the response identifies the intended
robot and reports `command_accepting: true`, `localized: true`, `nav2_ready:
true`, `dry_run: false`, and no emergency stop.

## Submit and monitor work

Use the [Main Server integration contract](../../reference/MAIN_SERVER_CONTRACT.md)
for the request schema, command kinds, callback rules, and response states.
Use the [LMS movement algorithm](../../reference/LMS_MOVEMENT_ALGORITHM.md) for
the required sequence of `leave_dock`, `move_to_point`, `dock_transfer`, and
`aruco_align` commands.

Poll the command endpoint until it reaches its documented terminal state:

```bash
curl -fsS "$NAV_BASE/robot-commands/<command-id>" | python3 -m json.tool
```

## Stop condition

Do not dispatch the next command when health reports an emergency stop, a
localization or navigation readiness failure, a traffic conflict, or a command
state other than the expected terminal state. Follow the recovery rules in the
integration contract.
