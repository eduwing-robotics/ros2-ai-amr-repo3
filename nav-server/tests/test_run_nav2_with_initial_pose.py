"""Startup contracts for Nav2 localization bringup."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_nav2_with_initial_pose.sh"
NAV_OPS = ROOT / "scripts" / "nav_ops.sh"
START_ALL = ROOT / "scripts" / "start_all_tb3_2.sh"
CREDENTIAL_LIBRARY = ROOT.parent / "scripts" / "lib" / "site_credentials.sh"


def _write_executable(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)


def _write_site_credentials(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    checkout = tmp_path / "checkout"
    helper = checkout / "scripts" / "lib" / "site_credentials.sh"
    helper.parent.mkdir(parents=True)
    shutil.copy2(CREDENTIAL_LIBRARY, helper)

    movement = "m" * 48
    vision = "v" * 48
    gateway = "g" * 48
    material = b"smartfactory-service-hmac-v1\0" + b"\0".join(
        value.encode("ascii") for value in (movement, vision, gateway)
    )
    credential_set_id = hashlib.sha256(material).hexdigest()[:24]
    credential_dir = checkout / ".secrets"
    credential_dir.mkdir(mode=0o700)
    credential_dir.chmod(0o700)
    bundle = credential_dir / "service-hmac.env"
    bundle.write_text(
        "\n".join(
            (
                f"SMARTFACTORY_CREDENTIAL_SET_ID={credential_set_id}",
                f"LMS_MOVEMENT_HMAC_SECRET={movement}",
                f"NAV_MAIN_HMAC_SECRET={movement}",
                f"LMS_VISION_HMAC_SECRET={vision}",
                f"MAIN_HMAC_SECRET={vision}",
                f"VISION_GATEWAY_HMAC_SECRET={gateway}",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    bundle.chmod(0o600)
    return checkout, {
        "LMS_MOVEMENT_HMAC_SECRET": movement,
        "NAV_MAIN_HMAC_SECRET": movement,
        "LMS_VISION_HMAC_SECRET": vision,
        "MAIN_HMAC_SECRET": vision,
        "VISION_GATEWAY_HMAC_SECRET": gateway,
    }


def _fake_startup_environment(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    event_log = tmp_path / "events.log"

    _write_executable(
        bin_dir / "ros2",
        """#!/usr/bin/env bash
echo "ros2 $*" >> "$EVENT_LOG"
if [[ "$1 $2 $3" == "run tf2_ros tf2_echo" ]]; then
  [[ "${FAKE_TF:-1}" == "1" ]] || exit 1
  echo "Translation: [0.0, 0.0, 0.0]"
elif [[ "$1 $2" == "service call" ]]; then
  if [[ "${FAKE_LIFECYCLE_ACTIVE:-1}" == "1" ]]; then
    echo "success: true"
  else
    echo "success: false"
  fi
fi
exit 0
""",
    )
    _write_executable(
        bin_dir / "rviz2",
        "#!/usr/bin/env bash\necho \"rviz2 $*\" >> \"$EVENT_LOG\"\nexit 0\n",
    )
    _write_executable(
        bin_dir / "ip",
        "#!/usr/bin/env bash\necho '192.168.30.101 dev fake_field0 src 192.168.30.5 uid 1000'\n",
    )
    _write_executable(
        bin_dir / "getent",
        "#!/usr/bin/env bash\necho '192.168.30.101 STREAM smartfactory-robot1.local'\n",
    )
    _write_executable(
        bin_dir / "timeout",
        "#!/usr/bin/env bash\nshift\nexec \"$@\"\n",
    )
    _write_executable(
        bin_dir / "curl",
        """#!/usr/bin/env bash
echo "curl $*" >> "$EVENT_LOG"
request="$*"
if [[ "${FAKE_API_MODE:-localized}" == "unavailable" ]]; then
  exit 22
fi
if [[ " $request " != *" -X POST "* \
  && -n "${FAKE_READINESS_DELAY_SEC:-}" \
  && ! -f "${FAKE_READINESS_DELAY_FILE}" ]]; then
  : > "${FAKE_READINESS_DELAY_FILE}"
  sleep "${FAKE_READINESS_DELAY_SEC}"
fi
if [[ " $request " == *" -X POST "* ]]; then
  endpoint="${!#}"
  timestamp=""
  nonce=""
  signature=""
  body=""
  while (($#)); do
    case "$1" in
      -H)
        case "$2" in
          "X-SF-Timestamp: "*) timestamp="${2#*: }" ;;
          "X-SF-Nonce: "*) nonce="${2#*: }" ;;
          "X-SF-Signature: "*) signature="${2#*: }" ;;
        esac
        shift 2
        ;;
      --data-binary)
        body="$2"
        shift 2
        ;;
      *) shift ;;
    esac
  done
  python3 - "$NAV_MAIN_HMAC_SECRET" "$endpoint" "$body" "$timestamp" "$nonce" "$signature" <<'PY'
import hashlib
import hmac
import sys
from urllib.parse import urlsplit

secret, endpoint, body, timestamp, nonce, signature = sys.argv[1:]
parsed = urlsplit(endpoint)
path = parsed.path or "/"
if parsed.query:
    path = f"{path}?{parsed.query}"
body_hash = hashlib.sha256(body.encode()).hexdigest()
signed = "\n".join(("POST", path, timestamp, nonce, body_hash)).encode()
expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
raise SystemExit(0 if timestamp and nonce and hmac.compare_digest(expected, signature) else 90)
PY
  if [[ " $request " == *" /initial-pose "* ]]; then
    printf '%s\n' '{"accepted":true,"robot_name":"tb3_1","robot_id":"tb3_burger_01","ros_domain_id":2,"localization":{"state":"SEEDING","localized":false,"map_id":"robot2_map"}}'
  elif [[ "${FAKE_API_MODE:-localized}" == "transient-once" && ! -f "$FAKE_API_COUNT_FILE" ]]; then
    : > "$FAKE_API_COUNT_FILE"
    printf '%s\n' '{"accepted":false,"robot_name":"tb3_1","robot_id":"tb3_burger_01","ros_domain_id":2,"localization":{"map_id":"robot2_map"},"search":{"accepted":false,"strategy":"observe_only","motion_started":false,"reason":"global_localization_service_unavailable"}}'
  elif [[ "${FAKE_API_MODE:-localized}" == "trigger-rejected" ]]; then
    printf '%s\n' '{"accepted":false,"robot_name":"tb3_1","robot_id":"tb3_burger_01","ros_domain_id":2,"localization":{"map_id":"robot2_map"},"search":{"accepted":false,"strategy":"observe_only","motion_started":false,"reason":"rejected"}}'
  else
    if [[ "${FAKE_API_MODE:-localized}" == "refinement-progress" ]]; then
      : > "${FAKE_GLOBAL_TRIGGER_FILE}"
    fi
    printf '%s\n' '{"accepted":true,"robot_name":"tb3_1","robot_id":"tb3_burger_01","ros_domain_id":2,"localization":{"map_id":"robot2_map"},"search":{"accepted":true,"strategy":"observe_only","motion_started":false,"reason":"amcl_global_search_started"}}'
  fi
  exit 0
fi
case "${FAKE_API_MODE:-localized}" in
  refinement-progress)
    if [[ ! -f "${FAKE_GLOBAL_TRIGGER_FILE}" ]]; then
      printf '%s\n' '{"state":"UNLOCALIZED","localized":false,"reason":"not_started","robot_name":"tb3_1","robot_id":"tb3_burger_01","ros_domain_id":2,"map_id":"robot2_map","robot_online":true,"scan_age_sec":0.1}'
    elif [[ ! -f "${FAKE_REFINEMENT_COUNT_FILE}" ]]; then
      : > "${FAKE_REFINEMENT_COUNT_FILE}"
      printf '%s\n' '{"state":"CONVERGING","localized":false,"reason":"scan_map_alignment_confirmation_pending","robot_name":"tb3_1","robot_id":"tb3_burger_01","ros_domain_id":2,"map_id":"robot2_map","robot_online":true,"scan_age_sec":0.1,"scan_map_alignment":{"attempts":1}}'
    else
      printf '%s\n' '{"state":"LOCALIZED","localized":true,"reason":"converged","robot_name":"tb3_1","robot_id":"tb3_burger_01","ros_domain_id":2,"map_id":"robot2_map","robot_online":true,"scan_age_sec":0.1,"scan_map_alignment":{"attempts":1,"accepted":true}}'
    fi
    ;;
  failed)
    printf '%s\n' '{"state":"FAILED","localized":false,"reason":"nomotion_update_timeout","robot_name":"tb3_1","robot_id":"tb3_burger_01","ros_domain_id":2,"map_id":"robot2_map","robot_online":true,"scan_age_sec":0.1}'
    ;;
  stale-scan)
    printf '%s\n' '{"state":"UNLOCALIZED","localized":false,"reason":"scan_missing_or_stale","robot_name":"tb3_1","robot_id":"tb3_burger_01","ros_domain_id":2,"map_id":"robot2_map","robot_online":true,"scan_age_sec":2.0}'
    ;;
  offline)
    printf '%s\n' '{"state":"UNLOCALIZED","localized":false,"reason":"robot_offline","robot_name":"tb3_1","robot_id":"tb3_burger_01","ros_domain_id":2,"map_id":"robot2_map","robot_online":false,"scan_age_sec":0.1}'
    ;;
  stale-map|readiness-map)
    printf '%s\n' '{"state":"LOCALIZED","localized":true,"reason":"converged","robot_name":"tb3_1","robot_id":"tb3_burger_01","ros_domain_id":2,"map_id":"robot1_map","robot_online":true,"scan_age_sec":0.1}'
    ;;
  stale-domain|readiness-domain)
    printf '%s\n' '{"state":"LOCALIZED","localized":true,"reason":"converged","robot_name":"tb3_1","robot_id":"tb3_burger_01","ros_domain_id":5,"map_id":"robot2_map","robot_online":true,"scan_age_sec":0.1}'
    ;;
  stale-robot|readiness-robot-name)
    printf '%s\n' '{"state":"LOCALIZED","localized":true,"reason":"converged","robot_name":"tb3_2","robot_id":"tb3_burger_01","ros_domain_id":2,"map_id":"robot2_map","robot_online":true,"scan_age_sec":0.1}'
    ;;
  readiness-robot-id)
    printf '%s\n' '{"state":"UNLOCALIZED","localized":false,"reason":"identity_mismatch","robot_name":"tb3_1","robot_id":"tb3_burger_02","ros_domain_id":2,"map_id":"robot2_map","robot_online":true,"scan_age_sec":0.1}'
    ;;
  inconsistent)
    printf '%s\n' '{"state":"LOCALIZED","localized":false,"reason":"converged","robot_name":"tb3_1","robot_id":"tb3_burger_01","ros_domain_id":2,"map_id":"robot2_map","robot_online":true,"scan_age_sec":0.1}'
    ;;
  *)
    printf '%s\n' '{"state":"LOCALIZED","localized":true,"reason":"converged","robot_name":"tb3_1","robot_id":"tb3_burger_01","ros_domain_id":2,"map_id":"robot2_map","robot_online":true,"scan_age_sec":0.1}'
    ;;
esac
""",
    )

    setup = tmp_path / "setup.bash"
    setup.write_text("", encoding="utf-8")
    map_yaml = tmp_path / "robot2_map.yaml"
    map_yaml.write_text("image: robot2_map.pgm\n", encoding="utf-8")
    params = tmp_path / "params.yaml"
    params.write_text("/**: {}\n", encoding="utf-8")

    checkout, credential_values = _write_site_credentials(tmp_path)
    return os.environ | {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "EVENT_LOG": str(event_log),
        "FAKE_API_COUNT_FILE": str(tmp_path / "api-count"),
        "FAKE_REFINEMENT_COUNT_FILE": str(tmp_path / "refinement-count"),
        "FAKE_GLOBAL_TRIGGER_FILE": str(tmp_path / "global-trigger"),
        "FAKE_READINESS_DELAY_FILE": str(tmp_path / "readiness-delay"),
        "ROS_SETUP": str(setup),
        "TURTLEBOT3_SETUP": str(setup),
        "MAP_YAML": str(map_yaml),
        "NAV2_PARAMS_FILE": str(params),
        "SMARTFACTORY_REPO_ROOT": str(checkout),
        **credential_values,
        "RMW_IMPLEMENTATION": "rmw_cyclonedds_cpp",
        "ROS_STATIC_PEERS": "smartfactory-robot1.local",
        "AUTOMATIC_LOCALIZATION_TIMEOUT_SEC": "1",
        "AUTOMATIC_LOCALIZATION_API_TIMEOUT_SEC": "1",
        "NAV2_STARTUP_RETRY_SEC": "1",
        "ROBOT_READINESS_TIMEOUT_SEC": "2",
        "ROBOT_SCAN_MAX_AGE_SEC": "1.0",
        "XDG_RUNTIME_DIR": str(tmp_path / "runtime"),
    }


def _run_startup(
    tmp_path: Path,
    *,
    args: list[str] | None = None,
    env_overrides: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    env = _fake_startup_environment(tmp_path)
    env.update(env_overrides or {})
    result = subprocess.run(
        [
            str(SCRIPT),
            "--robot",
            "tb3_1",
            "--domain",
            "2",
            "--delay",
            "0",
            "--repeat",
            "1",
            *(args or []),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=8,
        check=False,
    )
    event_log = Path(env["EVENT_LOG"])
    events = event_log.read_text(encoding="utf-8").splitlines() if event_log.exists() else []
    return result, events


def _event_index(events: list[str], needle: str) -> int:
    return next(index for index, event in enumerate(events) if needle in event)


def test_automatic_startup_orders_sensor_gate_trigger_localization_and_lifecycle(tmp_path: Path) -> None:
    result, events = _run_startup(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    readiness_get = next(
        index for index, event in enumerate(events) if event.startswith("curl ") and "-X POST" not in event
    )
    assert readiness_get < _event_index(events, "run tf2_ros tf2_echo")
    assert _event_index(events, "run tf2_ros tf2_echo") < _event_index(events, "launch nav2_bringup")
    assert _event_index(events, "launch nav2_bringup") < _event_index(events, "-X POST")
    localization_get = next(
        index
        for index, event in enumerate(events)
        if index > _event_index(events, "-X POST") and event.startswith("curl ") and "-X POST" not in event
    )
    assert _event_index(events, "-X POST") < localization_get
    assert localization_get < _event_index(events, "/lifecycle_manager_navigation/is_active")
    post = next(event for event in events if "-X POST" in event)
    assert 'strategy":"observe_only"' in post
    assert 'allow_motion":false' in post
    assert "X-SF-Timestamp:" in post and "X-SF-Nonce:" in post and "X-SF-Signature:" in post
    assert "navigation-ready: localization and lifecycle gates passed" in result.stdout
    assert not any("topic echo --once /scan" in event for event in events)
    assert not any("/cmd_vel" in event for event in events)


def test_standard_startup_loads_site_credentials_without_operator_export(tmp_path: Path) -> None:
    result, events = _run_startup(
        tmp_path,
        env_overrides={
            "LMS_MOVEMENT_HMAC_SECRET": "",
            "NAV_MAIN_HMAC_SECRET": "",
            "LMS_VISION_HMAC_SECRET": "",
            "MAIN_HMAC_SECRET": "",
            "VISION_GATEWAY_HMAC_SECRET": "",
        },
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert any("-X POST" in event for event in events)
    assert "navigation-ready: localization and lifecycle gates passed" in result.stdout
    assert not any(value * 48 in result.stdout + result.stderr for value in ("m", "v", "g"))


def test_missing_site_bundle_fails_before_ros_or_network_side_effects(tmp_path: Path) -> None:
    missing_checkout = tmp_path / "missing-checkout"
    helper = missing_checkout / "scripts" / "lib" / "site_credentials.sh"
    helper.parent.mkdir(parents=True)
    shutil.copy2(CREDENTIAL_LIBRARY, helper)
    result, events = _run_startup(
        tmp_path,
        env_overrides={
            "SMARTFACTORY_REPO_ROOT": str(missing_checkout),
            "LMS_MOVEMENT_HMAC_SECRET": "",
            "NAV_MAIN_HMAC_SECRET": "",
            "LMS_VISION_HMAC_SECRET": "",
            "MAIN_HMAC_SECRET": "",
            "VISION_GATEWAY_HMAC_SECRET": "",
        },
    )

    assert result.returncode != 0
    assert "credential bundle is missing" in result.stderr
    assert events == []


def test_mismatched_site_credential_fails_early_without_leaking_value(tmp_path: Path) -> None:
    stale_secret = "x" * 48
    result, events = _run_startup(
        tmp_path,
        env_overrides={"NAV_MAIN_HMAC_SECRET": stale_secret},
    )

    assert result.returncode != 0
    assert "NAV_MAIN_HMAC_SECRET differs from the credential bundle" in result.stderr
    assert stale_secret not in result.stdout + result.stderr
    assert events == []


def test_transient_amcl_service_rejection_is_retried_within_api_deadline(tmp_path: Path) -> None:
    result, events = _run_startup(
        tmp_path,
        env_overrides={
            "FAKE_API_MODE": "transient-once",
            "AUTOMATIC_LOCALIZATION_API_TIMEOUT_SEC": "3",
        },
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert sum("-X POST" in event for event in events) == 2
    assert "global_localization_service_unavailable; retrying" in result.stdout
    assert "navigation-ready: localization and lifecycle gates passed" in result.stdout
    assert not any("/cmd_vel" in event for event in events)


def test_alignment_refinement_progress_extends_localization_wait_without_motion(tmp_path: Path) -> None:
    result, events = _run_startup(
        tmp_path,
        env_overrides={
            "FAKE_API_MODE": "refinement-progress",
            "AUTOMATIC_LOCALIZATION_TIMEOUT_SEC": "1",
            "AUTOMATIC_LOCALIZATION_REFINEMENT_GRACE_SEC": "3",
        },
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "extending convergence wait for scan-map refinement attempt 1" in result.stdout
    assert "navigation-ready: localization and lifecycle gates passed" in result.stdout
    assert not any("/cmd_vel" in event for event in events)


def test_default_localization_wait_budgets_follow_selected_robot_profile(tmp_path: Path) -> None:
    result, events = _run_startup(
        tmp_path,
        env_overrides={
            "AUTOMATIC_LOCALIZATION_TIMEOUT_SEC": "",
            "AUTOMATIC_LOCALIZATION_REFINEMENT_GRACE_SEC": "",
        },
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "localization wait budget: base=210s refinement=135s" in result.stdout
    assert not any("/cmd_vel" in event for event in events)


@pytest.mark.parametrize(
    ("mode", "failure"),
    [
        ("stale-scan", "scan_missing_or_stale"),
        ("offline", "robot_offline"),
        ("unavailable", "api_unavailable"),
    ],
)
def test_transient_robot_readiness_keeps_nav2_and_rviz_available_for_recovery(
    tmp_path: Path, mode: str, failure: str
) -> None:
    result, events = _run_startup(
        tmp_path,
        env_overrides={"FAKE_API_MODE": mode, "ROBOT_READINESS_TIMEOUT_SEC": "1"},
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "LOCALIZATION_FAILED: fresh /scan unavailable via localization API" in result.stderr
    assert failure in result.stderr
    assert "robot input pending; launching Nav2/RViz" in result.stderr
    assert "automatic localization deferred" in result.stderr
    assert any("launch nav2_bringup" in event for event in events)
    assert any(event.startswith("rviz2 ") for event in events)
    assert any(event.startswith("curl ") for event in events)
    assert not any("run tf2_ros tf2_echo" in event for event in events)
    assert "navigation-ready" not in result.stdout
    assert not any("-X POST" in event for event in events)
    assert not any("topic pub" in event for event in events)
    assert not any("/cmd_vel" in event for event in events)


@pytest.mark.parametrize(
    ("mode", "failure"),
    [
        ("readiness-robot-name", "robot_name_mismatch"),
        ("readiness-robot-id", "robot_id_mismatch"),
        ("readiness-domain", "ros_domain_id_mismatch"),
        ("readiness-map", "map_id_mismatch"),
    ],
)
def test_identity_mismatch_still_fails_before_nav2_launch(
    tmp_path: Path, mode: str, failure: str
) -> None:
    result, events = _run_startup(
        tmp_path,
        env_overrides={"FAKE_API_MODE": mode, "ROBOT_READINESS_TIMEOUT_SEC": "1"},
    )

    assert result.returncode != 0
    assert failure in result.stderr
    assert "refusing Nav2 launch because robot/profile identity does not match" in result.stderr
    assert not any("launch nav2_bringup" in event for event in events)
    assert not any(event.startswith("rviz2 ") for event in events)


def test_missing_odom_tf_keeps_nav2_online_and_defers_localization(tmp_path: Path) -> None:
    result, events = _run_startup(tmp_path, env_overrides={"FAKE_TF": "0"})

    assert result.returncode == 0, result.stdout + result.stderr
    assert "LOCALIZATION_FAILED: odom -> base_footprint TF unavailable" in result.stderr
    assert _event_index(events, "curl ") < _event_index(events, "run tf2_ros tf2_echo")
    assert any("launch nav2_bringup" in event for event in events)
    assert any(event.startswith("rviz2 ") for event in events)
    assert "automatic localization deferred" in result.stderr
    assert not any("-X POST" in event for event in events)
    assert not any("topic pub" in event for event in events)
    assert not any("/cmd_vel" in event for event in events)


def test_slow_scan_discovery_does_not_consume_odom_tf_readiness_budget(tmp_path: Path) -> None:
    result, events = _run_startup(
        tmp_path,
        env_overrides={
            "ROBOT_READINESS_TIMEOUT_SEC": "1",
            "FAKE_READINESS_DELAY_SEC": "1",
        },
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "waiting for odom -> base_footprint TF" in result.stdout
    assert "robot scan and odom TF ready" in result.stdout
    assert any("launch nav2_bringup" in event for event in events)


@pytest.mark.parametrize(
    "mode",
    ["failed", "trigger-rejected", "inconsistent"],
)
def test_localization_failure_keeps_nav2_online_with_movement_admission_closed(
    tmp_path: Path, mode: str
) -> None:
    result, events = _run_startup(tmp_path, env_overrides={"FAKE_API_MODE": mode})

    assert result.returncode == 0, result.stdout + result.stderr
    assert "LOCALIZATION_FAILED" in result.stderr
    assert any("/lifecycle_manager_navigation/is_active" in event for event in events)
    assert "localization-pending: Nav2 remains online" in result.stderr
    assert "movement stays blocked until localization converges" in result.stderr
    assert "위치 다시 찾기" in result.stderr
    assert "navigation-ready" not in result.stdout
    assert not any("/cmd_vel" in event for event in events)


def test_nav2_lifecycle_failure_remains_fatal(tmp_path: Path) -> None:
    result, events = _run_startup(
        tmp_path,
        env_overrides={"FAKE_LIFECYCLE_ACTIVE": "0", "NAV2_STARTUP_RETRY_SEC": "1"},
    )

    assert result.returncode != 0
    assert any("/lifecycle_manager_navigation/is_active" in event for event in events)
    assert "navigation lifecycle not active yet" in result.stderr
    assert "navigation-ready" not in result.stdout
    assert "localization-pending" not in result.stderr
    assert not any("/cmd_vel" in event for event in events)


def test_lifecycle_wait_stays_recoverable_while_robot_input_is_absent(tmp_path: Path) -> None:
    result, events = _run_startup(
        tmp_path,
        env_overrides={
            "FAKE_API_MODE": "offline",
            "ROBOT_READINESS_TIMEOUT_SEC": "1",
            "FAKE_LIFECYCLE_ACTIVE": "0",
            "NAV2_STARTUP_RETRY_SEC": "1",
        },
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "robot input pending; launching Nav2/RViz" in result.stderr
    assert "navigation lifecycle pending until robot TF becomes available" in result.stderr
    assert any("launch nav2_bringup" in event for event in events)
    assert not any("-X POST" in event for event in events)
    assert not any("/cmd_vel" in event for event in events)


@pytest.mark.parametrize(
    "args",
    [
        ["--x", "0"],
        ["--x", "0", "--y", "0"],
        ["--yaw", "0"],
    ],
)
def test_partial_manual_pose_is_rejected_before_side_effects(tmp_path: Path, args: list[str]) -> None:
    result, events = _run_startup(tmp_path, args=args)

    assert result.returncode == 2
    assert "--x, --y, and --yaw must be supplied together" in result.stderr
    assert events == []


@pytest.mark.parametrize(
    "args",
    [
        ["--robot", "tb3_1", "--domain", "5"],
        ["--robot", "tb3_2", "--domain", "2"],
    ],
)
def test_noncanonical_robot_domain_pair_is_rejected_before_side_effects(
    tmp_path: Path, args: list[str]
) -> None:
    side_effect_setup = tmp_path / "side-effect-setup.bash"
    side_effect_setup.write_text('echo "sourced setup" >> "$EVENT_LOG"\n', encoding="utf-8")
    result, events = _run_startup(
        tmp_path,
        args=args,
        env_overrides={
            "ROS_SETUP": str(side_effect_setup),
            "TURTLEBOT3_SETUP": str(side_effect_setup),
        },
    )

    assert result.returncode == 2
    assert "robot/domain mismatch" in result.stderr
    assert events == []


def test_unknown_robot_is_rejected_before_side_effects(tmp_path: Path) -> None:
    side_effect_setup = tmp_path / "side-effect-setup.bash"
    side_effect_setup.write_text('echo "sourced setup" >> "$EVENT_LOG"\n', encoding="utf-8")
    result, events = _run_startup(
        tmp_path,
        args=["--robot", "unknown", "--domain", "2"],
        env_overrides={
            "ROS_SETUP": str(side_effect_setup),
            "TURTLEBOT3_SETUP": str(side_effect_setup),
        },
    )

    assert result.returncode == 2
    assert "unsupported robot identity" in result.stderr
    assert events == []


def test_default_movement_url_tracks_robot_port_override(tmp_path: Path) -> None:
    result, events = _run_startup(tmp_path, env_overrides={"TB3_1_PORT": "9101"})

    assert result.returncode == 0, result.stdout + result.stderr
    api_events = [event for event in events if event.startswith("curl ")]
    assert api_events
    assert all("http://127.0.0.1:9101/movement-api/v1/robots/tb3_1/" in event for event in api_events)


def test_explicit_movement_url_overrides_robot_port(tmp_path: Path) -> None:
    result, events = _run_startup(
        tmp_path,
        env_overrides={
            "TB3_1_PORT": "9101",
            "MOVEMENT_API_URL": "http://nav-api.example:9191/custom/v1",
        },
    )

    assert result.returncode == 0, result.stdout + result.stderr
    api_events = [event for event in events if event.startswith("curl ")]
    assert api_events
    assert all("http://nav-api.example:9191/custom/v1/robots/tb3_1/" in event for event in api_events)
    assert not any(":9101" in event for event in api_events)


def test_explicit_pose_seeds_api_gate_then_waits_for_localized_state(tmp_path: Path) -> None:
    result, events = _run_startup(
        tmp_path,
        args=["--x", "0", "--y", "0", "--yaw", "0"],
    )

    assert result.returncode == 0, result.stdout + result.stderr
    manual_post = next(event for event in events if "-X POST" in event and "/initial-pose" in event)
    assert '"x":0.0' in manual_post and '"y":0.0' in manual_post and '"yaw":0.0' in manual_post
    assert "X-SF-Timestamp:" in manual_post and "X-SF-Nonce:" in manual_post and "X-SF-Signature:" in manual_post
    assert not any("/localization/global-search" in event for event in events)
    manual_post_index = _event_index(events, "/initial-pose")
    localization_get = next(
        index
        for index, event in enumerate(events)
        if index > manual_post_index and event.startswith("curl ") and "-X POST" not in event
    )
    assert manual_post_index < localization_get
    assert localization_get < _event_index(events, "/lifecycle_manager_navigation/is_active")
    assert not any("topic pub" in event for event in events)
    assert not any("/cmd_vel" in event for event in events)


def test_startup_scripts_preserve_manual_only_coordinates_and_api_first_wrappers() -> None:
    nav_ops = NAV_OPS.read_text(encoding="utf-8")
    start_all = START_ALL.read_text(encoding="utf-8")

    assert "NAV2_AUTO_INITIAL_POSE" not in nav_ops
    assert nav_ops.count("NAV2_MANUAL_INITIAL_POSE") == 2
    assert 'exec "$SCRIPT_DIR/run_nav2_with_initial_pose.sh" --robot tb3_1 --domain 2' in nav_ops
    assert 'exec "$SCRIPT_DIR/run_nav2_with_initial_pose.sh" --robot tb3_2 --domain 5' in nav_ops
    assert start_all.index('new_win "nav-servers"') < start_all.index('new_win "nav2-rviz"')
    assert start_all.index('open_win "nav-servers"') < start_all.index('open_win "nav2-rviz"')
    assert start_all.index('add_pane "nav-servers"') < start_all.index('add_pane "nav2-rviz"')
    nav_command = start_all[start_all.index("cmd_nav2_rviz()") : start_all.index("cmd_detector2()")]
    assert "--x" not in nav_command and "--y" not in nav_command and "--yaw" not in nav_command


def test_helper_never_drives_lifecycle_transitions_or_cmd_vel() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "/lifecycle_manager_navigation/manage_nodes" not in source
    assert "nav2_msgs/srv/ManageLifecycleNodes" not in source
    assert "/cmd_vel" not in source
    assert "retry_navigation_startup &" not in source
    assert source.index("wait_for_robot_readiness") < source.index("ros2 launch nav2_bringup")
    assert 'grep -m1 "Translation:"' in source
    assert source.index("wait_for_localized_state") < source.rindex("monitor_navigation_startup")


def test_helper_keeps_nav2_and_rviz_in_the_sf_nav_owned_process_group() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "setsid ros2 launch nav2_bringup" not in source
    assert 'setsid rviz2 -d "$RVIZ_CONFIG_FILE"' not in source
    assert 'kill -TERM "$launch_pid"' in source
    assert 'kill -TERM "$rviz_pid"' in source


def test_repository_rviz_is_single_optional_process_and_uses_qos_safe_config(tmp_path: Path) -> None:
    result, events = _run_startup(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert sum(event.startswith("rviz2 ") for event in events) == 1
    assert any("config/rviz/agv_map_debug.rviz" in event for event in events if event.startswith("rviz2 "))
    assert not any("turtlebot3_navigation2" in event for event in events)

    headless_dir = tmp_path / "headless"
    headless_dir.mkdir()
    result, events = _run_startup(headless_dir, args=["--no-rviz"])
    assert result.returncode == 0, result.stdout + result.stderr
    assert not any(event.startswith("rviz2 ") for event in events)


def test_cyclonedds_profile_is_route_derived_not_host_ip_hardcoded(tmp_path: Path) -> None:
    result, _ = _run_startup(tmp_path, args=["--no-rviz"])

    assert result.returncode == 0, result.stdout + result.stderr
    profiles = list((tmp_path / "runtime" / "smartfactory-cyclonedds").glob("*.xml"))
    assert len(profiles) == 1
    profile = profiles[0].read_text(encoding="utf-8")
    assert 'NetworkInterface name="fake_field0"' in profile
    assert '<Peer Address="192.168.30.5"/>' in profile
    assert "<AllowMulticast>false</AllowMulticast>" in profile
    assert "smartfactory-robot1.local" not in profile
    assert "hardware_domain=2 local_domain=42" in result.stdout


def test_explicit_local_domain_keeps_public_robot_identity(tmp_path: Path) -> None:
    result, events = _run_startup(tmp_path, args=["--local-domain", "43", "--no-rviz"])

    assert result.returncode == 0, result.stdout + result.stderr
    assert "hardware_domain=2 local_domain=43" in result.stdout
    assert any("/robots/tb3_1/localization" in event for event in events)
