# Low-load Mode

Low-load mode is the preferred lab operator profile for demos and integration checks when the laptop must preserve CPU/GPU headroom.

```bash
cd ai-server
./scripts/ai/setup_ai_server_env.sh
./scripts/vision/sf_lab.sh low-load
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
Check the resolved `ROS/DDS discovery` block with:

```bash
./scripts/vision/sf_vision.sh print-config lab-gopro-tb3-low-load
```

Use `./scripts/vision/sf_lab.sh urls low-load` after launch to print the active WebRTC URLs and MJPEG diagnostic fallbacks.
