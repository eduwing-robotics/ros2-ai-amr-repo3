#!/usr/bin/env python3
"""Validate the LMS scenario contract without starting ROS or moving a robot."""

from __future__ import annotations

import json

from route_builder import build_inbound2_storage_b_scenario


def main() -> int:
    scenario = build_inbound2_storage_b_scenario(dry_run=True)
    business_steps = scenario["business_steps"]
    physical_steps = scenario["steps"]

    assert scenario["scenario_id"] == "inbound2-storage-b"
    assert scenario["scenario_version"] == 1
    assert scenario["robot_name"] == "tb3_2"
    assert len(business_steps) == 9
    assert len(physical_steps) == 15
    assert physical_steps[4]["action"] == "aruco_align"
    assert physical_steps[4]["payload"]["target_distance_m"] == 0.20
    assert physical_steps[5]["payload"]["fork_insert_enabled"] is False
    assert physical_steps[5]["payload"]["use_return_pose_key"] == "inbound2"
    assert physical_steps[9]["action"] == "aruco_align"
    assert physical_steps[9]["payload"]["target_distance_m"] == 0.18
    assert physical_steps[10]["payload"]["fork_insert_enabled"] is False
    assert physical_steps[10]["payload"]["use_return_pose_key"] == "storage_b"
    assert physical_steps[12]["payload"]["target_distance_m"] == 0.40
    assert physical_steps[12]["payload"]["final"] == "return_approach"
    assert physical_steps[13]["duration"] == 3.0
    assert physical_steps[14]["payload"]["target_distance_m"] == 0.20
    assert physical_steps[14]["payload"]["final"] == "hold"
    assert physical_steps[14]["payload"]["fork_insert_on_hold"] is False
    assert business_steps[3]["return_to_approach"] is True
    assert business_steps[6]["return_to_approach"] is True
    assert all(step["estimated_timeout_sec"] > 0 for step in business_steps)
    assert len(scenario["plan_hash"]) == 64

    print(json.dumps({
        "ok": True,
        "scenario_id": scenario["scenario_id"],
        "scenario_version": scenario["scenario_version"],
        "robot_name": scenario["robot_name"],
        "business_step_count": len(business_steps),
        "physical_step_count": len(physical_steps),
        "estimated_total_timeout_sec": scenario["estimated_total_timeout_sec"],
        "plan_hash": scenario["plan_hash"],
        "safety_contract": "calibrated ArUco 40cm-stop-20cm; no odom insert; final standby hold at 20cm",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
