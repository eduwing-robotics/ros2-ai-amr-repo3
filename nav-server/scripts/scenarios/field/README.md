# Field Scenario Scripts

This folder holds one-off and repeatable field validation runners for tb3_2 slot, vision, Lift, and drive scenarios. Run them from the repository root so operator commands, logs, and environment paths stay consistent.

Examples:

```bash
bash scripts/scenarios/field/run_drive_insert_scenario.sh
SLOT=a bash scripts/scenarios/field/run_center_slot_insert_test.sh
```

Keep canonical runtime entrypoints such as `scripts/sf_nav.sh`, `scripts/start_nav_servers.sh`, `scripts/nav_ops.sh`, and `scripts/start_all_tb3_2.sh` at the top level.
