#!/usr/bin/env bash
# Shared production service-credential bootstrap/loader.
# The generated values stay in one ignored repository-local file and are never printed.

_sf_site_credentials_tool() {
  local action="$1" repo_root="$2"
  python3 - "$action" "$repo_root" <<'PY'
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import secrets
import stat
import sys


ACTION = sys.argv[1]
ROOT = Path(sys.argv[2]).resolve()
DIRECTORY = ROOT / ".secrets"
BUNDLE = DIRECTORY / "service-hmac.env"
ID_KEY = "SMARTFACTORY_CREDENTIAL_SET_ID"
MOVEMENT_MAIN = "LMS_MOVEMENT_HMAC_SECRET"
MOVEMENT_NAV = "NAV_MAIN_HMAC_SECRET"
VISION_MAIN = "LMS_VISION_HMAC_SECRET"
VISION_AI = "MAIN_HMAC_SECRET"
GATEWAY = "VISION_GATEWAY_HMAC_SECRET"
ORDER = (ID_KEY, MOVEMENT_MAIN, MOVEMENT_NAV, VISION_MAIN, VISION_AI, GATEWAY)
SECRET_KEYS = set(ORDER[1:])
SECRET_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43,}$")
ID_PATTERN = re.compile(r"^[a-f0-9]{24}$")


def fail(message: str) -> "NoReturn":
    raise SystemExit(f"[credentials] ERROR: {message}")


def parse_env(path: Path, *, strict: bool = False) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            if strict:
                fail(f"invalid credential bundle line {number}")
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        if strict and key not in ORDER:
            fail(f"unexpected key in credential bundle: {key or '<empty>'}")
        if strict and key in values:
            fail(f"duplicate key in credential bundle: {key}")
        values[key] = value
    return values


def local_candidates() -> dict[str, list[tuple[str, str]]]:
    candidates = {key: [] for key in SECRET_KEYS}
    for key in SECRET_KEYS:
        value = os.environ.get(key, "").strip()
        if value:
            candidates[key].append(("process environment", value))
    for relative in ("main-server/.env", "nav-server/.env", "ai-server/.env"):
        path = ROOT / relative
        for key, value in parse_env(path).items():
            if key in candidates and value:
                candidates[key].append((relative, value))
    return candidates


def one_pair_value(
    label: str,
    left_key: str,
    right_key: str,
    candidates: dict[str, list[tuple[str, str]]],
) -> str | None:
    observed = candidates[left_key] + candidates[right_key]
    values = {value for _, value in observed}
    if len(values) > 1:
        locations = ", ".join(sorted({source for source, _ in observed}))
        fail(f"{label} credential pair differs across {locations}")
    return next(iter(values), None)


def one_value(key: str, candidates: dict[str, list[tuple[str, str]]]) -> str | None:
    observed = candidates[key]
    values = {value for _, value in observed}
    if len(values) > 1:
        locations = ", ".join(sorted({source for source, _ in observed}))
        fail(f"{key} differs across {locations}")
    return next(iter(values), None)


def validate_secret(key: str, value: str) -> None:
    if not SECRET_PATTERN.fullmatch(value):
        fail(f"{key} must be a URL-safe high-entropy value of at least 43 characters")


def credential_set_id(movement: str, vision: str, gateway: str) -> str:
    material = b"smartfactory-service-hmac-v1\0" + b"\0".join(
        value.encode("ascii") for value in (movement, vision, gateway)
    )
    return hashlib.sha256(material).hexdigest()[:24]


def validate_bundle(*, compare_local: bool = True) -> dict[str, str]:
    if not BUNDLE.exists():
        fail(f"credential bundle is missing: {BUNDLE}; run main-server/scripts/bootstrap.sh once, then deploy the same 0600 file to each service checkout")
    if DIRECTORY.is_symlink() or not DIRECTORY.is_dir():
        fail(f"credential directory must be a regular directory: {DIRECTORY}")
    directory_mode = stat.S_IMODE(DIRECTORY.stat().st_mode)
    if directory_mode != 0o700:
        fail(f"credential directory must have mode 0700, got {directory_mode:04o}: {DIRECTORY}")
    if BUNDLE.is_symlink() or not BUNDLE.is_file():
        fail(f"credential bundle must be a regular file: {BUNDLE}")
    mode = stat.S_IMODE(BUNDLE.stat().st_mode)
    if mode != 0o600:
        fail(f"credential bundle must have mode 0600, got {mode:04o}: {BUNDLE}")
    values = parse_env(BUNDLE, strict=True)
    missing = [key for key in ORDER if not values.get(key)]
    if missing:
        fail("credential bundle is missing required keys: " + ", ".join(missing))
    if not ID_PATTERN.fullmatch(values[ID_KEY]):
        fail(f"{ID_KEY} is invalid")
    for key in SECRET_KEYS:
        validate_secret(key, values[key])
    if values[MOVEMENT_MAIN] != values[MOVEMENT_NAV]:
        fail("Main/Nav credential pair differs inside the bundle")
    if values[VISION_MAIN] != values[VISION_AI]:
        fail("Main/AI credential pair differs inside the bundle")
    scoped = {values[MOVEMENT_MAIN], values[VISION_MAIN], values[GATEWAY]}
    if len(scoped) != 3:
        fail("Movement, Vision, and frame-gateway credentials must remain distinct")
    expected_id = credential_set_id(
        values[MOVEMENT_MAIN], values[VISION_MAIN], values[GATEWAY]
    )
    if values[ID_KEY] != expected_id:
        fail(f"{ID_KEY} does not match the credential material")
    if compare_local:
        for key, observed in local_candidates().items():
            for source, value in observed:
                if value != values[key]:
                    fail(f"{key} differs from the credential bundle in {source}")
    return values


def ensure_bundle() -> None:
    if BUNDLE.exists():
        validate_bundle()
        print(f"[credentials] ready: {BUNDLE} (values hidden)")
        return
    candidates = local_candidates()
    movement = one_pair_value("Main/Nav", MOVEMENT_MAIN, MOVEMENT_NAV, candidates)
    vision = one_pair_value("Main/AI", VISION_MAIN, VISION_AI, candidates)
    gateway = one_value(GATEWAY, candidates)
    movement = movement or secrets.token_urlsafe(48)
    vision = vision or secrets.token_urlsafe(48)
    gateway = gateway or secrets.token_urlsafe(48)
    generated = {
        ID_KEY: credential_set_id(movement, vision, gateway),
        MOVEMENT_MAIN: movement,
        MOVEMENT_NAV: movement,
        VISION_MAIN: vision,
        VISION_AI: vision,
        GATEWAY: gateway,
    }
    for key in SECRET_KEYS:
        validate_secret(key, generated[key])
    if len({movement, vision, gateway}) != 3:
        fail("Movement, Vision, and frame-gateway credentials must remain distinct")
    DIRECTORY.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(DIRECTORY, 0o700)
    payload = "# Generated by main-server/scripts/bootstrap.sh; do not commit or print.\n"
    payload += "\n".join(f"{key}={generated[key]}" for key in ORDER) + "\n"
    try:
        descriptor = os.open(BUNDLE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        validate_bundle()
        print(f"[credentials] ready: {BUNDLE} (values hidden)")
        return
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(BUNDLE, 0o600)
    directory_fd = os.open(DIRECTORY, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    print(f"[credentials] created: {BUNDLE} (values hidden)")


if ACTION == "ensure":
    ensure_bundle()
elif ACTION == "export":
    for key, value in validate_bundle().items():
        print(f"{key}={value}")
elif ACTION == "check":
    validate_bundle()
elif ACTION == "id":
    print(validate_bundle()[ID_KEY])
else:
    fail(f"unknown internal action: {ACTION}")
PY
}

sf_ensure_site_credentials() {
  _sf_site_credentials_tool ensure "$1"
}

sf_load_site_credentials() {
  local repo_root="$1" payload line
  if ! payload="$(_sf_site_credentials_tool export "$repo_root")"; then
    return 1
  fi
  while IFS= read -r line; do
    [[ -n "$line" ]] || continue
    export "$line"
  done <<<"$payload"
}

sf_check_site_credentials() {
  _sf_site_credentials_tool check "$1"
}

sf_site_credentials_id() {
  _sf_site_credentials_tool id "$1"
}
