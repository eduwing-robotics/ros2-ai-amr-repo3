# Navigation Documentation

This index lists documents that describe the current navigation-server system.
Historical material is intentionally separated into the [worklog index](../worklog/README.md).

## System reference

- [Current implementation](as-built/NAV_STACK_AS_BUILT.md)
- [Repository map](as-built/REPOSITORY_MAP.md)
- [Package-layout decisions](adr/ADR_001_SCRIPTS_COMPATIBLE_PACKAGE_LAYOUT.md)
- [No root redirect stubs decision](adr/ADR_002_NO_ROOT_REDIRECT_STUBS.md)

## Integration contracts

- [Main Server integration contract](reference/MAIN_SERVER_CONTRACT.md)
- [LMS movement algorithm](reference/LMS_MOVEMENT_ALGORITHM.md)
- [ROS robot interface specification](reference/ROS_ROBOT_INTERFACE_SPECIFICATION.md)

## Operations

- [Ordered startup by role](runbook/RUNBOOK_LMS_FULL_STARTUP.md)
- [Robot SBC guide](runbook/roles/robot-sbc.md)
- [Navigation PC guide](runbook/roles/nav-pc.md)
- [Main operator guide](runbook/roles/main-operator.md)
- [Vision operator guide](runbook/roles/ai-operator.md)
- [ArUco docking protocol](runbook/RUNBOOK_ARUCO_DOCKING.md)
- [Gazebo acceptance](runbook/RUNBOOK_GAZEBO_SIMULATION.md)
- [No-hardware tests](runbook/NO_HARDWARE_TESTS.md)
- [Development verification](runbook/DEVELOPMENT_VERIFICATION.md)
- [Runtime output policy](runbook/RUNTIME_OUTPUT_POLICY.md)
