"""Canonical Movement command status adapter."""

from fastapi import HTTPException

from app.domains.movement.client import MovementClientError, movement_client


def fetch(robot_id: str, command_id: str) -> dict:
    try:
        return movement_client.command_status(robot_id, command_id)
    except MovementClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
