-- Realign business helper poses with the field-validated robot2_map scan normals.
-- The scan/approach poses remain the Nav2 goals. These helpers describe only the
-- short straight ArUco hand-off, and field dispatch remains blocked until TB1/TB2
-- physical commissioning accepts the measured result.
INSERT INTO locations (id, type, status, x, y, yaw, marker_id, map_id) VALUES
    ('INBOUND_01',  'inbound',  'ACTIVE', -0.085,  0.206, 1.571,  0, 'robot2_map'),
    ('INBOUND_02',  'inbound',  'ACTIVE',  0.234,  0.206, 1.571,  1, 'robot2_map'),
    ('HOME_01',     'home',     'ACTIVE',  0.527,  0.306, 1.571,  3, 'robot2_map'),
    ('HOME_02',     'home',     'ACTIVE',  0.816,  0.326, 1.571,  4, 'robot2_map'),
    ('CHARGE_01',   'charge',   'ACTIVE',  0.816,  0.326, 1.571,  4, 'robot2_map'),
    ('OUTBOUND_01', 'outbound', 'ACTIVE',  1.131,  0.206, 1.571,  5, 'robot2_map'),
    ('OUTBOUND_02', 'outbound', 'ACTIVE',  1.450,  0.206, 1.571,  6, 'robot2_map'),
    ('STORAGE_S1',  'storage',  'ACTIVE',  0.239, -0.618, 0.000,  7, 'robot2_map'),
    ('STORAGE_S2',  'storage',  'ACTIVE',  0.253, -0.376, 0.000,  8, 'robot2_map'),
    ('STORAGE_S3',  'storage',  'ACTIVE',  1.039, -0.631, 3.142, 10, 'robot2_map'),
    ('STORAGE_S4',  'storage',  'ACTIVE',  1.025, -0.377, 3.142,  9, 'robot2_map')
ON CONFLICT (id) DO UPDATE SET
    type = EXCLUDED.type,
    status = EXCLUDED.status,
    x = EXCLUDED.x,
    y = EXCLUDED.y,
    yaw = EXCLUDED.yaw,
    marker_id = EXCLUDED.marker_id,
    map_id = EXCLUDED.map_id;
