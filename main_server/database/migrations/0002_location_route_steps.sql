CREATE TABLE IF NOT EXISTS location_route_steps (
    target_location_id TEXT NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
    step_order INTEGER NOT NULL CHECK (step_order > 0),
    waypoint_id TEXT NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
    PRIMARY KEY (target_location_id, step_order),
    UNIQUE (target_location_id, waypoint_id)
);

CREATE INDEX IF NOT EXISTS idx_location_route_steps_waypoint
    ON location_route_steps(waypoint_id);
