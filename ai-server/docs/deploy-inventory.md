# Deploy Inventory

| Source | Target | Class | Reason |
| --- | --- | --- | --- |
| `services/ai-server/app/` | `app/` | include | Active FastAPI app preserving streaming, frame/overlay, person hazard, and lift/load evidence behavior. |
| `services/ai-server/tests/` | `tests/` | adapt | No-hardware regression tests; deployment path assertions rehomed to standalone root. |
| `services/ai-server/requirements*.txt` | `requirements*.txt` | include | Runtime/dev/model dependency inputs. `requirements.lock` stays API/Docker-focused; model deps install through local setup. |
| `services/ai-server/Dockerfile` | `Dockerfile` | adapt | Rewritten for local `ai-server/` Docker context and `/app/ai-server` PYTHONPATH. |
| `docker-compose.ai-server.yml` | `docker-compose.yml` | adapt | Rewritten to build local Dockerfile and publish only `8100`. |
| `config/vision/**` | `config/vision/**` | adapt | Source registry, profiles, MediaMTX, ZoneROI configs; absolute model paths replaced with `models/` placeholders. |
| `config/perception/**` | `config/perception/**` | include | ArUco/docking example configs referenced by runtime/compose. |
| `scripts/ai/**` | `scripts/ai/**` | adapt | Setup/run/test entrypoints now use `ai-server/.venv` and local validator paths. |
| `scripts/vision/sf_lab.sh`, `sf_vision.sh`, bundle/sidecar helpers | `scripts/vision/**` | adapt | Low-load and stream operator scripts preserved with local root assumptions. |
| `scripts/lib/vision_bundle_common.sh` | `scripts/lib/vision_bundle_common.sh` | adapt | Shared operator helper rehomed locally. |
| `scripts/validate/validate_contracts.py` | `scripts/validate/validate_contracts.py` | adapt | Contract fixture/schema validation from local `docs/contracts`. |
| `scripts/validate/self_containment_audit.py` | `scripts/validate/self_containment_audit.py` | include | New deploy-boundary audit for scripts/docs command examples. |
| `scripts/generate/generate_source_registry_surfaces.py` | `scripts/generate/generate_source_registry_surfaces.py` | adapt | Kept only for local source-registry artifact regeneration. |
| `docs/contracts` schemas, fixtures, OpenAPI, API docs | `docs/contracts/` | include/adapt | Active Main-facing contract artifacts and validator inputs. |
| Historical reports/requests/proposals | excluded | exclude/archive | Not operator-facing and may contain stale SmartFactory-root instructions. |
| Removed legacy lift-roi endpoint files | excluded | exclude | Legacy API surface is intentionally not shipped. |
| `.omx/`, caches, venvs, models, media | `.gitignore` | ignore | Runtime/generated/local artifacts. |
