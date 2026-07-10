# Navigation Startup Index

Use one terminal per foreground process. Do not send a movement command until
each applicable readiness check has passed.

## Ordered startup

1. **Robot SBC:** start the robot base, camera, and—when configured—the lift bridge. See the [Robot SBC guide](roles/robot-sbc.md).
2. **Navigation PC:** start Nav2, the Movement API, and any required domain bridges. Confirm API and ROS readiness. See the [Navigation PC guide](roles/nav-pc.md).
3. **Vision operator:** start the ArUco detector for each required robot and confirm that the current marker is visible. See the [Vision operator guide](roles/ai-operator.md).
4. **Main operator:** verify the selected robot endpoint and health state, then submit and monitor commands according to the [Main operator guide](roles/main-operator.md).

For the docking-specific command sequence and stop conditions, use the [ArUco docking protocol](RUNBOOK_ARUCO_DOCKING.md).

## Shutdown order

1. Stop or abort active movement through the Main Server contract.
2. Stop foreground detector, bridge, and Nav2 processes on the Navigation PC.
3. Stop the Movement API with `scripts/nav_ops.sh stop`.
4. Stop the robot-SBC stack with `scripts/robot_sbc/stop_stack.sh`.
