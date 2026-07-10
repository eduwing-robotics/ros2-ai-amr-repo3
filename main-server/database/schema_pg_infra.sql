-- Standalone infra tables (not DBML business state) — PHASE_66.
-- No FK references from DBML tables. cameras.robot_id is a soft tag only.

CREATE TABLE IF NOT EXISTS cameras (
    source_id   TEXT PRIMARY KEY,
    label       TEXT NOT NULL,
    robot_id    TEXT,
    status      TEXT NOT NULL DEFAULT 'not_connected',
    stream_url  TEXT
);

CREATE TABLE IF NOT EXISTS maps (
    map_id      TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    image_url   TEXT NOT NULL DEFAULT '',
    resolution  DOUBLE PRECISION NOT NULL DEFAULT 0.05,
    origin_x    DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    origin_y    DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    origin_yaw  DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    width       INTEGER NOT NULL DEFAULT 0,
    height      INTEGER NOT NULL DEFAULT 0,
    frame_id    TEXT NOT NULL DEFAULT 'map'
);
