# Navigation PC Guide

Run these commands from the navigation-server checkout on the Navigation PC.

## Preflight

```bash
scripts/run_nav_servers.sh --print-plan
ROS_SETUP=/opt/ros/jazzy/setup.bash scripts/run_nav_servers.sh --check
```

`--print-plan` shows the enabled robot, ROS domain, API port, and map. `--check`
validates the ROS installation and configuration without starting server
processes.

## Start navigation and the Movement API

Start Nav2 in one terminal for each robot that will navigate:

```bash
scripts/nav_ops.sh nav2-1
```

Use `scripts/nav_ops.sh nav2-2` for the second robot. Set its initial pose in
RViz before accepting a movement command.

Start the Movement API in a separate terminal:

```bash
scripts/nav_ops.sh start
scripts/nav_ops.sh status
```

`start` runs the API in the background. `status` reports each API endpoint and
the `/cmd_vel` readiness for the configured robot domains.

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

## Stop

```bash
scripts/nav_ops.sh stop
```

Stop foreground bridge and Nav2 processes with `Ctrl+C` after movement has been
stopped.
