from __future__ import annotations

import importlib
import re

from tests.support import NAV_SERVER_ROOT

ROOT = NAV_SERVER_ROOT

FIELD_SCENARIO_RUNNERS = (
    "run_center_slot_insert_test.sh",
    "run_center_slot_l2_lift_test.sh",
    "run_drive_insert_scenario.sh",
    "run_drive_scenario_loop.sh",
    "run_ekf_zone_approach_insert_test.sh",
    "run_in1_out1_out2_vision_test.sh",
    "run_inbound1_b_lv2_wait2_scenario.sh",
    "run_inbound1_c_wait2_scenario.sh",
    "run_inbound2_b_lv2_scenario.sh",
    "run_inbound2_b_outbound1_wait2_scenario.sh",
    "run_inbound2_c_lv2_wait2_resume.sh",
    "run_inbound2_c_lv2_wait2_scenario.sh",
    "run_lift_preset_experiment.sh",
    "run_out2_vision_resume.sh",
    "run_outbound2_a_wait2_scenario.sh",
    "run_wait1_wait2_vision_145_test.sh",
    "run_warehouse_abcd_vision_135_test.sh",
    "run_warehouse_slot_vision_test.sh",
)

MAPPING_TOOLS = (
    "draw_current_layout_review.py",
    "draw_layout_map.py",
    "draw_map_review.py",
    "draw_zone_mask.py",
    "generate_center_wall_waypoints.py",
    "generate_factory_grid_waypoints.py",
    "record_waypoint_pose.py",
)

TOP_LEVEL_OPERATOR_ENTRYPOINTS = (
    "sf_nav.sh",
    "start_nav_servers.sh",
    "nav_ops.sh",
    "start_all_tb3_2.sh",
    "setup_nav_server_env.sh",
    "check_all.sh",
    "run_nav_servers.sh",
    "run_nav2_with_initial_pose.sh",
    "run_domain_bridges.sh",
    "run_pi_camera_aruco.sh",
)

TEST_TAXONOMY_DIRECTORIES = (
    "unit",
    "contracts",
    "integration",
    "runtime",
    "experiments",
)


def read_repo_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def read_required_repo_text(relative_path: str) -> str:
    path = ROOT / relative_path
    assert path.is_file(), f"missing required repository file: {relative_path}"
    return path.read_text(encoding="utf-8")


def collapsed(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def assert_mentions_role(text: str, script_name: str, *role_patterns: str) -> None:
    normalized = collapsed(text)
    assert f"`{script_name}`" in normalized
    assert any(re.search(pattern, normalized, flags=re.IGNORECASE) for pattern in role_patterns)


def assert_scripts_moved_from_top_level(file_names: tuple[str, ...], destination: str) -> None:
    for file_name in file_names:
        assert (ROOT / "scripts" / destination / file_name).is_file(), (
            f"missing moved script: scripts/{destination}/{file_name}"
        )
        assert not (ROOT / "scripts" / file_name).exists(), (
            f"script still at top level: scripts/{file_name}"
        )


def test_field_scenario_runners_live_under_scripts_scenarios_field():
    assert_scripts_moved_from_top_level(FIELD_SCENARIO_RUNNERS, "scenarios/field")


def test_mapping_tools_live_under_scripts_tools_mapping():
    assert_scripts_moved_from_top_level(MAPPING_TOOLS, "tools/mapping")


def test_canonical_and_configured_entrypoints_stay_top_level_scripts():
    for script_name in TOP_LEVEL_OPERATOR_ENTRYPOINTS:
        assert (ROOT / "scripts" / script_name).is_file(), f"missing top-level entrypoint: scripts/{script_name}"


def test_tests_are_grouped_by_taxonomy_with_only_shared_support_at_top_level():
    tests_root = ROOT / "tests"

    for directory_name in TEST_TAXONOMY_DIRECTORIES:
        assert (tests_root / directory_name).is_dir(), f"missing test taxonomy directory: tests/{directory_name}"

    assert (tests_root / "conftest.py").is_file()
    assert (tests_root / "support.py").is_file()
    assert sorted(path.name for path in tests_root.glob("test_*.py")) == []


def test_tests_support_exposes_nav_server_root():
    support_path = ROOT / "tests" / "support.py"

    assert support_path.is_file()
    assert importlib.import_module("tests.support").NAV_SERVER_ROOT == ROOT


def test_readme_identifies_sf_nav_as_canonical_runtime_entrypoint():
    readme = read_repo_text("README.md")

    assert "`scripts/sf_nav.sh`" in readme
    assert re.search(r"정본.*`sf_nav\.sh`.*runtime profile", collapsed(readme))


def test_readme_labels_legacy_runtime_scripts_by_role():
    readme = collapsed(read_repo_text("README.md"))

    assert re.search(r"`start_nav_servers\.sh`.*호환\s*wrapper", readme)
    assert re.search(r"`nav_ops\.sh`.*convenience|`nav_ops\.sh`.*helper", readme)
    assert re.search(r"`start_all_tb3_2\.sh`.*현장\s*helper", readme)


def test_scripts_guide_exists_for_runtime_entrypoint_classification():
    assert (ROOT / "scripts" / "README.md").is_file()


def test_scripts_guide_classifies_operator_entrypoints_by_role():
    guide = read_required_repo_text("scripts/README.md")

    assert_mentions_role(guide, "sf_nav.sh", r"`sf_nav\.sh`.*canonical", r"`sf_nav\.sh`.*정본")
    assert_mentions_role(
        guide,
        "start_nav_servers.sh",
        r"`start_nav_servers\.sh`.*compat",
        r"`start_nav_servers\.sh`.*호환",
    )
    assert_mentions_role(
        guide,
        "nav_ops.sh",
        r"`nav_ops\.sh`.*convenience",
        r"`nav_ops\.sh`.*편의",
        r"`nav_ops\.sh`.*helper",
    )
    assert_mentions_role(
        guide,
        "start_all_tb3_2.sh",
        r"`start_all_tb3_2\.sh`.*field",
        r"`start_all_tb3_2\.sh`.*현장",
        r"`start_all_tb3_2\.sh`.*helper",
    )


def test_scripts_guide_marks_package_first_runtime_components_not_operator_commands():
    guide = read_required_repo_text("scripts/README.md")
    normalized = collapsed(guide)

    assert_mentions_role(
        guide,
        "run_nav_servers.sh",
        r"`run_nav_servers\.sh`.*internal",
        r"`run_nav_servers\.sh`.*내부",
    )
    assert "`nav_app.app:app`" in normalized
    assert "`nav_app/services/`" in normalized
    assert "`nav_server.py`" not in normalized
    assert not (ROOT / "scripts" / "nav_server.py").exists()
    assert re.search(
        r"run_nav_servers\.sh.*(not a normal operator command|operator command가 아니다|운영자 명령이 아니다)",
        normalized,
        flags=re.IGNORECASE,
    )


def test_script_guide_is_linked_from_readme_or_docs_index():
    readme = read_repo_text("README.md")
    docs_index = read_repo_text("docs/README.md")

    assert "scripts/README.md" in readme or "scripts/README.md" in docs_index


def test_docs_taxonomy_keeps_operational_docs_under_docs_and_records_under_worklog():
    docs_readme = read_repo_text("docs/README.md")

    assert "[운영](runbook/OPERATIONS.md)" in docs_readme
    assert "[worklog](../worklog/README.md)" in docs_readme
    assert not (ROOT / "docs" / "handoff").exists()


def test_nav_ops_forwards_api_lifecycle_commands_to_start_nav_servers():
    nav_ops = read_repo_text("scripts/nav_ops.sh")

    assert "start|dry-run|stop|restart|status)" in nav_ops
    assert 'exec "$SCRIPT_DIR/start_nav_servers.sh" "$cmd"' in nav_ops
    assert '"$SCRIPT_DIR/sf_nav.sh"' not in nav_ops


def test_adr_001_defines_package_first_nav_layout_contract():
    adr = read_repo_text("docs/adr/ADR_001_PACKAGE_FIRST_NAV_LAYOUT.md")
    normalized = collapsed(adr)

    assert "import되는 애플리케이션 로직은 `nav_app/` 패키지에만 둔다" in adr
    assert "`scripts/`에는 운영자가 직접 실행하는 시작·검증·현장 도구만 둔다" in adr
    assert "`nav_app.app:app`" in normalized
    assert "`python3 -m uvicorn nav_app.app:app`" in normalized
    assert "애플리케이션 서비스는 `nav_app/services/`에서 import한다" in adr
    for entrypoint in ("sf_nav.sh", "run_nav_servers.sh", "smoke_*.sh"):
        assert f"`{entrypoint}`" in adr


def test_package_first_service_modules_live_under_nav_app_services_not_scripts():
    moved_services = (
        "route_builder.py",
        "logistics_navigator.py",
        "mission_manager.py",
        "traffic_manager.py",
        "zone_lock_manager.py",
        "aruco_detector_activation.py",
    )

    for module_name in moved_services:
        assert (ROOT / "nav_app" / "services" / module_name).is_file()
        assert not (ROOT / "scripts" / module_name).exists()


def test_active_agv_rviz_reference_is_detectable_from_nav2_launcher():
    launcher = read_repo_text("scripts/run_nav2_with_initial_pose.sh")
    rviz_config = ROOT / "config" / "rviz" / "agv_map_debug.rviz"

    assert rviz_config.exists()
    assert "RVIZ_CONFIG_FILE=\"${RVIZ_CONFIG_FILE:-$ROOT/config/rviz/agv_map_debug.rviz}\"" in launcher
    assert "/agv_path_markers" in rviz_config.read_text(encoding="utf-8")


def test_experimental_agv_docs_are_not_movement_api_dispatch_contracts():
    algorithm = collapsed(read_repo_text("docs/reference/NAV_ALGORITHM.md"))

    assert "AGV graph planner" in algorithm
    assert "orthogonal follower" in algorithm
    assert "현재 Movement API dispatch와 연결되지 않았으므로" in algorithm
    assert "운영 알고리즘이나 합격 근거로 사용하지 않는다" in algorithm


def test_agv_graph_experiment_bundle_has_expected_primary_layout():
    expected_files = (
        "README.md",
        "__init__.py",
        "agv_grid_planner.py",
        "agv_graph_builder.py",
        "agv_orthogonal_follower.py",
        "validate_agv_graph.py",
        "launch/agv_follower.launch.py",
        "config/agv_follower.yaml",
        "map/agv_waypoint_graph.yaml",
    )

    for relative_path in expected_files:
        path = ROOT / "experiments" / "agv_graph" / relative_path
        assert path.is_file(), f"missing AGV graph experiment file: {path.relative_to(ROOT)}"


def test_agv_graph_files_are_no_longer_primary_top_level_runtime_files():
    old_primary_files = (
        "scripts/agv_grid_planner.py",
        "scripts/agv_graph_builder.py",
        "scripts/agv_orthogonal_follower.py",
        "scripts/validate_agv_graph.py",
        "launch/agv_follower.launch.py",
        "config/agv_follower.yaml",
        "map/agv_waypoint_graph.yaml",
    )

    for relative_path in old_primary_files:
        assert not (ROOT / relative_path).exists(), f"AGV graph file still at old primary path: {relative_path}"


def test_agv_rviz_debug_config_remains_primary_runtime_reference():
    assert (ROOT / "config" / "rviz" / "agv_map_debug.rviz").is_file()


def test_scripts_guide_points_to_agv_graph_experiment_bundle_not_moved_top_level_scripts():
    guide = read_required_repo_text("scripts/README.md")
    normalized = collapsed(guide)

    assert "experiments/agv_graph/" in normalized
    assert not re.search(r"(?m)^\s*[-*]\s+`(?:agv_grid_planner|agv_graph_builder|agv_orthogonal_follower|validate_agv_graph)\.py`", guide)
    assert not re.search(r"(?m)^\s*[-*]\s+`agv_follower\.launch\.py`", guide)
    assert not re.search(r"(?m)^\s*[-*]\s+`agv_follower\.yaml`", guide)
    assert not re.search(r"(?m)^\s*[-*]\s+`agv_waypoint_graph\.yaml`", guide)


def test_worklog_index_does_not_have_malformed_nested_list_prefixes():
    worklog_index = read_repo_text("worklog/README.md")

    assert not re.search(r"(?m)^-\s+-\s+", worklog_index)


def test_markdown_docs_do_not_reference_flat_test_paths():
    stale_flat_test_path = re.compile(r"tests/test_[A-Za-z0-9_]+\.py")
    markdown_paths = [ROOT / "README.md"]
    markdown_paths.extend(sorted((ROOT / "docs").glob("**/*.md")))
    markdown_paths.extend(sorted((ROOT / "worklog").glob("**/*.md")))

    offenders: list[str] = []
    for path in markdown_paths:
        text = path.read_text(encoding="utf-8")
        relative_path = path.relative_to(ROOT)
        offenders.extend(f"{relative_path}:{match.group(0)}" for match in stale_flat_test_path.finditer(text))

    assert offenders == [], "stale flat test paths found: " + ", ".join(offenders)
