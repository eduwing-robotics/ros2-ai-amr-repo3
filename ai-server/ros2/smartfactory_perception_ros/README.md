# smartfactory_perception_ros

Thin ROS2 camera snapshot adapter for the SmartFactory AI Server.

## Boundary

- Subscribes to ROS camera topics as either:
  - raw `sensor_msgs/Image`, or
  - compressed `sensor_msgs/CompressedImage`.
- Encodes/posts each newly received frame at most once.
- POSTs snapshots to AI Server `POST /api/v1/detect/image`.
- Does **not** run inference.
- Does **not** make WMS decisions.
- Does **not** depend on YOLO/Torch.

It also includes a passive central-PC ArUco pose monitor for docking tuning:

- Subscribes to raw or compressed ROS camera topics.
- Reuses AI Server pure logic (`app.detectors` + `app.docking`) to compute
  marker pose, docking error, FPS, marker-lost and stale state.
- Logs advisory-only correction values for sign/gain tuning.
- Creates no command publishers and **never publishes `/cmd_vel`**.

For TurtleBot3 Pi Camera streams, prefer compressed transport. In live testing,
`/camera/image_raw/compressed` was ~30 Hz while `/camera/image_raw` was ~13 Hz.

## Build/test

```bash
source /opt/ros/jazzy/setup.bash
cd /home/codelab/turtlebot3_ws
colcon build --symlink-install --packages-select smartfactory_perception_ros
colcon test --packages-select smartfactory_perception_ros --event-handlers console_direct+
```

## Launch directly

Global camera/raw example:

```bash
source /opt/ros/jazzy/setup.bash
source /home/codelab/turtlebot3_ws/install/setup.bash
ros2 launch smartfactory_perception_ros ai_snapshot_clients.launch.py \
  use_ai_snapshot_clients:=true \
  use_global_camera:=true \
  use_robot_picams:=false \
  ai_server_url:=http://127.0.0.1:8100
```

Robot PiCam/compressed example for the current un-namespaced robot camera launch:

```bash
ros2 run smartfactory_perception_ros image_snapshot_client --ros-args \
  -p source_id:=tb3_1_picam \
  -p image_topic:=/camera/image_raw/compressed \
  -p image_transport:=compressed \
  -p ai_server_url:=http://127.0.0.1:8100 \
  -p snapshot_period_sec:=0.5 \
  -p request_timeout_sec:=1.0 \
  -p emit:=false
```


## Lane C vision frame gateway

`vision_frame_gateway` is the safe Lane C sidecar. It subscribes to a camera
image topic, POSTs latest frames to AI Server `POST /api/v1/vision/frame`, and
can optionally trigger `POST /api/v1/vision/worker/tick` before publishing safe
overlay/evidence topics:

- overlay image: `/sf/vision/sources/{source_id}/overlay/compressed`
- evidence JSON: `/sf/vision/events` (`std_msgs/msg/String`)

It rejects unsafe input/publish topics, creates no motion publishers, and never
publishes `/cmd_vel` or calls Nav2 actions.

Direct Robot1 domain-2 smoke example, using the temporary camera launch topic:

```bash
source /opt/ros/jazzy/setup.bash
source /home/codelab/turtlebot3_ws/install/setup.bash
ros2 launch smartfactory_perception_ros vision_frame_gateway.launch.py \
  use_vision_frame_gateway:=true \
  use_tb3_1_picam:=true \
  tb3_1_picam_image_topic:=/camera/image_raw/compressed \
  ai_server_url:=http://127.0.0.1:8100 \
  process_with_worker_tick:=true \
  force_worker_tick:=true \
  publish_overlay:=true \
  publish_evidence:=true
```

Domain-bridge/default central topics stay registry-aligned:
`/tb3_1/camera/image_raw/compressed` and
`/tb3_2/camera/image_raw/compressed`. The direct `/camera/...` override is only
for a passive Robot1 check before the domain bridge is running.

The launch file is disabled by default and each source must be explicitly
enabled. The allowlist seed is installed at
`share/smartfactory_perception_ros/config/lane_c_domain_bridge_allowlist.yaml`.

## D1 read-only AI overlay stream bridge

`vision_overlay_stream_bridge` is the D1 browser-view bridge for AI-included
overlay video. It subscribes only to allowlisted
`sensor_msgs/msg/CompressedImage` overlay topics and serves those frames as an
MJPEG browser stream. It has no publish endpoints, no ROS publishers, no service
clients, and no `/cmd_vel`/Nav2/teleop/parameter surface.

Allowed sources and default overlay topics:

| source | overlay topic |
|---|---|
| `global_cam_01` | `/sf/vision/sources/global_cam_01/overlay/compressed` |
| `tb3_1_picam` | `/sf/vision/sources/tb3_1_picam/overlay/compressed` |
| `tb3_2_picam` | `/sf/vision/sources/tb3_2_picam/overlay/compressed` |

Launch example after `vision_frame_gateway publish_overlay:=true` is running:

```bash
source /opt/ros/jazzy/setup.bash
source /home/codelab/Desktop/Project/SmartFactory/install/setup.bash
ros2 launch smartfactory_perception_ros vision_overlay_stream_bridge.launch.py \
  use_vision_overlay_stream_bridge:=true \
  host:=0.0.0.0 \
  port:=8090 \
  sources:=tb3_1_picam \
  max_fps:=30
```

Browser/debug endpoints:

- `GET /api/v1/vision/bridge/status` returns JSON status for enabled sources.
- `GET /api/v1/vision/overlay/view?source=tb3_1_picam` returns a simple HTML viewer.
- `GET /api/v1/vision/overlay/stream?source=tb3_1_picam&max_fps=30` returns `multipart/x-mixed-replace` MJPEG.
- Aliases: `/view/tb3_1_picam`, `/stream/tb3_1_picam.mjpeg`.

This bridge is the preferred D1 high-FPS browser path for AI overlay video. The
AI Server image endpoints remain smoke/debug surfaces; production GUI viewing
should not repeatedly poll snapshot URLs.

## Passive ArUco pose monitor

Use this for robot-available passive tuning or central-PC synthetic checks. It
does not contact AI Server and does not move the robot.

Direct run example:

```bash
source /opt/ros/jazzy/setup.bash
source /home/codelab/turtlebot3_ws/install/setup.bash
export SMARTFACTORY_AI_SERVER_PYTHONPATH=/home/codelab/Desktop/Project/SmartFactory/services/ai-server
ros2 run smartfactory_perception_ros aruco_pose_monitor --ros-args \
  -p image_topic:=/camera/image_raw/compressed \
  -p image_transport:=compressed \
  -p target_marker_id:=ARUCO_4X4_50_0 \
  -p marker_size_m:=0.08 \
  -p camera_fx:=600.0 \
  -p camera_fy:=600.0 \
  -p camera_cx:=320.0 \
  -p camera_cy:=240.0 \
  -p target_distance_m:=0.45
```

Launch-file example, disabled unless explicitly enabled:

```bash
ros2 launch smartfactory_perception_ros aruco_pose_monitor.launch.py \
  use_aruco_pose_monitor:=true \
  image_topic:=/camera/image_raw/compressed \
  image_transport:=compressed \
  target_marker_id:=ARUCO_4X4_50_0
```

Calibration values above are placeholders from the tuning template. Before any
permission-gated active docking, replace them with measured camera intrinsics
and station-specific target offsets.

The launch file is conservative: all snapshot clients are disabled unless
`use_ai_snapshot_clients:=true`, and individual adapters are gated by
`use_global_camera` / `use_robot_picams`.

## Live Robot1 QA evidence

Robot1 PiCam compressed transport was live-tested on 2026-06-11:

- `/camera/image_raw/compressed`: `sensor_msgs/msg/CompressedImage`, about 30 Hz.
- OpenCV viewer detected phone-displayed ArUco ID `0`.
- `image_snapshot_client` posted compressed frames to AI Server with `source_id=tb3_1_picam` and `emit=false`.
- AI Server produced `ARUCO_4X4_50_0` events for `tb3_1_picam` during the marker window.

Detailed runbook/evidence: [`docs/robot/robot1-picam-aruco-ai-server-qa-2026-06-11.md`](../../docs/robot/robot1-picam-aruco-ai-server-qa-2026-06-11.md).

## D1 async AI overlay gateway profile

The current D1 high-FPS profile keeps AI Server ROS-free and moves ROS work into sidecars:

```text
camera CompressedImage -> vision_frame_gateway -> AI Server /api/v1/vision/frame/process -> /sf/vision/.../overlay/compressed -> stream bridge
```

Important parameters:

- `async_pipeline:=true`: one bounded latest-only worker slot per source.
- `process_frame_inline:=true`: use `/api/v1/vision/frame/process` instead of separate frame ingest plus worker tick.
- `image_qos_reliability:=reliable|sensor_data|best_effort`: must be compatible with the camera publisher.
- `overlay_pub_qos_reliability:=reliable|best_effort`: overlay publisher QoS.
- `publish_lagging_overlay:=false`: skip overlays that do not match the processed latest frame sequence.

The Main-facing HTTP contract is still the ROS-free single public gateway on `0.0.0.0:8090`; internal per-domain ports remain local implementation details.
