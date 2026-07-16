from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
HOSTS_SOURCE = ROOT / "config" / "network" / "smartfactory-hosts"
INSTALLER = ROOT / "scripts" / "install-smartfactory-hosts.sh"


def test_canonical_site_hosts_are_hostname_first_on_192_168_30_subnet() -> None:
    entries = {
        fields[1]: fields[0]
        for line in HOSTS_SOURCE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
        for fields in [line.split()]
    }

    assert entries == {
        "smartfactory-integration.local": "192.168.30.5",
        "smartfactory-main.local": "192.168.30.9",
        "smartfactory-nav.local": "192.168.30.12",
        "smartfactory-vision.local": "192.168.30.3",
        "smartfactory-robot1.local": "192.168.30.101",
        "smartfactory-robot2.local": "192.168.30.102",
    }


def test_hosts_installer_replaces_only_its_managed_block(tmp_path: Path) -> None:
    hosts_file = tmp_path / "hosts"
    hosts_file.write_text(
        "127.0.0.1 localhost\n"
        "# BEGIN SMARTFACTORY HOSTS\n"
        "192.168.10.99 stale.local\n"
        "# END SMARTFACTORY HOSTS\n"
        "203.0.113.1 unrelated.example\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(INSTALLER), "--apply"],
        cwd=ROOT,
        env={"PATH": "/usr/bin:/bin", "HOSTS_FILE": str(hosts_file)},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    updated = hosts_file.read_text(encoding="utf-8")
    assert "192.168.10." not in updated
    assert updated.count("# BEGIN SMARTFACTORY HOSTS") == 1
    assert "192.168.30.3 smartfactory-vision.local smartfactory-vision" in updated
    assert "203.0.113.1 unrelated.example" in updated


def test_hosts_check_reports_an_unresolved_name_instead_of_exiting_silently(tmp_path: Path) -> None:
    source = tmp_path / "hosts-source"
    source.write_text("192.0.2.1 definitely-unresolved.invalid\n", encoding="utf-8")
    result = subprocess.run(
        [str(INSTALLER), "--check"],
        cwd=ROOT,
        env={
            "PATH": "/usr/bin:/bin",
            "SMARTFACTORY_HOSTS_SOURCE": str(source),
        },
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "resolves to <unresolved>, expected 192.0.2.1" in result.stderr


def test_active_server_defaults_do_not_embed_192_168_10_addresses() -> None:
    active_paths = [
        ROOT / "main-server" / "backend" / "app" / "core" / "config.py",
        ROOT / "main-server" / ".env.example",
        ROOT / "ai-server" / ".env.example",
        ROOT / "ai-server" / "scripts" / "lib" / "vision_bundle_common.sh",
        ROOT / "nav-server" / "config" / "main_server_routes.json",
    ]

    for path in active_paths:
        assert "192.168.10." not in path.read_text(encoding="utf-8"), path
