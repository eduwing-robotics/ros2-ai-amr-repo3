#!/usr/bin/env python3
"""Record the robot's current map pose into map/zones.json waypoints."""

import argparse
import json
import math
import os
import shutil
import sys
import time
from pathlib import Path

import rclpy
from geometry_msgs.msg import PoseWithCovarianceStamped
from rclpy.duration import Duration
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from tf2_ros import Buffer, TransformException, TransformListener


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ZONES = ROOT / "map" / "zones.json"


def yaw_from_quaternion(q):
    return math.atan2(
        2.0 * (q.w * q.z + q.x * q.y),
        1.0 - 2.0 * (q.y * q.y + q.z * q.z),
    )


def rounded_pose(x, y, yaw):
    return round(float(x), 3), round(float(y), 3), round(float(yaw), 3)


class PoseRecorder:
    def __init__(self, timeout_sec, target_frame, base_frames):
        self.timeout_sec = float(timeout_sec)
        self.target_frame = target_frame
        self.base_frames = base_frames
        self.node = rclpy.create_node("record_waypoint_pose")
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self.node)
        self.amcl_pose = None

        qos = QoSProfile(depth=1)
        qos.reliability = ReliabilityPolicy.RELIABLE
        qos.durability = DurabilityPolicy.TRANSIENT_LOCAL
        self.node.create_subscription(PoseWithCovarianceStamped, "/amcl_pose", self._amcl_cb, qos)

    def _amcl_cb(self, msg):
        self.amcl_pose = msg

    def read_pose(self, source):
        if getattr(self, "_samples", 1) <= 1:
            return self._read_pose_once(source)
        readings = []
        for i in range(self._samples):
            readings.append(self._read_pose_once(source))
            if i + 1 < self._samples:
                time.sleep(0.4)
        xs = [r["x"] for r in readings]
        ys = [r["y"] for r in readings]
        yaws = [r["theta"] for r in readings]
        cx = round(sum(xs) / len(xs), 3)
        cy = round(sum(ys) / len(ys), 3)
        sy = sum(math.sin(y) for y in yaws)
        cyaw = sum(math.cos(y) for y in yaws)
        ctheta = round(math.atan2(sy, cyaw), 3)
        out = dict(readings[-1])
        out.update({"x": cx, "y": cy, "theta": ctheta, "samples": len(readings)})
        return out

    def _read_pose_once(self, source):
        deadline = time.monotonic() + self.timeout_sec
        last_error = None
        while time.monotonic() < deadline:
            rclpy.spin_once(self.node, timeout_sec=0.1)
            if source in ("tf", "auto"):
                for base_frame in self.base_frames:
                    try:
                        transform = self.tf_buffer.lookup_transform(
                            self.target_frame,
                            base_frame,
                            rclpy.time.Time(),
                            timeout=Duration(seconds=0.05),
                        )
                        t = transform.transform.translation
                        q = transform.transform.rotation
                        x, y, yaw = rounded_pose(t.x, t.y, yaw_from_quaternion(q))
                        return {
                            "source": "tf",
                            "frame": self.target_frame,
                            "child_frame": base_frame,
                            "x": x,
                            "y": y,
                            "theta": yaw,
                        }
                    except TransformException as exc:
                        last_error = str(exc)

            if source in ("amcl", "auto") and self.amcl_pose is not None:
                pose = self.amcl_pose.pose.pose
                x, y, yaw = rounded_pose(
                    pose.position.x,
                    pose.position.y,
                    yaw_from_quaternion(pose.orientation),
                )
                return {
                    "source": "amcl_pose",
                    "frame": self.amcl_pose.header.frame_id or self.target_frame,
                    "child_frame": None,
                    "x": x,
                    "y": y,
                    "theta": yaw,
                }

        detail = f" last_tf_error={last_error}" if last_error else ""
        raise TimeoutError(f"pose read timed out after {self.timeout_sec:.1f}s.{detail}")

    def destroy(self):
        self.node.destroy_node()


def update_waypoint(zones_path, waypoint, pose, create, backup, theta_only=False, max_xy_error_m=None):
    data = json.loads(zones_path.read_text(encoding="utf-8"))
    waypoints = data.setdefault("waypoints", {})
    if waypoint not in waypoints:
        if not create:
            known = ", ".join(sorted(waypoints.keys()))
            raise KeyError(f"unknown waypoint '{waypoint}'. Use --create to add it. Known: {known}")
        waypoints[waypoint] = {"role": waypoint}

    old = dict(waypoints[waypoint])
    if theta_only and max_xy_error_m is not None:
        saved_x = old.get("x")
        saved_y = old.get("y")
        if saved_x is not None and saved_y is not None:
            drift_m = math.hypot(float(pose["x"]) - float(saved_x), float(pose["y"]) - float(saved_y))
            if drift_m > float(max_xy_error_m):
                raise ValueError(
                    f"pose xy drift {drift_m:.3f} m exceeds max {float(max_xy_error_m):.3f} m "
                    f"(saved x={saved_x} y={saved_y}, current x={pose['x']} y={pose['y']}); "
                    "fix Nav2 approach before recording theta"
                )
    if theta_only:
        waypoints[waypoint]["theta"] = pose["theta"]
    else:
        waypoints[waypoint]["x"] = pose["x"]
        waypoints[waypoint]["y"] = pose["y"]
        waypoints[waypoint]["theta"] = pose["theta"]

    if backup:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup_path = zones_path.with_name(f"{zones_path.name}.{stamp}.bak")
        shutil.copy2(zones_path, backup_path)
    else:
        backup_path = None

    zones_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return old, waypoints[waypoint], backup_path


def parse_args():
    parser = argparse.ArgumentParser(description="Save current robot map pose into a zones.json waypoint.")
    parser.add_argument("waypoint", help="waypoint id in map/zones.json, e.g. inbound_slot_1_approach")
    parser.add_argument("--zones", type=Path, default=DEFAULT_ZONES)
    parser.add_argument("--source", choices=("auto", "tf", "amcl"), default="auto")
    parser.add_argument("--target-frame", default="map")
    parser.add_argument("--base-frame", action="append", dest="base_frames")
    parser.add_argument("--timeout-sec", type=float, default=5.0)
    parser.add_argument("--samples", type=int, default=1, help="average N pose reads while stopped (default 1)")
    parser.add_argument("--theta-only", action="store_true", help="update theta only; keep existing x/y")
    parser.add_argument(
        "--max-xy-error-m",
        type=float,
        default=None,
        help="theta-only: refuse save if current xy drifts farther than this from saved waypoint (default: RECORD_MAX_XY_ERROR_M or 0.03)",
    )
    parser.add_argument("--create", action="store_true", help="create waypoint if it does not exist")
    parser.add_argument("--no-backup", action="store_true", help="do not write a timestamped backup")
    return parser.parse_args()


def main():
    args = parse_args()
    zones_path = args.zones.expanduser().resolve()
    base_frames = args.base_frames or ["base_link", "base_footprint"]

    if not zones_path.exists():
        print(f"zones file not found: {zones_path}", file=sys.stderr)
        return 2

    rclpy.init()
    recorder = PoseRecorder(args.timeout_sec, args.target_frame, base_frames)
    recorder._samples = max(1, int(args.samples))
    max_xy_error_m = args.max_xy_error_m
    if max_xy_error_m is None and args.theta_only:
        max_xy_error_m = float(os.getenv("RECORD_MAX_XY_ERROR_M", "0.02"))
    try:
        pose = recorder.read_pose(args.source)
        old, new, backup_path = update_waypoint(
            zones_path,
            args.waypoint,
            pose,
            create=args.create,
            backup=not args.no_backup,
            theta_only=args.theta_only,
            max_xy_error_m=max_xy_error_m,
        )
    finally:
        recorder.destroy()
        rclpy.shutdown()

    print(f"saved waypoint: {args.waypoint}")
    print(f"source: {pose['source']} frame={pose['frame']} child={pose['child_frame']}", end="")
    if pose.get("samples"):
        print(f" samples={pose['samples']} (averaged)", end="")
    print()
    print(f"old: x={old.get('x')} y={old.get('y')} theta={old.get('theta')}")
    print(f"new: x={new['x']} y={new['y']} theta={new['theta']}")
    if backup_path:
        print(f"backup: {backup_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
