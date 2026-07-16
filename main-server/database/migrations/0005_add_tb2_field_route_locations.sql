-- Add only the missing business locations needed by the field-validated TB3_2 route.
-- Existing operator-managed rows are never overwritten; runtime binding checks reject drift.
INSERT INTO locations (id, type, status, x, y, yaw, marker_id, map_id) VALUES
    ('INBOUND_02',  'inbound',  'ACTIVE', 0.473, 0.27, -1.57, 1, 'robot2_map'),
    ('OUTBOUND_02', 'outbound', 'ACTIVE', 1.541, 0.27, -1.57, 6, 'robot2_map'),
    ('HOME_02',     'home',     'ACTIVE', 0.836, 0.953, 1.394, 4, 'robot2_map')
ON CONFLICT (id) DO NOTHING;
