-- PostgreSQL MVP schema — ref/smartfactory-db-final.dbml (PHASE_59)
-- CHECK/default policies from PHASE_59 minimum supplement.

CREATE TABLE IF NOT EXISTS items (
    id   TEXT PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS robots (
    id            TEXT PRIMARY KEY,
    domain_id     INTEGER NOT NULL DEFAULT 1,
    status        TEXT NOT NULL DEFAULT 'IDLE',
    battery_level DOUBLE PRECISION,
    last_seen_at  TIMESTAMPTZ,
    CONSTRAINT robots_status_chk CHECK (
        status IN ('IDLE', 'ASSIGNED', 'RUNNING', 'CHARGING', 'ERROR', 'ESTOP', 'OFFLINE')
    )
);

CREATE TABLE IF NOT EXISTS locations (
    id        TEXT PRIMARY KEY,
    type      TEXT NOT NULL,
    status    TEXT NOT NULL DEFAULT 'ACTIVE',
    x         DOUBLE PRECISION,
    y         DOUBLE PRECISION,
    yaw       DOUBLE PRECISION DEFAULT 0,
    marker_id INTEGER,
    map_id    TEXT,
    CONSTRAINT locations_type_chk CHECK (
        type IN ('inbound', 'outbound', 'storage', 'home', 'charge', 'dock', 'transit', 'scan')
    ),
    CONSTRAINT locations_status_chk CHECK (status IN ('ACTIVE', 'DISABLED', 'BLOCKED'))
);

CREATE TABLE IF NOT EXISTS inventory (
    item_id     TEXT NOT NULL REFERENCES items(id),
    location_id TEXT NOT NULL REFERENCES locations(id),
    floor       INTEGER NOT NULL DEFAULT 1,
    quantity    INTEGER NOT NULL DEFAULT 0,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (item_id, location_id, floor),
    CONSTRAINT inventory_floor_chk CHECK (floor IN (1, 2)),
    CONSTRAINT inventory_quantity_chk CHECK (quantity >= 0)
);

CREATE INDEX IF NOT EXISTS idx_inventory_location ON inventory(location_id);
CREATE INDEX IF NOT EXISTS idx_inventory_location_floor ON inventory(location_id, floor);

CREATE TABLE IF NOT EXISTS tasks (
    id               BIGSERIAL PRIMARY KEY,
    task_type        TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'CREATED',
    priority         INTEGER NOT NULL DEFAULT 0,
    robot_id         TEXT REFERENCES robots(id),
    item_id          TEXT REFERENCES items(id),
    quantity         INTEGER NOT NULL DEFAULT 1,
    from_location_id TEXT REFERENCES locations(id),
    from_floor       INTEGER,
    to_location_id   TEXT REFERENCES locations(id),
    to_floor         INTEGER,
    error_reason     TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at       TIMESTAMPTZ,
    finished_at      TIMESTAMPTZ,
    CONSTRAINT tasks_type_chk CHECK (task_type IN ('INBOUND', 'OUTBOUND', 'MOVE', 'CHARGE')),
    CONSTRAINT tasks_status_chk CHECK (
        status IN ('CREATED', 'QUEUED', 'ASSIGNED', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED')
    ),
    CONSTRAINT tasks_quantity_chk CHECK (quantity > 0),
    CONSTRAINT tasks_from_floor_chk CHECK (from_floor IS NULL OR from_floor IN (1, 2)),
    CONSTRAINT tasks_to_floor_chk CHECK (to_floor IS NULL OR to_floor IN (1, 2))
);

CREATE INDEX IF NOT EXISTS idx_tasks_status_priority ON tasks(status, priority, created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_robot_status ON tasks(robot_id, status);
CREATE INDEX IF NOT EXISTS idx_tasks_item ON tasks(item_id);
CREATE INDEX IF NOT EXISTS idx_tasks_from_loc ON tasks(from_location_id, from_floor, status);
CREATE INDEX IF NOT EXISTS idx_tasks_to_loc ON tasks(to_location_id, to_floor, status);
CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at);
-- A robot may own at most one live task. The transactional claim locks both
-- rows; this partial unique index also protects the invariant from other SQL writers.
CREATE UNIQUE INDEX IF NOT EXISTS uq_tasks_active_robot
    ON tasks(robot_id)
    WHERE robot_id IS NOT NULL
      AND status IN ('CREATED', 'QUEUED', 'ASSIGNED', 'RUNNING');
-- An active INBOUND task is the durable reservation for its destination
-- pallet slot.  Completing, failing, or cancelling the task releases it.
CREATE UNIQUE INDEX IF NOT EXISTS uq_tasks_active_inbound_slot_floor
    ON tasks(to_location_id, to_floor)
    WHERE task_type = 'INBOUND'
      AND status IN ('CREATED', 'QUEUED', 'ASSIGNED', 'RUNNING');

CREATE TABLE IF NOT EXISTS commands (
    id                     BIGSERIAL PRIMARY KEY,
    task_type              TEXT NOT NULL,
    sequence_no            INTEGER NOT NULL,
    command_type           TEXT NOT NULL,
    target_system          TEXT NOT NULL,
    required_evidence_type TEXT NOT NULL,
    request_template_json  JSONB NOT NULL DEFAULT '{}'::jsonb,
    timeout_sec            INTEGER,
    is_active              BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (task_type, sequence_no)
);

CREATE INDEX IF NOT EXISTS idx_commands_task_type ON commands(task_type);
CREATE INDEX IF NOT EXISTS idx_commands_command_type ON commands(command_type);
CREATE INDEX IF NOT EXISTS idx_commands_target_system ON commands(target_system);
CREATE INDEX IF NOT EXISTS idx_commands_required_evidence ON commands(required_evidence_type);
CREATE INDEX IF NOT EXISTS idx_commands_active ON commands(is_active);

CREATE TABLE IF NOT EXISTS evidence_events (
    id          BIGSERIAL PRIMARY KEY,
    task_id     BIGINT,
    command_id  BIGINT REFERENCES commands(id),
    event_type  TEXT NOT NULL,
    source      TEXT NOT NULL,
    confidence  DOUBLE PRECISION,
    severity    TEXT NOT NULL DEFAULT 'INFO',
    trusted     BOOLEAN NOT NULL DEFAULT FALSE,
    image_url   TEXT,
    data_json   JSONB NOT NULL DEFAULT '{}'::jsonb,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_evidence_task ON evidence_events(task_id);
CREATE INDEX IF NOT EXISTS idx_evidence_command ON evidence_events(command_id);
CREATE INDEX IF NOT EXISTS idx_evidence_event_type ON evidence_events(event_type);
CREATE INDEX IF NOT EXISTS idx_evidence_severity ON evidence_events(severity);
CREATE INDEX IF NOT EXISTS idx_evidence_trusted ON evidence_events(trusted);
CREATE INDEX IF NOT EXISTS idx_evidence_observed ON evidence_events(observed_at);

CREATE TABLE IF NOT EXISTS safety_stops (
    id                   BIGSERIAL PRIMARY KEY,
    detected_evidence_id BIGINT NOT NULL REFERENCES evidence_events(id),
    status               TEXT NOT NULL DEFAULT 'OPEN',
    opened_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    hold_until           TIMESTAMPTZ,
    closed_at            TIMESTAMPTZ,
    CONSTRAINT safety_stops_status_chk CHECK (status IN ('OPEN', 'HOLDING', 'CLOSED'))
);

CREATE INDEX IF NOT EXISTS idx_safety_stops_status ON safety_stops(status);
CREATE INDEX IF NOT EXISTS idx_safety_stops_evidence ON safety_stops(detected_evidence_id);
CREATE INDEX IF NOT EXISTS idx_safety_stops_hold_until ON safety_stops(hold_until);
CREATE INDEX IF NOT EXISTS idx_safety_stops_opened ON safety_stops(opened_at);

CREATE TABLE IF NOT EXISTS item_change_logs (
    id               BIGSERIAL PRIMARY KEY,
    task_id          BIGINT,
    item_id          TEXT NOT NULL,
    location_id      TEXT,
    floor            INTEGER,
    event_type       TEXT NOT NULL,
    quantity_change  INTEGER NOT NULL,
    quantity_before  INTEGER,
    quantity_after   INTEGER,
    reason           TEXT,
    changed_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_item_change_task ON item_change_logs(task_id);
CREATE INDEX IF NOT EXISTS idx_item_change_item ON item_change_logs(item_id);
CREATE INDEX IF NOT EXISTS idx_item_change_location ON item_change_logs(location_id);
CREATE INDEX IF NOT EXISTS idx_item_change_floor ON item_change_logs(floor);
CREATE INDEX IF NOT EXISTS idx_item_change_event_type ON item_change_logs(event_type);
CREATE INDEX IF NOT EXISTS idx_item_change_changed ON item_change_logs(changed_at);

CREATE TABLE IF NOT EXISTS task_logs (
    id                    BIGSERIAL PRIMARY KEY,
    task_id               BIGINT NOT NULL,
    task_type             TEXT NOT NULL,
    result                TEXT NOT NULL,
    result_evidence_type  TEXT,
    started_at            TIMESTAMPTZ,
    finished_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    error_reason          TEXT,
    summary               TEXT,
    snapshot_json         JSONB NOT NULL DEFAULT '{}'::jsonb,
    logged_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT task_logs_result_chk CHECK (result IN ('COMPLETED', 'FAILED', 'CANCELLED'))
);

CREATE INDEX IF NOT EXISTS idx_task_logs_task ON task_logs(task_id);
CREATE INDEX IF NOT EXISTS idx_task_logs_task_type ON task_logs(task_type);
CREATE INDEX IF NOT EXISTS idx_task_logs_result ON task_logs(result);
CREATE INDEX IF NOT EXISTS idx_task_logs_result_evidence ON task_logs(result_evidence_type);
CREATE INDEX IF NOT EXISTS idx_task_logs_finished ON task_logs(finished_at);
CREATE INDEX IF NOT EXISTS idx_task_logs_logged ON task_logs(logged_at);

-- PHASE_66: widen locations.type CHECK on existing databases (idempotent).
ALTER TABLE locations DROP CONSTRAINT IF EXISTS locations_type_chk;
ALTER TABLE locations ADD CONSTRAINT locations_type_chk CHECK (
    type IN ('inbound', 'outbound', 'storage', 'home', 'charge', 'dock', 'transit', 'scan')
);

-- PHASE_74: map marker ownership per map.
ALTER TABLE locations ADD COLUMN IF NOT EXISTS map_id TEXT;
CREATE INDEX IF NOT EXISTS idx_locations_map_id ON locations(map_id);
