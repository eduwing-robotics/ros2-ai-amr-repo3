# Nav runtime profile contract

This document is the current reference contract for Nav profile selection and evidence boundaries. The cross-service startup sequence belongs to the [physical E2E integrated runbook](../../../docs/operations/physical-e2e-checklist.md) and is not duplicated here.

Runtime profiles select operational intent; they do not duplicate robot
hardware facts. `config/robots.json` remains the canonical inventory for robot
IDs, domains, ports, capabilities, localization, and lift hardware.

## Selection

Selection precedence is `--profile`, then `SF_NAV_PROFILE`, then the manifest
default. The sole default is `tb1-live`. `tb2-live`, `all-live`, and
`tb1-synthetic-hil` require explicit selection.

The operator surface is `scripts/sf_nav.sh`:

```text
profiles | print-config | check | up | foreground | status | smoke | logs | down
```

`print-config` is deterministic and is the same resolved plan consumed by
launch, status, and compatibility wrappers. Profiles reference canonical robot
IDs and express component ownership (`external` or `managed-script`);
`service-managed` fails closed until an adapter exists.
Required heterogeneous components may declare `robot_ids`; for example,
`all-live` scopes bridge readiness to TB1 but requires physical lift readiness
from both lift-capable robots. TB1 needs the hardware-domain 2 to Nav-local
domain 42 bridge; TB2 runs directly in domain 5 and must not wait for a bridge
it does not use. Base readiness requires an expected controller node on
`/cmd_vel`, and physical lift readiness comes from the API's
subscriber-and-fresh-telemetry `lift.ready` gate, not from topic names alone.

Each selected robot also has one explicit `lift_backends` value:
`disabled`, `virtual`, or `physical`. TB1 and TB2 live select `physical`, while
TB1 synthetic HIL selects `virtual`. A
`physical` selection is rejected unless the same robot's canonical hardware
facts enable lift and advertise the lift capability. Docking and task code use
the same physical path for TB1 and TB2; robot ID, ROS domain, and camera source
remain profile-specific. The complete lift configuration, including topics,
levels, heights, timeouts, tolerance, and command scale, is identical for TB1
and TB2. The TB2-completed `robot2_map` level-1 E2E is the shared field
commissioning baseline: both robots use the same `0.055 m` field ArUco marker size and
`COMMISSIONED_ROBOT2_MAP_PHYSICAL_LEVEL1` dispatch policy. Metric camera
calibration remains robot-specific and is not copied between mounts;
`metric_docking.live_enabled` remains false for both. Shared commissioning does
not remove the per-run health, localization, and physical lift readiness gates.

Every live or synthetic-HIL Nav profile owns its selected robots' Nav2 helper as
`managed-script`. The supervisor starts Movement API endpoints first, then
Nav2 and observe-only localization, and reports the profile ready only when each
selected endpoint reports both `localized=true` and `nav2_ready=true`.

## Evidence boundary

`tb1-synthetic-hil` is test-only, has `execution_class=synthetic_hil` and
`evidence_class=nonphysical`, and requires `SF_NAV_ALLOW_SYNTHETIC_HIL=1`.
It keeps `SIMULATION_MODE=0`: Nav2, localization, alignment, base motion, and
safety admission remain real; only the lift backend is virtual.

Synthetic HIL never converts virtual execution into physical evidence. Health
and command evidence must retain `physical_lift_verified=false` and
`PHYSICAL_LIFT_NOT_VERIFIED`.
