"""Robot connectivity and localization payload helpers."""
import math
import os
import time

from fastapi import HTTPException

from nav_app.config import active_robot_profile, current_ros_domain_id
from nav_app.runtime import runtime
from nav_app.settings import ACTIVE_ROBOT_ID, is_simulation_mode
from nav_app.util.time import utc_now as _utc_now
from nav_app.adapters.callbacks import post_main_callback as _post_main_callback
from nav_app.services.status_helpers import robot_state_from_mission_status
from nav_app.services.capabilities import active_lift_status, profile_capabilities
from nav_app.services.lift_backends import lift_provenance
from nav_app.services.localization import GLOBAL_SEARCH, LocalizationGate, global_search_config
from nav_app.services.scan_map_alignment import alignment_config

def active_bridge_robot_id():
    return active_robot_profile().get("bridge_robot_id")


def aruco_detection_topic():
    profile = active_robot_profile()
    configured = os.getenv("ARUCO_DETECTION_TOPIC") or profile.get("aruco_detection_topic")
    if configured:
        return configured
    bridge_robot_id = profile.get("bridge_robot_id") or "tb3_1"
    return f"/mission/{bridge_robot_id}/aruco/detections"


def cmd_vel_subscribers():
    if not runtime.navigator:
        return []
    return runtime.navigator.cmd_vel_subscribers()


def cmd_vel_subscriber_count():
    return len(cmd_vel_subscribers())


def active_robot_online():
    if not runtime.navigator:
        return False
    if is_simulation_mode():
        return True
    if runtime.mission_manager and runtime.mission_manager.dry_run:
        return True
    return cmd_vel_subscriber_count() > 0


def command_accepting(is_emergency: bool = False):
    if not runtime.navigator:
        return False
    dry_run = bool(runtime.mission_manager and runtime.mission_manager.dry_run)
    localization_required = not (dry_run or is_simulation_mode())
    nav2_ready = bool(
        dry_run
        or is_simulation_mode()
        or getattr(runtime.navigator, "nav2_ready", False)
    )
    return bool(
        not is_emergency
        and nav2_ready
        and active_robot_online()
        and (not localization_required or localization_health()["localized"])
    )


def localization_gate():
    profile = active_robot_profile()
    if runtime.localization is None or runtime.localization.profile is not profile:
        runtime.localization = LocalizationGate(profile)
    return runtime.localization


def _global_localization_request(gate, strategy="observe_only", allow_motion=False):
    """Build one profile-derived search contract for automatic and explicit starts."""
    config = global_search_config(gate.profile)
    return {
        **config,
        "strategy": str(strategy),
        "allow_motion": bool(allow_motion),
        "covariance_limits": {
            "x": gate.config["max_covariance_x"],
            "y": gate.config["max_covariance_y"],
            "yaw": gate.config["max_covariance_yaw"],
        },
        "active_map_yaml": gate.profile.get("active_map_yaml"),
        "scan_map_alignment": alignment_config(gate.profile),
    }


def localization_health():
    gate = localization_gate()
    observation = None
    if gate.state == "UNLOCALIZED":
        gate.start(None)
        if runtime.navigator and hasattr(runtime.navigator, "request_global_localization"):
            runtime.navigator.request_global_localization(_global_localization_request(gate))
    if runtime.navigator and hasattr(runtime.navigator, "localization_observation"):
        observation = runtime.navigator.localization_observation()
        if isinstance(observation, dict):
            samples = observation.get("amcl_samples") or []
            last_receipt = gate.last_amcl_receipt_monotonic
            unseen_samples = []
            for sample in samples:
                try:
                    receipt_monotonic = float(sample.get("receipt_monotonic"))
                except (AttributeError, TypeError, ValueError):
                    continue
                if not math.isfinite(receipt_monotonic):
                    continue
                if last_receipt is None or receipt_monotonic > last_receipt:
                    unseen_samples.append((receipt_monotonic, sample))
            for receipt_monotonic, sample in sorted(unseen_samples, key=lambda item: item[0]):
                sample_observation = {**observation, "amcl": sample}
                sample_observation.pop("amcl_samples", None)
                sample_observation["receipt_monotonic"] = receipt_monotonic
                gate.observe(sample_observation)

            # History proves convergence independently of HTTP poll frequency;
            # this final observation separately enforces current scan/TF liveness.
            current_observation = dict(observation)
            current_observation.pop("amcl_samples", None)
            gate.observe(current_observation)
    alignment = _scan_map_alignment_admission(gate)
    health = gate.health()
    if isinstance(observation, dict):
        health["tf_status_reason"] = observation.get("tf_status_reason")
        health["tf_source_age_sec"] = observation.get("tf_source_age_sec")
    if alignment is not None:
        health["scan_map_alignment"] = alignment
        config = alignment_config(gate.profile)
        if config.get("enabled") and not alignment.get("accepted"):
            health["localized"] = False
            if health.get("state") == "LOCALIZED":
                if alignment.get("reason") == "confirmation_pending":
                    health["state"] = "CONVERGING"
                    health["reason"] = "scan_map_alignment_confirmation_pending"
                elif alignment.get("reason") == "global_localization_search_active":
                    health["state"] = "CONVERGING"
                    health["reason"] = "global_localization_search_active"
                elif alignment.get("refinement_required"):
                    health["state"] = "CONVERGING"
                    health["reason"] = "scan_map_alignment_refinement_pending"
    return health


def _scan_map_alignment_admission(gate):
    navigator = runtime.navigator
    if not navigator or gate.state != "LOCALIZED" or not hasattr(navigator, "localization_alignment_observation"):
        status = getattr(navigator, "scan_map_alignment_status", None) if navigator else None
        return dict(status) if isinstance(status, dict) else None
    if (
        hasattr(navigator, "global_localization_search_active")
        and navigator.global_localization_search_active()
    ):
        search = (
            navigator.global_localization_search_status()
            if hasattr(navigator, "global_localization_search_status")
            else {}
        )
        return {
            "accepted": False,
            "refinement_required": False,
            "reason": "global_localization_search_active",
            "search": search,
        }
    alignment = navigator.localization_alignment_observation(gate.profile)
    if alignment.get("accepted"):
        return alignment
    if alignment.get("reason") == "confirmation_pending":
        return alignment
    if not alignment.get("refinement_required"):
        gate.reject(f"scan_map_alignment_{alignment.get('reason', 'failed')}")
        return alignment
    config = alignment_config(gate.profile)
    if int(alignment.get("attempts", 0)) >= int(config["max_refinement_passes"]):
        gate.reject("scan_map_alignment_refinement_pass_limit")
        return {**alignment, "reason": "refinement_pass_limit"}
    if not hasattr(navigator, "claim_scan_map_refinement"):
        gate.reject("scan_map_alignment_refinement_claim_unavailable")
        return {**alignment, "reason": "refinement_claim_unavailable"}
    claimed_alignment = navigator.claim_scan_map_refinement(alignment)
    if claimed_alignment is None:
        status = getattr(navigator, "scan_map_alignment_status", alignment)
        return dict(status)
    corrected_pose = claimed_alignment.get("corrected_pose") or {}
    seed = {
        "map_id": gate.config["map_id"],
        "map_metadata_identity": gate.config["map_metadata_identity"],
        "saved_at_epoch_sec": time.time(),
        "pose": corrected_pose,
    }
    gate.start(seed)
    search = {
        **global_search_config(gate.profile),
        "covariance_limits": {
            "x": gate.config["max_covariance_x"],
            "y": gate.config["max_covariance_y"],
            "yaw": gate.config["max_covariance_yaw"],
        },
        "scan_map_alignment": config,
        "refinement_initial_covariance": config.get("initial_covariance") or {
            "x": 0.02,
            "y": 0.02,
            "yaw": 0.01,
        },
    }
    requested = navigator.apply_scan_map_refinement(claimed_alignment, search)
    if requested is None:
        gate.reject("scan_map_alignment_refinement_unavailable")
    return dict(getattr(navigator, "scan_map_alignment_status", claimed_alignment))


def start_localization(seed=None):
    """Start a seed attempt or fail-closed global search when no valid seed exists."""
    gate = localization_gate()
    state = gate.start(seed)
    if runtime.navigator:
        if state == GLOBAL_SEARCH and hasattr(runtime.navigator, "request_global_localization"):
            runtime.navigator.request_global_localization(_global_localization_request(gate))
        elif state != GLOBAL_SEARCH and seed and hasattr(runtime.navigator, "set_initial_pose"):
            runtime.navigator.set_initial_pose(seed.get("pose", seed), frame_id="map")
    return gate.health()


def start_global_localization(strategy="observe_only", allow_motion=False):
    """Start map-wide AMCL search under the robot profile's fail-closed motion policy."""
    profile = active_robot_profile()
    config = global_search_config(profile)
    strategy = str(strategy or config["default_strategy"])
    if strategy not in config["allowed_strategies"]:
        raise ValueError(f"global localization strategy is not allowed: {strategy}")
    if strategy != "observe_only" and config.get("motion_requires_explicit_request", True) and not allow_motion:
        raise ValueError("bounded localization motion requires allow_motion=true")
    gate = localization_gate()
    gate.start(None)
    request = _global_localization_request(gate, strategy, allow_motion)
    search = runtime.navigator.request_global_localization(request)
    return {"localization": gate.health(), "search": search, "policy": config}


def assert_active_bridge_robot(robot_name: str, noun: str = "요청"):
    if robot_name != active_bridge_robot_id():
        raise HTTPException(
            status_code=409,
            detail=(
                f"이 Movement API 프로세스는 {active_bridge_robot_id()}만 담당합니다. "
                f"{robot_name} {noun}은 해당 robot_name 프로세스로 보내야 합니다."
            ),
        )


def localization_reason(pose, online: bool):
    if not runtime.navigator:
        return "unknown"
    if not online:
        return "robot_offline"
    return localization_health()["reason"]


def localization_payload(robot_name: str):
    pose = runtime.navigator.get_current_pose() if runtime.navigator else None
    online = active_robot_online()
    amcl_pose_received = bool(runtime.navigator and runtime.navigator.has_amcl_pose())
    health = localization_health()
    search = (
        runtime.navigator.global_localization_search_status()
        if runtime.navigator and hasattr(runtime.navigator, "global_localization_search_status")
        else None
    )
    reason = localization_reason(pose, online)
    pose_age = pose.get("age_sec") if pose else None
    return {
        "robot_name": robot_name,
        "robot_id": ACTIVE_ROBOT_ID,
        "ros_domain_id": current_ros_domain_id(),
        "map_frame": "map",
        "robot_online": online,
        "cmd_vel_topic": "/cmd_vel",
        "cmd_vel_subscribers": cmd_vel_subscriber_count(),
        "cmd_vel_subscriber_nodes": cmd_vel_subscribers(),
        "localized": health["localized"],
        **health,
        "localization_required": not (runtime.mission_manager.dry_run if runtime.mission_manager else False) and not is_simulation_mode(),
        "pose": pose,
        "pose_source": pose.get("source") if pose else None,
        "last_pose_age_sec": pose_age,
        "pose_age_sec": pose_age,
        "amcl_pose_received": amcl_pose_received,
        "search": search,
        "initial_pose_required": not health["localized"] and online,
        "reason": reason,
        "action_required": reason != "ok",
        "reported_at": _utc_now(),
    }


def movement_robot_status_payload(robot_name=None, command_id=None, state=None):
    pose = None
    online = active_robot_online()
    if not runtime.navigator or not runtime.mission_manager:
        battery = 0.0
        state = state or "offline"
    else:
        snapshot = runtime.mission_manager.get_status_snapshot()
        battery = snapshot["battery"]
        pose = snapshot.get("pose")
        state = state or robot_state_from_mission_status(runtime.mission_manager.mission_status)
    if not online:
        state = "offline"
    health = localization_health()
    provenance = lift_provenance(backend=getattr(runtime, "lift_client", None))
    return {
        "robot_name": robot_name or active_bridge_robot_id(),
        "robot_online": online,
        "command_accepting": command_accepting(),
        "online": online,
        "cmd_vel_topic": "/cmd_vel",
        "cmd_vel_subscribers": cmd_vel_subscriber_count(),
        "cmd_vel_subscriber_nodes": cmd_vel_subscribers(),
        "state": state,
        "current_command_id": command_id,
        "battery": battery,
        "pose": pose,
        "localized": health["localized"],
        "localization": health,
        "simulation_mode": is_simulation_mode(),
        "capabilities": profile_capabilities(active_robot_profile()),
        "lift": active_lift_status(active_robot_profile()),
        **provenance,
        "reported_at": _utc_now(),
    }


def report_movement_robot_status(robot_name: str, command_id=None, state=None):
    return _post_main_callback(
        f"/movement/robots/{robot_name}/status",
        movement_robot_status_payload(robot_name=robot_name, command_id=command_id, state=state),
    )


def movement_robot_summary():
    profile = active_robot_profile()
    command_id = None
    if runtime.mission_manager and runtime.mission_manager.mission_status in ("ACCEPTED", "RUNNING", "EMERGENCY", "CHARGING"):
        command_id = runtime.mission_manager.current_mission_id
    pose = runtime.navigator.get_current_pose() if runtime.navigator else None
    online = active_robot_online()
    state = robot_state_from_mission_status(runtime.mission_manager.mission_status) if runtime.mission_manager else "offline"
    if not online:
        state = "offline"
    health = localization_health()
    provenance = lift_provenance(backend=getattr(runtime, "lift_client", None))
    return {
        "robot_name": profile.get("bridge_robot_id"),
        "robot_id": profile.get("robot_id"),
        "online": online,
        "cmd_vel_topic": "/cmd_vel",
        "cmd_vel_subscribers": cmd_vel_subscriber_count(),
        "cmd_vel_subscriber_nodes": cmd_vel_subscribers(),
        "state": state,
        "current_command_id": command_id,
        "battery": runtime.navigator.battery_level if runtime.navigator else 0.0,
        "pose": pose,
        "localized": health["localized"],
        "localization": health,
        "simulation_mode": is_simulation_mode(),
        "reported_at": _utc_now(),
        "ros_domain_id": current_ros_domain_id(),
        "namespace": profile.get("namespace"),
        "capabilities": profile_capabilities(profile),
        "lift": active_lift_status(profile),
        **provenance,
    }
