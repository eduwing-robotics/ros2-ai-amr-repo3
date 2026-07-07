# Troubleshooting

## Port 8100 is busy

Stop the old AI Server process or run with another port:

```bash
AI_SERVER_PORT=8110 ./scripts/ai/run_ai_server.sh
```

## Frames or overlays are stale

Check source status and stream discovery:

```bash
./scripts/vision/sf_lab.sh api streams
./scripts/vision/sf_lab.sh api worker-status global_cam_01
```

## Model path missing

Model weights are not committed. Run `./scripts/ai/setup_ai_server_env.sh` to
create `.venv/` and download the default pretrained weights under `models/`.

## mDNS/hostname not reachable

Use direct IP/port URLs from `./scripts/vision/sf_lab.sh urls low-load`, then fix local DNS/mDNS separately.
