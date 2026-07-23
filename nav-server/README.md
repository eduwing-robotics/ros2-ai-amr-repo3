# Navigation Server

This workspace runs the Movement API, Nav2 helpers, robot-SBC bringup helpers,
and map/waypoint data for the AMR fleet.

## Start here

1. Read the [documentation index](docs/README.md).
2. For a real robot, follow the ordered [startup index](docs/runbook/RUNBOOK_LMS_FULL_STARTUP.md).
3. For the HTTP command contract, use the [Main Server integration contract](docs/reference/MAIN_SERVER_CONTRACT.md).

## Local verification

Run these commands from this directory:

```bash
scripts/setup_nav_server_env.sh
scripts/check_all.sh
scripts/run_nav_servers.sh --print-plan
ROS_SETUP=/opt/ros/jazzy/setup.bash scripts/run_nav_servers.sh --check
```

The setup command recreates the ignored `.venv` from tracked requirements.
`check_all.sh` runs local checks. The remaining commands print and validate the
enabled robot-server plan without starting robot motion.

## Current documentation

- [Current implementation](docs/as-built/NAV_STACK_AS_BUILT.md)
- [Repository map](docs/as-built/REPOSITORY_MAP.md)
- [Integration contract](docs/reference/MAIN_SERVER_CONTRACT.md)
- [LMS movement algorithm](docs/reference/LMS_MOVEMENT_ALGORITHM.md)
- [Robot ROS interface](docs/reference/ROS_ROBOT_INTERFACE_SPECIFICATION.md)
- [Role-based startup](docs/runbook/RUNBOOK_LMS_FULL_STARTUP.md)
- [ArUco docking protocol](docs/runbook/RUNBOOK_ARUCO_DOCKING.md)
- [Development verification](docs/runbook/DEVELOPMENT_VERIFICATION.md)

Historical plans, handoffs, commissioning records, and superseded contracts are
listed separately in the [worklog index](worklog/README.md).
