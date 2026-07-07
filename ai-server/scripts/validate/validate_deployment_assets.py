#!/usr/bin/env python3
"""Validate standalone AI Server deployment assets."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "Dockerfile"
COMPOSE = ROOT / "docker-compose.yml"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    require(DOCKERFILE.exists(), "Dockerfile missing")
    require(COMPOSE.exists(), "docker-compose.yml missing")
    text = DOCKERFILE.read_text(encoding="utf-8")
    require("PYTHONPATH=/app/ai-server" in text, "Dockerfile must set standalone PYTHONPATH")
    require("COPY app ./app" in text, "Dockerfile must copy app locally")
    require(
        "COPY docs/contracts ./docs/contracts" in text, "Dockerfile must include contract schemas"
    )
    require("rclpy" not in text.lower(), "Dockerfile must stay independent from ROS runtime")
    compose = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    service = compose["services"]["ai-server"]
    require(service["build"]["dockerfile"] == "Dockerfile", "compose must use local Dockerfile")
    require(
        "${AI_SERVER_PORT:-8100}:8100" in service.get("ports", []),
        "compose must publish only AI API port",
    )
    published = "\n".join(str(port) for port in service.get("ports", []))
    for forbidden_port in ("9090", "11311", "11811", "18090", "18091", "7400", "7600"):
        require(
            forbidden_port not in published,
            f"compose must not publish ROS/internal port {forbidden_port}",
        )
    print("Deployment assets validated.")


if __name__ == "__main__":
    main()
