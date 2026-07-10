-- Test-only fixture. Idempotent INSERT ... ON CONFLICT DO NOTHING.
-- Apply ONLY via tests.pg_fixture.apply_demo_fixture() against a dedicated test DB.
-- WARNING: do not run against production databases.

INSERT INTO items (id, name) VALUES
    ('BOX-A', 'Box A'),
    ('BOX-B', 'Box B')
ON CONFLICT (id) DO NOTHING;

INSERT INTO maps (map_id, name, image_url) VALUES
    ('robot1_map', 'Robot 1 Map', '')
ON CONFLICT (map_id) DO NOTHING;

INSERT INTO locations (id, type, status, x, y, yaw, marker_id, map_id) VALUES
    ('INBOUND_01',  'inbound',  'ACTIVE', -0.04, 1.082, 1.655, 0, 'robot1_map'),
    ('OUTBOUND_01', 'outbound', 'ACTIVE', 1.327, 0.27, -1.57, 5, 'robot1_map'),
    ('STORAGE_S1',  'storage',  'ACTIVE', 0.327, 0.573, -0.155, 7, 'robot1_map'),
    ('STORAGE_S2',  'storage',  'ACTIVE', 0.74, 0.992, 0.0, 8, 'robot1_map'),
    ('STORAGE_S3',  'storage',  'ACTIVE', 1.06, 1.236, 3.14, 10, 'robot1_map'),
    ('STORAGE_S4',  'storage',  'ACTIVE', 1.06, 0.992, 3.14, 9, 'robot1_map'),
    ('HOME_01',     'home',     'ACTIVE', 0.765, 0.33, -1.57, 3, 'robot1_map'),
    ('CHARGE_01',   'charge',   'ACTIVE', 0.836, 0.953, 1.394, 4, 'robot1_map'),
    ('scan_INBOUND_01',  'scan', 'ACTIVE', -0.085, 0.006, 1.571, 0, 'robot1_map'),
    ('scan_OUTBOUND_01', 'scan', 'ACTIVE', 1.131, 0.006, 1.571, 5, 'robot1_map'),
    ('scan_STORAGE_S1',  'scan', 'ACTIVE', 0.026, -0.025, 0.0, 7, 'robot1_map'),
    ('scan_STORAGE_S2',  'scan', 'ACTIVE', 0.033, -0.376, 0.0, 8, 'robot1_map'),
    ('scan_STORAGE_S3',  'scan', 'ACTIVE', 1.226, -0.025, 3.142, 10, 'robot1_map'),
    ('scan_STORAGE_S4',  'scan', 'ACTIVE', 1.225, -0.377, 3.142, 9, 'robot1_map'),
    ('scan_HOME_01',     'scan', 'ACTIVE', 0.527, 0.006, 1.571, 3, 'robot1_map'),
    ('scan_CHARGE_01',   'scan', 'ACTIVE', 0.816, 0.006, 1.571, 4, 'robot1_map')
ON CONFLICT (id) DO NOTHING;

INSERT INTO inventory (item_id, location_id, floor, quantity) VALUES
    ('BOX-A', 'STORAGE_S1', 1, 5),
    ('BOX-B', 'STORAGE_S2', 1, 3)
ON CONFLICT (item_id, location_id, floor) DO NOTHING;

INSERT INTO cameras (source_id, label, robot_id, status) VALUES
    ('tb3_1_picam', 'tb3_1 Camera', 'tb3_1', 'not_connected'),
    ('tb3_2_picam', 'tb3_2 Camera', 'tb3_2', 'not_connected')
ON CONFLICT (source_id) DO NOTHING;
