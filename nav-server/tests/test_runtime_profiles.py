import json
from pathlib import Path

import pytest

from nav_app.config.runtime_profiles import (
    DEFAULT_MANIFEST_PATH,
    DEFAULT_ROBOTS_PATH,
    RuntimeProfileError,
    resolve_runtime_profile,
)


def test_selection_precedence_and_tb1_is_default(monkeypatch):
    monkeypatch.setenv("SF_NAV_PROFILE", "tb2-live")
    assert resolve_runtime_profile()["profile_id"] == "tb2-live"
    resolved = resolve_runtime_profile(cli_profile="all-live")
    assert resolved["profile_id"] == "all-live"
    assert resolved["selection_source"] == "cli"
    monkeypatch.delenv("SF_NAV_PROFILE")
    default = resolve_runtime_profile()
    assert default["profile_id"] == "tb1-live"
    assert [robot["robot_id"] for robot in default["robots"]] == ["tb3_burger_01"]


def test_all_live_expands_in_canonical_config_order():
    resolved = resolve_runtime_profile(cli_profile="all-live")
    assert [robot["robot_id"] for robot in resolved["robots"]] == ["tb3_burger_01", "tb3_burger_02"]
    assert resolved["components"]["lift"]["required"] is True
    assert resolved["components"]["lift"]["robot_ids"] == ["tb3_burger_02"]


def _fixture(tmp_path: Path, profile_id="test"):
    source_profile = DEFAULT_MANIFEST_PATH.parent / "tb1-live.json"
    profile = json.loads(source_profile.read_text())
    profile["profile_id"] = profile_id
    (tmp_path / "profile.json").write_text(json.dumps(profile))
    manifest = {"schema_version": 1, "default_profile": profile_id, "profiles": {profile_id: "profile.json"}}
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    robots_path = tmp_path / "robots.json"
    robots_path.write_text(DEFAULT_ROBOTS_PATH.read_text())
    return manifest_path, robots_path, profile


def test_unknown_hardware_fact_key_is_rejected(tmp_path):
    manifest_path, robots_path, profile = _fixture(tmp_path)
    profile["components"]["movement_api"]["api_port"] = 9999
    (tmp_path / "profile.json").write_text(json.dumps(profile))
    with pytest.raises(RuntimeProfileError, match="unknown keys"):
        resolve_runtime_profile(manifest_path=manifest_path, robots_path=robots_path)


def test_profile_ids_are_basename_safe(tmp_path):
    manifest_path, robots_path, profile = _fixture(tmp_path)
    profile["profile_id"] = "../../outside"
    (tmp_path / "profile.json").write_text(json.dumps(profile))
    manifest_path.write_text(
        json.dumps({"schema_version": 1, "default_profile": "../../outside", "profiles": {"../../outside": "profile.json"}})
    )
    with pytest.raises(RuntimeProfileError, match="basename-safe"):
        resolve_runtime_profile(manifest_path=manifest_path, robots_path=robots_path)


def test_component_robot_ids_must_be_selected(tmp_path):
    manifest_path, robots_path, profile = _fixture(tmp_path)
    profile["components"]["lift"] = {
        "enabled": True,
        "required": True,
        "ownership": "external",
        "start_script": "",
        "readiness_probe": "lift-topics",
        "robot_ids": ["tb3_burger_02"],
    }
    (tmp_path / "profile.json").write_text(json.dumps(profile))
    with pytest.raises(RuntimeProfileError, match="component robot_ids"):
        resolve_runtime_profile(manifest_path=manifest_path, robots_path=robots_path)


@pytest.mark.parametrize("ownership", ["root", "service-managed"])
def test_invalid_or_unimplemented_ownership_fails_closed(tmp_path, ownership):
    manifest_path, robots_path, profile = _fixture(tmp_path)
    profile["components"]["movement_api"]["ownership"] = ownership
    (tmp_path / "profile.json").write_text(json.dumps(profile))
    with pytest.raises(RuntimeProfileError, match="ownership|not implemented"):
        resolve_runtime_profile(manifest_path=manifest_path, robots_path=robots_path)


def test_live_profile_cannot_enable_virtual_lift(tmp_path):
    manifest_path, robots_path, profile = _fixture(tmp_path)
    profile["virtual_lift"] = {"enabled": True}
    (tmp_path / "profile.json").write_text(json.dumps(profile))
    with pytest.raises(RuntimeProfileError, match="live profiles cannot enable"):
        resolve_runtime_profile(manifest_path=manifest_path, robots_path=robots_path)


@pytest.mark.parametrize(
    "virtual_lift,match",
    [
        ({"enabled": True, "backend": "nondeterministic"}, "unsupported"),
        ({"enabled": True, "backend": "deterministic", "topic": "/lift"}, "unknown keys"),
        ({"enabled": "yes", "backend": "deterministic"}, "must be boolean"),
    ],
)
def test_virtual_lift_schema_is_exact(tmp_path, virtual_lift, match):
    manifest_path, robots_path, profile = _fixture(tmp_path)
    profile["execution_class"] = "synthetic_hil"
    profile["evidence_class"] = "nonphysical"
    profile["virtual_lift"] = virtual_lift
    (tmp_path / "profile.json").write_text(json.dumps(profile))
    with pytest.raises(RuntimeProfileError, match=match):
        resolve_runtime_profile(manifest_path=manifest_path, robots_path=robots_path)


def test_synthetic_hil_requires_enabled_virtual_lift(tmp_path):
    manifest_path, robots_path, profile = _fixture(tmp_path)
    profile["execution_class"] = "synthetic_hil"
    profile["evidence_class"] = "nonphysical"
    profile.pop("virtual_lift", None)
    (tmp_path / "profile.json").write_text(json.dumps(profile))
    with pytest.raises(RuntimeProfileError, match="requires enabled virtual_lift"):
        resolve_runtime_profile(manifest_path=manifest_path, robots_path=robots_path)


def test_unknown_disabled_refs_and_resource_collisions_fail(tmp_path):
    manifest_path, robots_path, profile = _fixture(tmp_path)
    profile["robot_selector"] = {"robot_ids": ["missing"]}
    (tmp_path / "profile.json").write_text(json.dumps(profile))
    with pytest.raises(RuntimeProfileError, match="unknown robot"):
        resolve_runtime_profile(manifest_path=manifest_path, robots_path=robots_path)

    profile["robot_selector"] = {"enabled_robots": True}
    (tmp_path / "profile.json").write_text(json.dumps(profile))
    robots = json.loads(robots_path.read_text())
    robots["robots"][1]["api_port"] = robots["robots"][0]["api_port"]
    robots_path.write_text(json.dumps(robots))
    with pytest.raises(RuntimeProfileError, match="api_ports"):
        resolve_runtime_profile(manifest_path=manifest_path, robots_path=robots_path)


def test_resolved_config_is_deterministic_and_preserves_canonical_facts(monkeypatch):
    monkeypatch.delenv("SF_NAV_PROFILE", raising=False)
    first = resolve_runtime_profile()
    second = resolve_runtime_profile()
    assert first == second
    assert not {"run_id", "ownership_token", "started_at"} & first.keys()
    source = json.loads(DEFAULT_ROBOTS_PATH.read_text())["robots"][0]
    actual = first["robots"][0]
    for key, value in source.items():
        if key == "active_map_yaml":
            assert actual[key].endswith(value)
        else:
            assert actual[key] == value
