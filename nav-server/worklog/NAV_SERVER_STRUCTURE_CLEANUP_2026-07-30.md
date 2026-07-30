# Nav Server Structure Cleanup - 2026-07-30

## Scope

This cleanup applies to `ros2-ai-amr-repo3` branch `e2d-docing`, directory
`nav-server`. `ros2-ai-amr-repo4/slam_navigation` was used only as a structure and
documentation reference. No repo4 runtime behavior, launch flow, or navigation
algorithm was transplanted.

## Result

The primary operator surface is now explicit:

| Item | Disposition | Reason |
| --- | --- | --- |
| `scripts/sf_nav.sh` | Keep as canonical operator entrypoint | Current docs and tests identify it as the standard start path |
| `scripts/start_nav_servers.sh` | Keep as compatibility wrapper | Existing operators may still use it; it delegates to canonical startup |
| `scripts/nav_ops.sh` | Keep as convenience wrapper | Groups common operator actions without owning runtime behavior |
| `scripts/start_all_tb3_2.sh` | Keep as field helper | Used for tb3_2 commissioning workflows |
| `scripts/agv_grid_planner.py` | Move to `experiments/agv_graph/` | Experimental, not Movement API dispatch |
| `scripts/agv_graph_builder.py` | Move to `experiments/agv_graph/` | Experimental graph helper |
| `scripts/agv_orthogonal_follower.py` | Move to `experiments/agv_graph/` | Experimental follower |
| `scripts/validate_agv_graph.py` | Move to `experiments/agv_graph/` | Experimental validator |
| `launch/agv_follower.launch.py` | Move to `experiments/agv_graph/launch/` | Launches only the experiment follower |
| `config/agv_follower.yaml` | Move to `experiments/agv_graph/config/` | Experiment parameters |
| `map/agv_waypoint_graph.yaml` | Move to `experiments/agv_graph/map/` | Experiment graph data |
| `config/rviz/agv_map_debug.rviz` | Keep in `config/rviz/` | Still used by `scripts/run_nav2_with_initial_pose.sh` |

## Structure Metrics

| Metric | Before | After | Note |
| --- | ---: | ---: | --- |
| Source files under `nav-server` | 246 | 251 | Increase comes from docs, tests, and package markers, not production runtime breadth |
| Files under `scripts/` | 94 | 91 | Four AGV scripts moved out, one scripts guide added |
| Top-level shell scripts | 48 | 48 | Shell compatibility surface was classified, not removed |
| AGV bundle files at primary runtime paths | 7 | 0 | Experimental AGV code/config/launch/map files no longer sit in `scripts/`, `launch/`, `config/`, or `map/` primary runtime locations |
| Files in `experiments/agv_graph/` | 0 | 9 | Seven moved artifacts plus README and package marker |

## Evidence

- Added a repository layout contract test for the canonical entrypoint, wrapper roles,
  documentation taxonomy, and AGV experiment boundary.
- Baseline snapshots found 99 operator-entrypoint matches and 19 AGV matches. These
  were discovery inventories, not reduction targets, because valid references remain
  in tests, docs, the experiment bundle, and the active RViz debug file.
- Focused relocation suite passed: `63 passed in 26.79s`.
- `git diff --check` reported no whitespace errors.
- `python3 experiments/agv_graph/validate_agv_graph.py --help` works.
- `source /opt/ros/jazzy/setup.bash && ros2 launch ./experiments/agv_graph/launch/agv_follower.launch.py --show-args`
  resolves the launch file and reports the `params_file` argument.

## Known Limits

- Physical robot validation was not performed.
- Full ROS 2 runtime launch without `--show-args` was not performed.
- The AGV graph validator currently runs but reports `graph_errors=36` against
  `map/robot2_map.yaml`, so the AGV bundle remains non-production experiment
  evidence only.
