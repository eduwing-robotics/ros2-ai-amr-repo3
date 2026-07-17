-- Test-only fixture. Idempotent INSERT ... ON CONFLICT DO NOTHING.
-- Apply ONLY via tests.pg_fixture.apply_demo_fixture() against a dedicated test DB.
-- WARNING: do not run against production databases.

INSERT INTO items (id, name) VALUES
    ('BOX-A', 'Box A'),
    ('BOX-B', 'Box B')
ON CONFLICT (id) DO NOTHING;

INSERT INTO maps (map_id, name, image_url) VALUES
    ('robot2_map', 'Robot 2 Map', '')
ON CONFLICT (map_id) DO NOTHING;

INSERT INTO locations (id, type, status, x, y, yaw, marker_id, map_id) VALUES
    ('INBOUND_01',  'inbound',  'ACTIVE', -0.085,  0.206, 1.571,  0, 'robot2_map'),
    ('INBOUND_02',  'inbound',  'ACTIVE',  0.234,  0.206, 1.571,  1, 'robot2_map'),
    ('OUTBOUND_01', 'outbound', 'ACTIVE',  1.131,  0.206, 1.571,  5, 'robot2_map'),
    ('OUTBOUND_02', 'outbound', 'ACTIVE',  1.450,  0.206, 1.571,  6, 'robot2_map'),
    ('STORAGE_S1',  'storage',  'ACTIVE',  0.239, -0.618, 0.000,  7, 'robot2_map'),
    ('STORAGE_S2',  'storage',  'ACTIVE',  0.253, -0.376, 0.000,  8, 'robot2_map'),
    ('STORAGE_S3',  'storage',  'ACTIVE',  1.039, -0.631, 3.142, 10, 'robot2_map'),
    ('STORAGE_S4',  'storage',  'ACTIVE',  1.025, -0.377, 3.142,  9, 'robot2_map'),
    ('HOME_01',     'home',     'ACTIVE',  0.527,  0.306, 1.571,  3, 'robot2_map'),
    ('HOME_02',     'home',     'ACTIVE',  0.816,  0.326, 1.571,  4, 'robot2_map'),
    ('CHARGE_01',   'charge',   'ACTIVE',  0.816,  0.326, 1.571,  4, 'robot2_map'),
    ('inbound_slot_1_approach',  'scan', 'ACTIVE', -0.085, 0.006, 1.571, 0, 'robot2_map'),
    ('inbound_slot_2_approach',  'scan', 'ACTIVE', 0.234, 0.006, 1.571, 1, 'robot2_map'),
    ('outbound_slot_1_approach', 'scan', 'ACTIVE', 1.131, 0.006, 1.571, 5, 'robot2_map'),
    ('outbound_slot_2_approach', 'scan', 'ACTIVE', 1.45, 0.006, 1.571, 6, 'robot2_map'),
    ('warehouse_a_approach',     'scan', 'ACTIVE', 0.019, -0.618, 0.0, 7, 'robot2_map'),
    ('warehouse_b_approach',     'scan', 'ACTIVE', 0.033, -0.376, 0.0, 8, 'robot2_map'),
    ('warehouse_c_approach',     'scan', 'ACTIVE', 1.239, -0.631, 3.142, 10, 'robot2_map'),
    ('warehouse_d_approach',     'scan', 'ACTIVE', 1.225, -0.377, 3.142, 9, 'robot2_map'),
    ('vehicle_1_approach',       'scan', 'ACTIVE', 0.527, 0.006, 1.571, 3, 'robot2_map'),
    ('vehicle_2_approach',       'scan', 'ACTIVE', 0.816, 0.006, 1.571, 4, 'robot2_map')
ON CONFLICT (id) DO NOTHING;

INSERT INTO inventory (item_id, location_id, floor, quantity) VALUES
    ('BOX-A', 'STORAGE_S1', 1, 5),
    ('BOX-B', 'STORAGE_S2', 1, 3)
ON CONFLICT (item_id, location_id, floor) DO NOTHING;

INSERT INTO cameras (source_id, label, robot_id, status) VALUES
    ('tb3_1_picam', 'tb3_1 Camera', 'tb3_1', 'not_connected'),
    ('tb3_2_picam', 'tb3_2 Camera', 'tb3_2', 'not_connected')
ON CONFLICT (source_id) DO NOTHING;
