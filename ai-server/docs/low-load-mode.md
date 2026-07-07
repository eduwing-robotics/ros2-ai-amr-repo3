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

The runtime can run in a normal terminal. Set `SF_VISION_TMUX_GUARD_ENABLED=true`
only if you want to force the old `Smartfactory:3:Development` tmux pane.
