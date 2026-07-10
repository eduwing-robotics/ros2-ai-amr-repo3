from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import config
from app.security import require_admin, require_operator


def _app(dependency):
    app = FastAPI()

    @app.post("/mutation", dependencies=[Depends(dependency)])
    def mutation():
        return {"ok": True}

    @app.get("/health")
    def health():
        return {"ok": True}

    return app


def test_control_mutation_fails_closed_when_token_is_unconfigured(monkeypatch):
    monkeypatch.setattr(config, "settings", replace(config.settings, operator_token=""))
    client = TestClient(_app(require_operator))
    assert client.get("/health").status_code == 200
    assert client.post("/mutation").status_code == 503


def test_operator_token_is_required_and_admin_is_distinct(monkeypatch):
    monkeypatch.setattr(config, "settings", replace(config.settings, operator_token="operator", admin_token="admin"))
    assert TestClient(_app(require_operator)).post("/mutation", headers={"Authorization": "Bearer operator"}).status_code == 200
    assert TestClient(_app(require_admin)).post("/mutation", headers={"Authorization": "Bearer operator"}).status_code == 401
    assert TestClient(_app(require_admin)).post("/mutation", headers={"Authorization": "Bearer admin"}).status_code == 200
