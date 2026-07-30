# Mapping Tools

This folder holds map review, waypoint generation, zone-mask drawing, and waypoint recording utilities. These are support tools, not runtime entrypoints.

Examples:

```bash
python3 scripts/tools/mapping/generate_factory_grid_waypoints.py --dry-run
python3 scripts/tools/mapping/record_waypoint_pose.py <waypoint-id>
```

Run tools from the repository root unless a script says otherwise. Generated map and zone outputs continue to target the existing `map/` paths.
