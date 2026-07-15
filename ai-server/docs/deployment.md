# Deployment

This package is deployed as a single `ai-server/` directory. Commands assume:

```bash
cd ai-server
```

## Docker Compose

```bash
docker compose -f docker-compose.yml config --quiet
docker compose -f docker-compose.yml up --build ai-server
```

The compose file binds the AI Server HTTP port to `127.0.0.1` by default.
ROS graph, rosbridge, and internal stream ports are not published by the API
container. Put a local authenticated reverse proxy in front of it when another
host needs access; do not replace the loopback binding with a public port
mapping for production evidence ingress.

Set a non-empty `MAIN_HMAC_SECRET` shared with Main and a different,
non-empty `VISION_GATEWAY_HMAC_SECRET` for the ROS `vision_frame_gateway`.
Compose refuses to render when the gateway secret is absent. Production
deployments keep every cache-mutating route HMAC-protected. The API remains
loopback-bound. See `docs/contracts/ai-server-api.md` for the signature payload
and headers.
The Docker image is optional and API-focused. It installs `requirements.lock`
and does not include the YOLO/model runtime used by the native low-load lab
profile.

## Native process

### Primary lab operation

Use the supervised low-load WebRTC bundle for normal AI Server lab operation:

```bash
./scripts/ai/setup_ai_server_env.sh
./scripts/vision/sf_lab.sh low-load
```

This is the main operational entrypoint. It dynamically publishes
`smartfactory-vision.local` to the current `192.168.30.*` address and starts
WebRTC as the primary browser stream plane.

### API-only development

```bash
./scripts/ai/setup_ai_server_env.sh
AI_SERVER_HOST=0.0.0.0 AI_SERVER_PORT=8100 ./scripts/ai/run_ai_server.sh
```

The API-only command does not start the ROS camera gateways, mDNS hostname
publisher, MediaMTX, or camera WebRTC publishers.

## Model/runtime preflight

The same setup command prepares the model runtime and default weights:

```bash
./scripts/ai/setup_ai_server_env.sh
./scripts/vision/sf_lab.sh check low-load
```

The setup creates `.venv/` and `models/`; both are local runtime artifacts and
are intentionally not committed. It does not rewrite `requirements.lock`, so
running setup on different machines should not dirty the repository.
