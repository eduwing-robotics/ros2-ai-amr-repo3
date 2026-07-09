# ros2-ai-amr-repo3

Eduwing ROS2 AMR monorepo (repo3). Each top-level folder is an independently deployable component.

## Layout

| Folder | Description |
| --- | --- |
| `Nav-server/` | SLAM map, zones, Nav2 Movement API (`nav_app/`), scripts, configs, tests |

Other components (simulator, main server, etc.) will be added as sibling folders on separate branches.

## Nav-server quick start

```bash
cd Nav-server
python3 -m pytest tests/ -q
scripts/start_nav_servers.sh status
```

See `Nav-server/README.md` for the full operator guide.

## Sync from local workspace

On the Nav PC (`slam_nav_ws`):

```bash
bash scripts/sync_nav_server_from_workspace.sh
```
