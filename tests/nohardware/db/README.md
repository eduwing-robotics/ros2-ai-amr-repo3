# No-hardware DB seam check

`tests/nohardware/db/check_db_persistence.py` verifies the Main Server PostgreSQL persistence/state-machine seam only. It creates minimal DB fixtures (`task`, `robot`, `locations`) and checks real `app.db.repo_bridge` repositories plus `evidence_runtime.save_orchestration` / `attach_orchestration`.

Covered here:
- RUNNING orchestration save/read/attach
- untrusted AI advisory evidence row
- trusted Main `LIFT_LOAD_GATE_DECISION` evidence row
- `AWAITING_OPERATOR` orchestration save/read/attach
- trusted CRITICAL safety evidence opening a `safety_stops` row, then close
- task completion (`DONE`) and robot return to `IDLE`
- two independent PostgreSQL connections racing the same terminal callback:
  exactly one callback may advance, create terminal evidence, and claim the
  next dispatch
- restart recovery from a durably `dispatching` next step, including stable
  deterministic command identity and one `DISPATCHED` evidence event

Not covered here: Movement/Vision HTTP/TCP behavior. Those no-hardware contracts are intentionally handled by the separate TCP runner/tests (`scripts/test-nohardware-tcp.sh`, `tests/nohardware/check_main_movement_tcp.py`, `tests/nohardware/check_main_vision_tcp.py`).
