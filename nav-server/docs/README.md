# Navigation Documentation

This index lists documents that describe the current navigation-server system.
Historical material is intentionally separated into the [worklog index](../worklog/README.md).
Repository-wide placement and ownership rules live in the
[documentation governance guide](../../docs/DOCUMENTATION_GUIDE.md).

## System reference

- [Current implementation](as-built/NAV_STACK_AS_BUILT.md)
- [Repository map](as-built/REPOSITORY_MAP.md)
- [Package-layout decisions](adr/ADR_001_SCRIPTS_COMPATIBLE_PACKAGE_LAYOUT.md)
- [No root redirect stubs decision](adr/ADR_002_NO_ROOT_REDIRECT_STUBS.md)

## Integration contracts

- [Main Server integration contract](reference/MAIN_SERVER_CONTRACT.md)
- [LMS movement algorithm](reference/LMS_MOVEMENT_ALGORITHM.md)
- [ROS robot interface specification](reference/ROS_ROBOT_INTERFACE_SPECIFICATION.md)
- [Nav runtime profile contract](reference/NAV_RUNTIME_PROFILE_CONTRACT.md)

## Operations

- [Single follow-along cross-service field procedure](../../docs/operations/physical-e2e-checklist.md)
- [Ordered startup by role](runbook/RUNBOOK_LMS_FULL_STARTUP.md)
- [Robot SBC guide](runbook/roles/robot-sbc.md)
- [Navigation PC guide](runbook/roles/nav-pc.md)
- [Main operator guide](runbook/roles/main-operator.md)
- [Vision operator guide](runbook/roles/ai-operator.md)
- [ArUco docking protocol](runbook/RUNBOOK_ARUCO_DOCKING.md)
- [Gazebo acceptance](runbook/RUNBOOK_GAZEBO_SIMULATION.md)
- [No-hardware tests](runbook/NO_HARDWARE_TESTS.md)
- [Development verification](runbook/DEVELOPMENT_VERIFICATION.md)
- [Movement API validation checklist](runbook/API_MOVEMENT_CHECKLIST.md)
- [Runtime output policy](reference/RUNTIME_OUTPUT_POLICY.md)
