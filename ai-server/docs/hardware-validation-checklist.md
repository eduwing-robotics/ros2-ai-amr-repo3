# Hardware Validation Checklist

Record these checks separately from no-hardware automated tests.

- [ ] Global camera stream visible at the low-load URL.
- [ ] Overlay for `global_cam_01/full` updates and is not stale.
- [ ] ZoneROI alignment matches the lab pickup/dropoff surface.
- [ ] ArUco item marker IDs `20..49` are detected in the configured ZoneROI.
- [ ] Lift/load evidence produces expected controlled-case statuses: `PASS`, `FAIL`, `UNCERTAIN`, `NO_DECISION`.
- [ ] PiCam person-hazard advisory updates for connected TurtleBot sources.
- [ ] Runtime restart/control API remains disabled or protected by the approved token/allow-list.
