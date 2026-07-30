# Nav Server Tests

Tests are grouped by one-level taxonomy directories:

- `unit/` - pure helpers, geometry, map state, camera, ArUco, lift, and route helpers.
- `contracts/` - repository layout, API/config/security/safety contracts, and no-hardware envelopes.
- `integration/` - cross-service navigation, docking, localization, scan-map, vision, and command flows.
- `runtime/` - operator scripts, deployment paths, ROS domain/runtime profiles, RViz, and Gazebo contracts.
- `experiments/` - AGV graph/planner experiment coverage.

Shared pytest setup remains in `conftest.py`; shared path helpers live in `support.py`.
