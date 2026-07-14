from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMON = ROOT / "scripts" / "lib" / "vision_bundle_common.sh"
MDNS_PUBLISHER = ROOT / "scripts" / "vision" / "publish_vision_mdns_alias.py"
PROFILES = ROOT / "config" / "vision" / "profiles"


def _fake_hostname(tmp_path: Path, addresses: str) -> Path:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    hostname = fake_bin / "hostname"
    hostname.write_text(f"#!/usr/bin/env bash\nprintf '%s\\n' '{addresses}'\n", encoding="utf-8")
    hostname.chmod(0o755)
    return fake_bin


def test_lan_ip_selection_prefers_only_the_site_192_168_30_subnet(tmp_path: Path) -> None:
    fake_bin = _fake_hostname(tmp_path, "192.168.10.59 192.168.30.5")

    result = subprocess.run(
        ["bash", "-c", f"source {COMMON}; sf_lan_ip"],
        env={
            "PATH": f"{fake_bin}:/usr/bin:/bin",
            "SMARTFACTORY_LAN_IPV4_PREFIX": "192.168.30.",
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "192.168.30.5"


def test_lan_ip_selection_fails_closed_without_a_site_address(tmp_path: Path) -> None:
    fake_bin = _fake_hostname(tmp_path, "192.168.10.59 172.18.0.1")

    result = subprocess.run(
        ["bash", "-c", f"source {COMMON}; sf_lan_ip"],
        env={
            "PATH": f"{fake_bin}:/usr/bin:/bin",
            "SMARTFACTORY_LAN_IPV4_PREFIX": "192.168.30.",
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert result.stdout == ""


def test_mdns_auto_address_uses_the_site_subnet(tmp_path: Path) -> None:
    fake_bin = _fake_hostname(tmp_path, "192.168.10.59 192.168.30.5")
    result = subprocess.run(
        ["python3", str(MDNS_PUBLISHER), "--print-only"],
        cwd=ROOT,
        env={
            "PATH": f"{fake_bin}:/usr/bin:/bin",
            "SMARTFACTORY_LAN_IPV4_PREFIX": "192.168.30.",
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "192.168.30.5" in result.stdout
    assert "192.168.10." not in result.stdout


def test_standard_profiles_do_not_publish_temporary_production_mdns_aliases() -> None:
    offenders = [
        path.name
        for path in PROFILES.glob("*.env")
        if "SF_VISION_MDNS_ENABLED=true" in path.read_text(encoding="utf-8")
    ]

    assert offenders == []
