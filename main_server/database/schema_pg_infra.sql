-- Standalone infra tables (not DBML business state) — .
-- No FK references from DBML tables. cameras.robot_id is a soft tag only.

CREATE TABLE IF NOT EXISTS cameras (
    source_id   TEXT PRIMARY KEY,
    label       TEXT NOT NULL,
    robot_id    TEXT,
    status      TEXT NOT NULL DEFAULT 'not_connected',
    stream_url  TEXT
);

-- Single-map runtime: metadata is read from maps/*.yaml + *.pgm, never persisted.
DROP TABLE IF EXISTS maps;
