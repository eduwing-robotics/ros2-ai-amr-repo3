#!/usr/bin/env python3
"""Run repeatable two-robot standby, traffic, and collision-stop assertions."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from dual_robot_geometry import DEFAULT_CONFIG, load_layout

SIMULATOR_ROOT = Path(__file__).resolve().parents[1]
ROOT = SIMULATOR_ROOT.parent
TERMINAL_STATES = {"DONE", "ARRIVED", "FAILED", "ABORTED", "CANCELLED", "STOPPED"}


def request_json(url: str, payload: dict[str, Any] | None = None, timeout: float = 5.0) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method="POST" if data is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {url}: {detail}") from exc


def wait_ready(layout: dict[str, Any], timeout_sec: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_sec
    snapshots: dict[str, Any] = {}
    while time.monotonic() < deadline:
        all_ready = True
        for robot in layout["robots"]:
            name = str(robot["name"])
            port = int(robot["api_port"])
            try:
                health = request_json(f"http://127.0.0.1:{port}/movement-api/v1/health", timeout=2.0)
                nav = request_json(
                    f"http://127.0.0.1:{port}/movement-api/v1/robots/{name}/nav-state",
                    timeout=2.0,
                )
                snapshots[name] = {"health": health, "nav_state": nav}
                ready = bool(
                    health.get("ok")
                    and health.get("robot_online")
                    and health.get("nav2_ready")
                    and health.get("command_accepting")
                    and nav.get("reason") == "ok"
                )
            except Exception as exc:
                snapshots[name] = {"error": str(exc)}
                ready = False
            all_ready &= ready
        if all_ready:
            return snapshots
        time.sleep(0.5)
    raise RuntimeError(f"dual stack not ready within {timeout_sec:.1f}s: {snapshots}")


def command_payload(robot: dict[str, Any], command_id: str) -> dict[str, Any]:
    approach = robot["approach_pose"]
    return {
        "command_id": command_id,
        "task_id": 108,
        "robot_name": robot["name"],
        "steps": [
            {"action": "leave_dock", "payload": {}},
            {
                "action": "nav2_pose",
                "payload": {
                    "frame_id": "map",
                    "goal": {
                        "waypoint": robot["approach_waypoint"],
                        "x": approach["x"],
                        "y": approach["y"],
                        "yaw": approach["yaw"],
                        "soft_xy_tolerance_m": 0.08,
                        "soft_yaw_tolerance_rad": 0.40,
                    },
                },
            },
            {"action": "wait", "duration": 2.0, "payload": {}},
        ],
    }


def assert_close(label: str, actual: Any, expected: float, tolerance: float) -> None:
    if actual is None or abs(float(actual) - expected) > tolerance:
        raise AssertionError(f"{label}: expected {expected:.3f}±{tolerance:.3f}, got {actual!r}")


def assert_traffic_result(layout: dict[str, Any], commands: dict[str, dict[str, Any]], observed: dict[str, list[str]]) -> None:
    if not any("WAITING_TRAFFIC" in states for states in observed.values()):
        raise AssertionError(f"shared warehouse_aisle contention was not observed: {observed}")
    for robot in layout["robots"]:
        name = str(robot["name"])
        command = commands[name]
        if command.get("state") != "DONE":
            raise AssertionError(f"{name} did not finish: {command.get('state')} {command.get('reason')}")
        telemetry = command.get("leave_dock_telemetry") or {}
        assert_close(f"{name} start marker", telemetry.get("start_marker_distance_m"), 0.20, 0.03)
        assert_close(f"{name} target marker", telemetry.get("target_marker_distance_m"), 0.40, 0.005)
        assert_close(f"{name} requested reverse", telemetry.get("requested_reverse_distance_m"), 0.20, 0.03)
        end_distance = telemetry.get("end_marker_distance_m")
        if end_distance is None or not 0.395 <= float(end_distance) <= 0.43:
            raise AssertionError(f"{name} end marker outside 40cm line: {end_distance!r}")
        measured = telemetry.get("measured_reverse_distance_m")
        if measured is None or not 0.08 <= float(measured) <= 0.26:
            raise AssertionError(f"{name} measured reverse is implausible: {measured!r}")
        if telemetry.get("reverse_stop_reason") != "marker_clearance":
            raise AssertionError(f"{name} reverse stop was not marker-controlled: {telemetry}")
        max_angular = telemetry.get("max_abs_angular_z_rps")
        if max_angular is None or abs(float(max_angular)) > 0.01:
            raise AssertionError(
                f"{name} reverse angular velocity exceeds 0.01rad/s: {max_angular!r}"
            )
        approach_error = telemetry.get("approach_pose_error_m")
        if approach_error is None or float(approach_error) > 0.08:
            raise AssertionError(f"{name} approach error exceeds 8cm: {approach_error!r}")
        if "warehouse_aisle" not in (telemetry.get("held_traffic_segments") or []):
            raise AssertionError(f"{name} did not retain warehouse_aisle during leave_dock")

    traffic_path = Path(str(layout["traffic_lock_state_path"]))
    release_deadline = time.monotonic() + 3.0
    while True:
        state = json.loads(traffic_path.read_text(encoding="utf-8"))
        if not state.get("locks"):
            break
        if time.monotonic() >= release_deadline:
            raise AssertionError(f"traffic locks leaked after terminal commands: {state['locks']}")
        time.sleep(0.05)


def capture_final_approach_poses(
    layout: dict[str, Any], timeout_sec: float = 5.0, tolerance_m: float = 0.05
) -> dict[str, Any]:
    """Capture settled AMCL/map poses after both commands reach terminal success."""
    deadline = time.monotonic() + timeout_sec
    snapshots: dict[str, Any] = {}
    while time.monotonic() < deadline:
        all_within_tolerance = True
        for robot in layout["robots"]:
            name = str(robot["name"])
            port = int(robot["api_port"])
            target = robot["approach_pose"]
            try:
                health = request_json(
                    f"http://127.0.0.1:{port}/movement-api/v1/health", timeout=2.0
                )
                pose = health.get("pose") or {}
                error_m = math.hypot(
                    float(pose["x"]) - float(target["x"]),
                    float(pose["y"]) - float(target["y"]),
                )
                snapshots[name] = {
                    "pose": pose,
                    "approach_target_pose": {
                        "x": float(target["x"]),
                        "y": float(target["y"]),
                    },
                    "approach_pose_error_m": error_m,
                    "tolerance_m": tolerance_m,
                }
                within = bool(health.get("localized") and error_m <= tolerance_m)
            except Exception as exc:
                snapshots[name] = {"error": str(exc), "tolerance_m": tolerance_m}
                within = False
            all_within_tolerance &= within
        if all_within_tolerance and len(snapshots) == len(layout["robots"]):
            return snapshots
        time.sleep(0.10)
    raise AssertionError(
        f"final map pose did not settle within {tolerance_m:.3f}m of approach: {snapshots}"
    )


def run_traffic(layout: dict[str, Any], timeout_sec: float) -> dict[str, Any]:
    stamp = int(time.time() * 1000)
    command_ids = {str(robot["name"]): f"g108-dual-{robot['name']}-{stamp}" for robot in layout["robots"]}
    submissions: dict[str, Any] = {}
    errors: list[Exception] = []
    start_gate = threading.Event()

    def submit(robot: dict[str, Any]) -> None:
        name = str(robot["name"])
        port = int(robot["api_port"])
        start_gate.wait()
        try:
            submissions[name] = request_json(
                f"http://127.0.0.1:{port}/movement-api/v1/commands",
                command_payload(robot, command_ids[name]),
            )
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=submit, args=(robot,), daemon=True) for robot in layout["robots"]]
    for thread in threads:
        thread.start()
    start_gate.set()

    observed = {str(robot["name"]): [] for robot in layout["robots"]}
    commands: dict[str, dict[str, Any]] = {}
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        all_terminal = True
        for robot in layout["robots"]:
            name = str(robot["name"])
            port = int(robot["api_port"])
            try:
                command = request_json(
                    f"http://127.0.0.1:{port}/movement-api/v1/commands/{command_ids[name]}",
                    timeout=1.0,
                )
            except Exception:
                all_terminal = False
                continue
            commands[name] = command
            traffic_state = command.get("traffic_state")
            if traffic_state and (not observed[name] or observed[name][-1] != traffic_state):
                observed[name].append(str(traffic_state))
            all_terminal &= command.get("state") in TERMINAL_STATES
        if all_terminal and len(commands) == len(layout["robots"]):
            break
        time.sleep(0.05)

    for thread in threads:
        thread.join(timeout=2.0)
    if errors:
        raise errors[0]
    if len(commands) != len(layout["robots"]) or any(
        command.get("state") not in TERMINAL_STATES for command in commands.values()
    ):
        raise RuntimeError(f"dual traffic scenario timed out: {commands}")
    assert_traffic_result(layout, commands, observed)
    final_approach_poses = capture_final_approach_poses(layout)
    final_errors = [
        float(item["approach_pose_error_m"])
        for item in final_approach_poses.values()
    ]
    approach_error_spread_m = max(final_errors) - min(final_errors)
    if approach_error_spread_m > 0.03:
        raise AssertionError(
            f"dual final approach error spread exceeds 0.03m: "
            f"{approach_error_spread_m:.6f} {final_approach_poses}"
        )
    return {
        "passed": True,
        "submissions": submissions,
        "observed_traffic_states": observed,
        "commands": commands,
        "final_approach_poses": final_approach_poses,
        "approach_error_spread_m": approach_error_spread_m,
    }


def run_collision(robot: dict[str, Any], evidence_path: Path, timeout_sec: float) -> dict[str, Any]:
    script_dir = SIMULATOR_ROOT / "scripts"
    probe = script_dir / "sim_collision_stop_probe.py"
    shell = (
        'set -e; '
        f'source "{script_dir / "sim_paths.sh"}"; '
        f'sim_paths_init "{script_dir}"; source_ros_stack; '
        f'export ROS_DOMAIN_ID="{int(robot["ros_domain_id"])}"; '
        f'python3 "{probe}" --timeout-sec "{timeout_sec}" --evidence "{evidence_path}" '
        '--ros-args -p use_sim_time:=true'
    )
    completed = subprocess.run(["bash", "-lc", shell], text=True, capture_output=True, timeout=timeout_sec + 20.0)
    if completed.returncode != 0:
        raise RuntimeError(
            f"collision probe failed rc={completed.returncode}\nstdout={completed.stdout}\nstderr={completed.stderr}"
        )
    return json.loads(evidence_path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--scenario", choices=("all", "traffic", "collision"), default="all")
    parser.add_argument("--ready-timeout-sec", type=float, default=90.0)
    parser.add_argument("--command-timeout-sec", type=float, default=90.0)
    parser.add_argument("--collision-timeout-sec", type=float, default=12.0)
    parser.add_argument(
        "--evidence",
        type=Path,
        default=SIMULATOR_ROOT / "generated" / "dual_robot" / "latest_safety_evidence.json",
    )
    args = parser.parse_args()

    layout = load_layout(args.config)
    evidence: dict[str, Any] = {
        "profile": layout["profile"],
        "hold_marker_distance_m": layout["hold_marker_distance_m"],
        "approach_marker_distance_m": layout["approach_marker_distance_m"],
        "generated_at_epoch": time.time(),
    }
    evidence["readiness"] = wait_ready(layout, args.ready_timeout_sec)
    if args.scenario in ("all", "traffic"):
        evidence["traffic_scenario"] = run_traffic(layout, args.command_timeout_sec)
    if args.scenario in ("all", "collision"):
        collision_path = args.evidence.with_name("collision_stop_evidence.json")
        evidence["collision_scenario"] = run_collision(layout["robots"][0], collision_path, args.collision_timeout_sec)
    evidence["passed"] = True
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "passed": True,
        "evidence": str(args.evidence),
        "traffic_wait_observed": bool(
            evidence.get("traffic_scenario", {}).get("observed_traffic_states")
        ),
        "collision_stop_observed": evidence.get("collision_scenario", {}).get("stop_observed"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
