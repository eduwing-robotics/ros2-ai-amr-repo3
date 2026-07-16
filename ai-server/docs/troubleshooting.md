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

## Hostname not reachable

The shared repository hosts mapping is the only authority for
`smartfactory-vision.local`. Check it from the repository root:

```bash
cd ..
./scripts/install-smartfactory-hosts.sh --check
getent ahostsv4 smartfactory-vision.local
```

If the check fails, correct the canonical mapping before restarting low-load.
Do not publish a second mDNS alias or save a direct-IP fallback in service
configuration.

## WebRTC and MJPEG overlays differ

WebRTC is the primary browser stream; MJPEG is a diagnostic fallback. After code or ZoneROI config changes, restart low-load and compare the active URLs from:

```bash
./scripts/vision/sf_lab.sh urls low-load
```
