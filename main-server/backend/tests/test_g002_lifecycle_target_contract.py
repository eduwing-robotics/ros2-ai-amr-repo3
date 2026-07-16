"""Dependency-free red contracts for the G002 lifecycle and safety target."""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = BACKEND_ROOT / "app"


def _source(relative: str) -> str:
    return (APP_ROOT / relative).read_text(encoding="utf-8")


def _unknown_cargo_raises_http_409(source: str) -> bool:
    tree = ast.parse(source)

    def is_unknown_cargo_guard(node: ast.AST) -> bool:
        if (
            not isinstance(node, ast.Compare)
            or len(node.ops) != 1
            or not isinstance(node.ops[0], ast.Eq)
        ):
            return False
        operands = (node.left, *node.comparators)
        return any(
            isinstance(item, ast.Name) and item.id == "cargo_state" for item in operands
        ) and any(
            isinstance(item, ast.Constant) and item.value == "UNKNOWN"
            for item in operands
        )

    def is_http_409_raise(node: ast.AST) -> bool:
        if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
            return False
        call = node.exc
        exception_name = (
            call.func.id
            if isinstance(call.func, ast.Name)
            else call.func.attr
            if isinstance(call.func, ast.Attribute)
            else None
        )
        return exception_name == "HTTPException" and any(
            keyword.arg == "status_code"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value == 409
            for keyword in call.keywords
        )

    functions = (
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    )
    for function in functions:
        function_arguments = function.args.args + function.args.kwonlyargs
        if not any(argument.arg == "cargo_state" for argument in function_arguments):
            continue
        for branch in (node for node in ast.walk(function) if isinstance(node, ast.If)):
            if is_unknown_cargo_guard(branch.test) and any(
                is_http_409_raise(node)
                for statement in branch.body
                for node in ast.walk(statement)
            ):
                return True
    return False


def _has_typed_accepted_post_route(source: str, path: str) -> bool:
    tree = ast.parse(source)
    for function in (
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ):
        for decorator in function.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            if not (
                isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == "post"
                and decorator.args
                and isinstance(decorator.args[0], ast.Constant)
                and decorator.args[0].value == path
            ):
                continue
            keywords = {keyword.arg: keyword.value for keyword in decorator.keywords}
            response_model = keywords.get("response_model")
            status_code = keywords.get("status_code")
            return (
                isinstance(response_model, ast.Name)
                and response_model.id == "WorkOrderStopResult"
                and isinstance(status_code, ast.Attribute)
                and status_code.attr == "HTTP_202_ACCEPTED"
            )
    return False


def test_work_order_safe_stop_has_route_and_single_service_entrypoint() -> None:
    router = _source("api/routers/work_orders.py")
    service = _source("services/work_orders_pg.py")

    assert _has_typed_accepted_post_route(router, "/work-orders/{order_id}/stop")
    assert "def stop_work_order(" in service
    assert "request_work_order_stop" in service
    assert "AWAITING_OPERATOR" in service
    assert "CANCEL_REQUESTED" in service


def test_recovery_exposes_only_safe_move_and_manual_abort() -> None:
    recovery = _source("services/task_recovery.py")
    task_router = _source("api/routers/tasks.py")

    assert 'RecoveryStrategy = Literal["safe_move", "manual_abort"]' in recovery
    assert "safe_replan" not in recovery
    assert '"restart"' not in recovery
    assert 'body.get("strategy", "safe_move")' in task_router
    assert _unknown_cargo_raises_http_409(recovery)


def test_robot_enablement_and_estop_tristate_are_public_contracts() -> None:
    robot_models = _source("models/robots.py")
    robots = _source("api/routers/robots.py")
    callbacks = _source("services/movement_callbacks.py")

    assert "enabled: bool" in robot_models
    assert "enabled: bool | None = None" in robot_models
    assert "enabled" in robots
    for state in ("cleared", "active", "unknown"):
        assert state in callbacks
    assert "offline" in callbacks.lower()
    assert "enabled_ids" not in callbacks
    assert 'state": "disabled"' not in callbacks


def test_realtime_pose_is_process_memory_only_and_canonical() -> None:
    pose_runtime = APP_ROOT / "services" / "pose_runtime.py"
    assert pose_runtime.is_file(), "process-local pose runtime is required"

    router = _source("api/routers/robot_poses.py")
    assert '@router.post("/robots/{robot_id}/pose"' in router
    assert '@router.post("/robot-poses/report"' not in router
    assert '@router.post("/movement/missions/{command_id}/pose"' not in router
    assert "transaction(" not in router
    assert "movement_client.robot_pose" not in router
    movement_router = _source("api/routers/movement.py")
    movement_callbacks = _source("services/movement_callbacks.py")
    assert "ingest_robot_status_pose" not in movement_router
    assert "pose_runtime.ingest" not in movement_callbacks


def test_mission_status_uses_only_canonical_robot_command_endpoint() -> None:
    movement = _source("services/movement.py")

    assert 'f"{origin}/robot-commands/{command_id}"' in movement
    assert 'f"{base}/commands/{command_id}"' not in movement
    assert "legacy /commands" not in movement


def test_dock_pairs_are_derived_from_waypoints_and_ordered_routes() -> None:
    map_models = _source("models/maps.py")
    app_sources = "\n".join(path.read_text(encoding="utf-8") for path in APP_ROOT.rglob("*.py"))

    assert "route_target_id" in map_models
    assert "approach_waypoint_ids" in map_models
    assert "dock_pairs" not in app_sources
    assert "dock_pair_promotion" not in app_sources
    assert "CREATE TABLE dock_pairs" not in (BACKEND_ROOT.parent / "database" / "schema_pg.sql").read_text(
        encoding="utf-8"
    )


def test_inout_composition_and_evidence_hazard_ownership_have_regressions() -> None:
    tests_root = BACKEND_ROOT / "tests"
    for name in (
        "test_evidence_inout_scenario_offline.py",
        "test_nohardware_main_evidence_gates.py",
        "test_lift_load_evidence.py",
        "test_person_hazard.py",
    ):
        assert (tests_root / name).is_file()


def test_db_forward_migrations_keep_only_required_legacy_orchestration_legs() -> None:
    migrations = BACKEND_ROOT.parent / "database" / "migrations"
    assert migrations.is_dir(), "forward PostgreSQL migrations are required"
    assert list(migrations.glob("*.sql")), "at least one forward migration is required"

    orchestration = _source("services/orchestration_state.py")
    assert 'orch.get("legs")' in orchestration
    assert 'orch.get("cursor")' in orchestration
    assert "dual_write" not in orchestration
    assert not (APP_ROOT / "db" / "repositories.py").exists()


def test_manual_navigation_override_mode_is_deleted() -> None:
    offenders = []
    for path in APP_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "manual_override_nav" in text or "LMS_MANUAL_OVERRIDE_NAV" in text:
            offenders.append(str(path.relative_to(BACKEND_ROOT)))
    assert offenders == [], f"manual navigation override remains active: {offenders}"


def test_existing_behavioral_regressions_anchor_safety_and_claims() -> None:
    required_tests = (
        "test_pg_db_safety_races.py",
        "test_nohardware_task_recovery_state_machine.py",
        "test_movement_callbacks.py",
        "test_movement_callback_auth.py",
        "test_person_hazard.py",
        "test_lift_load_evidence.py",
        "test_nohardware_main_evidence_gates.py",
        "test_evidence_inout_scenario_offline.py",
    )
    tests_root = BACKEND_ROOT / "tests"
    for name in required_tests:
        assert (tests_root / name).is_file()
