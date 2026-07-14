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

Low-load normally publishes `smartfactory-vision.local` to the current
`192.168.30.*` Vision PC address for the lifetime of the supervised runtime.
Check the managed publisher and its selected address:

```bash
./scripts/vision/sf_lab.sh status
cat .run/vision/logs/mdns-alias.log
getent ahostsv4 smartfactory-vision.local
```

If `mdns-alias` is not alive, restart the main runtime with
`./scripts/vision/sf_lab.sh low-load`. Direct-IP URLs are a temporary diagnostic
fallback, not the hostname-first operating contract.

## WebRTC and MJPEG overlays differ

WebRTC is the primary browser stream; MJPEG is a diagnostic fallback. After code or ZoneROI config changes, restart low-load and compare the active URLs from:

```bash
./scripts/vision/sf_lab.sh urls low-load
```
