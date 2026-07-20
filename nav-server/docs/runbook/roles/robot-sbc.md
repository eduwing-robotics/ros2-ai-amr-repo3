# Robot SBC Guide

Run these commands on the SBC attached to the selected robot. Replace the
placeholder paths with the installed ROS overlay paths for that SBC.

## Base bringup

From the navigation-server checkout on the SBC:

```bash
export TB3_WS_SETUP="<turtlebot3-overlay>/install/setup.bash"
ROS_DOMAIN_ID=2 WS_SETUP="$TB3_WS_SETUP" scripts/robot_sbc/start_bringup.sh
```

For the second robot, use its configured domain and stable OpenCR device path:

```bash
export TB3_WS_SETUP="<turtlebot3-overlay>/install/setup.bash"
ROS_DOMAIN_ID=5 \
USB_PORT="<opencr-by-id-device>" \
WS_SETUP="$TB3_WS_SETUP" \
scripts/robot_sbc/start_bringup.sh
```

Keep the bringup process in the foreground. On the Navigation PC, confirm that
the selected domain has a `/scan` publisher and a `/cmd_vel` subscriber before
starting navigation.

## Camera

Open a second SBC terminal after base bringup:

```bash
export TB3_WS_SETUP="<turtlebot3-overlay>/install/setup.bash"
ROS_DOMAIN_ID=2 WS_SETUP="$TB3_WS_SETUP" scripts/robot_sbc/start_camera.sh
```

Use the robot's configured domain for the second robot. The camera must publish
`/camera/image_raw/compressed`; the Vision operator verifies it from the
Navigation PC. The operating default is `camera_ros`. Use Picamera2 only as an
explicit fallback when `camera_ros` cannot start:

```bash
ROS_DOMAIN_ID=2 CAMERA_BACKEND=picamera2 \
WS_SETUP="$TB3_WS_SETUP" scripts/robot_sbc/start_camera.sh
```

The TB3_2 one-shot and camera-restart scripts follow the same policy. Their
default is `CAMERA_BACKEND=camera_ros`; set `CAMERA_BACKEND=picamera2` on the
Navigation PC only for a deliberate fallback run.

## Lift bridge

Start this for either TB1 or TB2. Use the selected robot's configured domain:

```bash
export LIFT_WS_SETUP="<lift-overlay>/install/setup.bash"
ROS_DOMAIN_ID=5 \
LIFT_WS_SETUP="$LIFT_WS_SETUP" \
LIFT_SERIAL_PORT="<lift-controller-device>" \
scripts/robot_sbc/start_lift_bridge.sh
```

TB1 uses `ROS_DOMAIN_ID=2`; TB2 uses `ROS_DOMAIN_ID=5`.

## Stop

Run the following on the SBC to stop base, camera, and lift processes:

```bash
scripts/robot_sbc/stop_stack.sh
```
