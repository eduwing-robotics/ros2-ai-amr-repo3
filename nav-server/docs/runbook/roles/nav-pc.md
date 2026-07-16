# Navigation PC Guide

Run these commands from the navigation-server checkout on the Navigation PC.

## Live process session

Keep field processes observable in the shared tmux session. Use one named
window per process; do not replace a live window with an untracked background
process.

```bash
tmux new-session -Ad -s ros2-amr-hardware-test
tmux new-window -t ros2-amr-hardware-test -n nav2-tb3-1
tmux new-window -t ros2-amr-hardware-test -n movement-api
tmux attach -t ros2-amr-hardware-test
```

Run the commands below in their named windows. Use `Ctrl+C` in the owning
window to stop a process, and inspect remaining windows with
`tmux list-windows -t ros2-amr-hardware-test`.

## Preflight

```bash
scripts/run_nav_servers.sh --print-plan
ROS_SETUP=/opt/ros/jazzy/setup.bash scripts/run_nav_servers.sh --check
```

`--print-plan` shows the enabled robot, ROS domain, API port, and map. `--check`
validates the ROS installation and configuration without starting server
processes.

## Start navigation and the Movement API

Start the Movement API first so the Nav2 helper can submit its signed
localization request:

```bash
scripts/nav_ops.sh start
scripts/nav_ops.sh status
```

`start` runs the API in the background. `status` reports each API endpoint and
the `/cmd_vel` readiness for the configured robot domains.

Confirm the trusted deployment placed the shared repository-level
`.secrets/service-hmac.env` bundle, then use `scripts/sf_nav.sh`. The profile
launcher loads `NAV_MAIN_HMAC_SECRET` internally; do not copy or export the
secret in the operator shell. Start Nav2 in one terminal for each robot that
will navigate:

```bash
scripts/nav_ops.sh nav2-1
```

The helper waits for `/scan` and the `odom -> base_footprint` TF within a
bounded readiness window before launching Nav2; either missing input fails the
startup closed. The normal path signs and sends the `observe_only` request
below, verifies robot name/ID, ROS domain, active map, strategy, and
`motion_started=false`, then polls until `LOCALIZED`. Only then does it observe
`/lifecycle_manager_navigation/is_active` in the foreground and report
`navigation-ready`. It never calls `manage_nodes` to activate or retry
lifecycle transitions. Any bounded readiness, localization, identity, or
lifecycle timeout fails startup closed.

Use `scripts/nav_ops.sh nav2-2` for the second robot. The automatic request is:

```text
POST /movement-api/v1/robots/tb3_1/localization/global-search
{"strategy":"observe_only","allow_motion":false}
```

`observe_only` redistributes AMCL particles, repeatedly calls
`/request_nomotion_update` within its bounded timeout, and publishes no
`/cmd_vel` (zero commanded motion). Localization is accepted only after
repeated, newer AMCL samples pass scan/TF freshness, covariance, pose/yaw
jitter, consecutive-sample, and minimum-stable-duration limits. An accepted
global-search request only starts this evaluation; it does not mean the robot
is localized. Poll until convergence:

When the initial pose is unknown, the robot1 profile runs map-wide scan
matching. It publishes an AMCL seed only when the same candidate appears in
three of five fresh scans, then proceeds through the normal convergence gate.
Direction alignment only breaks near-equal distance fits. Short returns from
people or movable objects do not count as wall evidence.

```bash
watch -n 1 'curl -fsS http://localhost:8001/movement-api/v1/robots/tb3_1/localization | python3 -m json.tool'
```

Proceed only when the response reports `localized=true`, `state=LOCALIZED`,
and `reason=converged`. If observation does not converge, fail closed. Hand off
to `bounded_linear_wiggle` only through a new explicit request with
`allow_motion=true`, and only after both front and rear clearances pass the
robot-profile minimums. Its speed, step/total distance, scan freshness, and
directional clearance remain continuously bounded; stale scan or lost
clearance stops the search. Rotation is not a supported search strategy.
Do not repeatedly submit a new search while a bounded search is stopping. The
API returns `previous_search_still_stopping`, keeps the cancellation event set,
and commands a stop instead of allowing two localization-motion workers to
publish concurrently. Repeated health reads reuse the last accepted AMCL sample
without counting it twice or revoking an already converged state; negative or
non-finite freshness/covariance values remain fail-closed.

For a field check, keep RViz in the owning Nav2 tmux window. Confirm that outer
walls and fixed interior structures overlap before enabling movement. Stop
Nav2/RViz after evidence capture when the robot is on limited battery.

An explicit pose is manual recovery only. Use it only when the operator knows
the confirmed-map pose, and provide all three values together:

```bash
NAV2_MANUAL_INITIAL_POSE=1 \
NAV2_INITIAL_X=<x> NAV2_INITIAL_Y=<y> NAV2_INITIAL_YAW=<yaw> \
scripts/nav_ops.sh nav2-1
```

Manual recovery still waits for the same identity-bound `LOCALIZED` gate before
navigation readiness; a partial pose is rejected before launch.

## Domain bridges

Start bridges only when center-domain monitoring or control is required. This
process remains in the foreground:

```bash
scripts/nav_ops.sh bridges
```

## Readiness checks

Run the check for every robot that will receive a command:

```bash
scripts/nav_ops.sh check1
```

Use `scripts/nav_ops.sh check2` for the second robot. Confirm the API is
reachable, `/scan` has a publisher, and `/cmd_vel` has a subscriber.
Before real movement, also confirm localization reports `localized=true` and
`reason=converged`; every other localization state remains command-blocking.

## Stop

```bash
scripts/nav_ops.sh stop
```

Stop foreground bridge and Nav2 processes with `Ctrl+C` after movement has been
stopped. Stop the Movement API in its tmux window the same way; keep the
`ros2-amr-hardware-test` session until logs and evidence have been collected.
