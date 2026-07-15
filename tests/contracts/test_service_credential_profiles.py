"""Production service-credential bootstrap and launcher contracts."""

from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess


ROOT = Path(__file__).resolve().parents[2]
LIBRARY = ROOT / "scripts" / "lib" / "site_credentials.sh"
BUNDLE_RELATIVE = Path(".secrets/service-hmac.env")
SECRET_KEYS = {
    "LMS_MOVEMENT_HMAC_SECRET",
    "NAV_MAIN_HMAC_SECRET",
    "LMS_VISION_HMAC_SECRET",
    "MAIN_HMAC_SECRET",
    "VISION_GATEWAY_HMAC_SECRET",
}


def _run_library(action: str, repo_root: Path, *, env: dict[str, str] | None = None):
    command = (
        f'source "{LIBRARY}"; '
        f'sf_{action}_site_credentials "{repo_root}"'
    )
    return subprocess.run(
        ["bash", "-c", command],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _parse_bundle(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def test_bootstrap_creates_one_private_paired_bundle_without_printing_secrets(tmp_path):
    first = _run_library("ensure", tmp_path)
    assert first.returncode == 0, first.stderr

    bundle = tmp_path / BUNDLE_RELATIVE
    values = _parse_bundle(bundle)
    assert set(values) == {"SMARTFACTORY_CREDENTIAL_SET_ID", *SECRET_KEYS}
    assert stat.S_IMODE(bundle.stat().st_mode) == 0o600
    assert stat.S_IMODE(bundle.parent.stat().st_mode) == 0o700
    assert values["LMS_MOVEMENT_HMAC_SECRET"] == values["NAV_MAIN_HMAC_SECRET"]
    assert values["LMS_VISION_HMAC_SECRET"] == values["MAIN_HMAC_SECRET"]
    assert len(
        {
            values["LMS_MOVEMENT_HMAC_SECRET"],
            values["LMS_VISION_HMAC_SECRET"],
            values["VISION_GATEWAY_HMAC_SECRET"],
        }
    ) == 3
    assert all(len(values[key]) >= 43 for key in SECRET_KEYS)
    assert not any(value in first.stdout + first.stderr for value in values.values())

    second = _run_library("ensure", tmp_path)
    assert second.returncode == 0, second.stderr
    assert _parse_bundle(bundle) == values


def test_bootstrap_migrates_matching_existing_pairs_and_rejects_split_pairs(tmp_path):
    movement = "m" * 48
    vision = "v" * 48
    gateway = "g" * 48
    for service in ("main-server", "nav-server", "ai-server"):
        (tmp_path / service).mkdir()
    (tmp_path / "main-server/.env").write_text(
        f"LMS_MOVEMENT_HMAC_SECRET={movement}\nLMS_VISION_HMAC_SECRET={vision}\n",
        encoding="utf-8",
    )
    (tmp_path / "nav-server/.env").write_text(
        f"NAV_MAIN_HMAC_SECRET={movement}\n", encoding="utf-8"
    )
    (tmp_path / "ai-server/.env").write_text(
        f"MAIN_HMAC_SECRET={vision}\nVISION_GATEWAY_HMAC_SECRET={gateway}\n",
        encoding="utf-8",
    )

    result = _run_library("ensure", tmp_path)
    assert result.returncode == 0, result.stderr
    values = _parse_bundle(tmp_path / BUNDLE_RELATIVE)
    assert values["LMS_MOVEMENT_HMAC_SECRET"] == movement
    assert values["LMS_VISION_HMAC_SECRET"] == vision
    assert values["VISION_GATEWAY_HMAC_SECRET"] == gateway

    split_root = tmp_path / "split"
    (split_root / "main-server").mkdir(parents=True)
    (split_root / "nav-server").mkdir()
    (split_root / "main-server/.env").write_text(
        f"LMS_MOVEMENT_HMAC_SECRET={movement}\n", encoding="utf-8"
    )
    (split_root / "nav-server/.env").write_text(
        f"NAV_MAIN_HMAC_SECRET={'x' * 48}\n", encoding="utf-8"
    )
    rejected = _run_library("ensure", split_root)
    assert rejected.returncode != 0
    assert "Main/Nav credential pair differs" in rejected.stderr
    assert movement not in rejected.stdout + rejected.stderr


def test_loader_rejects_missing_insecure_or_conflicting_credentials(tmp_path):
    missing = _run_library("load", tmp_path)
    assert missing.returncode != 0
    assert "credential bundle is missing" in missing.stderr

    assert _run_library("ensure", tmp_path).returncode == 0
    values = _parse_bundle(tmp_path / BUNDLE_RELATIVE)
    conflicting_env = os.environ.copy()
    conflicting_env["NAV_MAIN_HMAC_SECRET"] = "wrong-credential-must-not-appear"
    conflicting = _run_library("load", tmp_path, env=conflicting_env)
    assert conflicting.returncode != 0
    assert "NAV_MAIN_HMAC_SECRET differs from the credential bundle" in conflicting.stderr
    assert conflicting_env["NAV_MAIN_HMAC_SECRET"] not in conflicting.stdout + conflicting.stderr
    assert not any(value in conflicting.stdout + conflicting.stderr for value in values.values())

    tampered = values.copy()
    tampered["LMS_MOVEMENT_HMAC_SECRET"] = "t" * 48
    tampered["NAV_MAIN_HMAC_SECRET"] = "t" * 48
    bundle = tmp_path / BUNDLE_RELATIVE
    bundle.write_text(
        "\n".join(f"{key}={value}" for key, value in tampered.items()) + "\n",
        encoding="utf-8",
    )
    differing_set = _run_library("load", tmp_path)
    assert differing_set.returncode != 0
    assert "does not match the credential material" in differing_set.stderr
    assert not any(value in differing_set.stdout + differing_set.stderr for value in tampered.values())

    bundle.write_text(
        "\n".join(f"{key}={value}" for key, value in values.items()) + "\n",
        encoding="utf-8",
    )
    (tmp_path / BUNDLE_RELATIVE).chmod(0o644)
    insecure = _run_library("load", tmp_path)
    assert insecure.returncode != 0
    assert "mode 0600" in insecure.stderr

    (tmp_path / BUNDLE_RELATIVE).chmod(0o600)
    (tmp_path / BUNDLE_RELATIVE).parent.chmod(0o755)
    exposed_directory = _run_library("load", tmp_path)
    assert exposed_directory.returncode != 0
    assert "mode 0700" in exposed_directory.stderr


def test_standard_bootstrap_and_launchers_own_credential_generation_and_loading():
    sources = {
        "bootstrap": ROOT / "main-server/scripts/bootstrap.sh",
        "main": ROOT / "main-server/scripts/real.sh",
        "nav": ROOT / "nav-server/scripts/sf_nav.sh",
        "vision": ROOT / "ai-server/scripts/vision/sf_vision.sh",
        "preflight": ROOT / "scripts/operator-preflight.sh",
    }
    text = {name: path.read_text(encoding="utf-8") for name, path in sources.items()}

    assert "sf_ensure_site_credentials" in text["bootstrap"]
    assert "sf_load_site_credentials" in text["main"]
    assert "sf_load_site_credentials" in text["nav"]
    assert "sf_load_site_credentials" in text["vision"]
    assert "sf_load_site_credentials" in text["preflight"]
    assert "required Movement HMAC secret is not set; export" not in text["preflight"]
    assert "required Vision HMAC secret is not set; export" not in text["preflight"]
