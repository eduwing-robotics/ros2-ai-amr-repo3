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

The compose file publishes only the AI Server HTTP port. ROS graph, rosbridge, and internal stream ports are not published by the API container.
The Docker image is optional and API-focused. It installs `requirements.lock`
and does not include the YOLO/model runtime used by the native low-load lab
profile.

## Native process

```bash
./scripts/ai/setup_ai_server_env.sh
AI_SERVER_HOST=0.0.0.0 AI_SERVER_PORT=8100 ./scripts/ai/run_ai_server.sh
```

## Model runtime

The same setup command prepares the model runtime and default weights:

```bash
./scripts/ai/setup_ai_server_env.sh
./scripts/vision/sf_lab.sh check low-load
./scripts/vision/sf_lab.sh low-load
```

The setup creates `.venv/` and `models/`; both are local runtime artifacts and
are intentionally not committed. It does not rewrite `requirements.lock`, so
running setup on different machines should not dirty the repository.
