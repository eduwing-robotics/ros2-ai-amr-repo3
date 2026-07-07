# AI Server Quality Gates

Run from the standalone deploy root:

```bash
cd ai-server
./scripts/ai/test_ai_server.sh
bash -n scripts/ai/*.sh scripts/vision/*.sh
python3 scripts/validate/validate_contracts.py
python3 scripts/validate/validate_deployment_assets.py
python3 scripts/validate/self_containment_audit.py
.venv/bin/python -m ruff check app tests scripts
```

Hardware checks are manual and documented in `docs/hardware-validation-checklist.md`.

## ShellCheck advisory exclusions

The deploy package keeps existing operator shell semantics for sourced ROS setup files, tmux-supervised cleanup hooks, literal JSON environment defaults, and array-like command dispatch. The CI/pass command excludes these non-blocking inherited advisories while keeping syntax and higher-signal shell checks active:

```bash
shellcheck -e SC1090,SC1091,SC2030,SC2031,SC2034,SC2054,SC2089,SC2090,SC2128,SC2178,SC2295,SC2329 scripts/ai/*.sh scripts/vision/*.sh
```
