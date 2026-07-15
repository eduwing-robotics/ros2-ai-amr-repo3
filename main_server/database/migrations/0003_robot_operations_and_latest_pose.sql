ALTER TABLE robots
    ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT TRUE;

CREATE TABLE IF NOT EXISTS robot_latest_poses (
    robot_id TEXT PRIMARY KEY REFERENCES robots(id) ON DELETE CASCADE,
    map_id TEXT NOT NULL,
    x DOUBLE PRECISION NOT NULL,
    y DOUBLE PRECISION NOT NULL,
    yaw DOUBLE PRECISION NOT NULL DEFAULT 0,
    linear_velocity DOUBLE PRECISION,
    angular_velocity DOUBLE PRECISION,
    source TEXT NOT NULL DEFAULT 'movement',
    command_id TEXT,
    reported_at TIMESTAMPTZ NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_robot_latest_poses_received_at
    ON robot_latest_poses(received_at DESC);
