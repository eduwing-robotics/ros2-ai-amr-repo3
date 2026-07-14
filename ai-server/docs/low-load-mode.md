# Main AI Server Startup: Low-load WebRTC

Low-load mode is the primary AI Server lab startup for demos and integration
checks when the laptop must preserve CPU/GPU headroom. Use the operator wrapper;
do not start the AI API, gateway, mDNS publisher, or MediaMTX separately.

```bash
cd ai-server
./scripts/ai/setup_ai_server_env.sh
./scripts/vision/sf_lab.sh low-load
```

The command stays in the foreground and supervises the complete runtime. Use a
second terminal for status and URL checks:

```bash
cd ai-server
./scripts/vision/sf_lab.sh status
./scripts/vision/sf_lab.sh urls low-load
```

The setup downloads the default pretrained weights used by the low-load profile:

- `models/yolov8n.pt` for PiCam/person-style detect passes.
- `models/yolov8s-seg.pt` for the global camera segmentation pass.

These files are runtime artifacts, not repository files. To use another model,
override `VISION_MODEL_PATH` and `VISION_MODEL_SOURCE_CONFIG_JSON` before launch.

PiCam sources use the FastDDS robot-network defaults in
`config/ros/fastdds-smartfactory.env`. For a different lab address plan, set
`SMARTFACTORY_ROBOT_PEERS` and `SMARTFACTORY_OPERATOR_PEERS`, or set
`SF_VISION_ROS_ENV_FILE` to a local override file before starting low-load mode.
For diagnostic inspection only, check the resolved `ROS/DDS discovery` block
without starting processes with:

```bash
./scripts/vision/sf_vision.sh print-config lab-gopro-tb3-low-load
```

Use `./scripts/vision/sf_lab.sh urls low-load` after launch to print the active WebRTC URLs and MJPEG diagnostic fallbacks.

Low-load is hostname-first and WebRTC-primary. While the runtime is active it
publishes `smartfactory-vision.local` through Avahi/mDNS using the current IPv4
address on the configured SmartFactory site subnet (`192.168.30.*` by default).
The address is detected at each launch and is not fixed in the profile.

The operator bundle creates an ephemeral Vision gateway credential when
`VISION_GATEWAY_HMAC_SECRET` is not configured. The value stays internal to the
runtime process tree, so low-load startup and robot camera bringup do not require
manual secret distribution. An explicitly configured credential is preserved for
deployments that run the AI Server and frame gateway independently.
