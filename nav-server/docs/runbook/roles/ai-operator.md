# Vision Operator Guide

Run the ArUco detector on the Navigation PC only after the robot SBC publishes
the selected camera topic. The detector is advisory input to Movement; it does
not publish motion commands.

## Start and verify

Use a dedicated terminal for each detector. The command stays in the
foreground.

```bash
cd <repo-root>/nav-server
scripts/nav_ops.sh detector1
```

Use `scripts/nav_ops.sh detector2` for `tb3_burger_02`. In another Navigation
PC terminal, verify the selected robot's camera and detector readiness:

```bash
cd <repo-root>/nav-server
scripts/nav_ops.sh check1
curl -fsS "http://127.0.0.1:8001/movement-api/v1/aruco/latest?marker_id=<marker-id>"
```

`check1` reports the camera topic alongside API and ROS readiness. Use
`check2` and port `8002` for the second robot.

## Stop condition

Do not authorize an ArUco-dependent docking command when the camera topic has
no publisher, the detector exits, or the required marker is absent or stale.
Follow the [ArUco docking runbook](../RUNBOOK_ARUCO_DOCKING.md) for command
sequence and recovery.
