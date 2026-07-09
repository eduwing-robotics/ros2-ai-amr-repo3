# SmartFactory AI Server Deploy Package

This folder is the standalone deploy root for the SmartFactory AI Server. It is designed to be copied as `ai-server/` into the target deployment repository and run from this directory without referencing the original SmartFactory monorepo.

## Current capability

- FastAPI AI Server on port `8100`.
- Camera frame ingest, latest-frame/overlay APIs, MJPEG/WebRTC-oriented stream discovery, and low-load lab operator scripts.
- Main-facing ArUco + ZoneROI lift/load evidence endpoint: `POST /api/v1/vision/evidence/lift-load/evaluate`.
- Person-hazard advisory/read-model APIs for PiCam sources. AI Server emits evidence/advisory state only; Main/Movement owns task, inventory, stop, slow, and motion decisions.

Legacy `/api/v1/lift-roi/evaluate*` endpoints are not part of this deploy package.

## Quick start: no hardware

```bash
cd ai-server
./scripts/ai/setup_ai_server_env.sh
./scripts/ai/test_ai_server.sh
./scripts/ai/run_ai_server.sh --reload
```

Health check:

```bash
curl http://127.0.0.1:8100/api/v1/health
```

## Low-load lab runtime

Low-load mode keeps stream/operator ergonomics while limiting inference load.
Run `./scripts/ai/setup_ai_server_env.sh` first. It creates `.venv/`, installs
the model runtime, and prepares the default pretrained weights under `models/`
(`yolov8n.pt`, `yolov8s-seg.pt`). The generated environment and weights are
ignored by git.

For TurtleBot PiCam sources, the runtime loads
`config/ros/fastdds-smartfactory.env` by default. If the lab robot or operator
PC addresses differ, set `SMARTFACTORY_ROBOT_PEERS` and
`SMARTFACTORY_OPERATOR_PEERS` before launch, or point `SF_VISION_ROS_ENV_FILE`
at a small local override file.

```bash
cd ai-server
./scripts/vision/sf_lab.sh low-load
./scripts/vision/sf_lab.sh status
./scripts/vision/sf_lab.sh urls low-load
./scripts/vision/sf_lab.sh api health
./scripts/vision/sf_lab.sh api streams
./scripts/vision/sf_lab.sh api worker-status global_cam_01
```

Runtime restart/control APIs stay disabled unless the operator explicitly configures the runtime-control token and allow-list environment variables.

## Hardware validation boundary

Automated tests are no-hardware checks. When lab cameras are available, use `docs/live-api-smoke-tests.md` to record the manual GoPro/PiCam/ArUco validation.

## API and contracts

- API reference: `docs/api.md`
- Live API smoke tests: `docs/live-api-smoke-tests.md`
- Lift/load contract: `docs/contracts/lift-load-evidence.md`
- OpenAPI snapshot and JSON schemas: `docs/contracts/`

## Quality gates

```bash
cd ai-server
./scripts/ai/test_ai_server.sh
bash -n scripts/ai/*.sh scripts/vision/*.sh
python3 scripts/validate/validate_deployment_assets.py
python3 scripts/validate/self_containment_audit.py
.venv/bin/python -m ruff check app tests scripts
```

The final command requires dev dependencies from `requirements-dev.txt`.
