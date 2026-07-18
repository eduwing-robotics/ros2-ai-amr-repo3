-- 기능 책임: PostgreSQL 통합 테스트가 공유하는 최소 업무 fixture를 제공한다.
-- Test-only fixture. Idempotent INSERT ... ON CONFLICT DO NOTHING.
-- Apply ONLY via tests.support.postgres.apply_demo_fixture() against a dedicated test DB.
-- WARNING: do not run against production databases.

INSERT INTO items (id, name) VALUES
    ('BOX-A', 'Box A'),
    ('BOX-B', 'Box B')
ON CONFLICT (id) DO NOTHING;

INSERT INTO locations (id, type, status, x, y, yaw, marker_id) VALUES
    ('INBOUND_01',  'inbound',  'ACTIVE', 2.0, 0.0, 0, 101),
    ('OUTBOUND_01', 'outbound', 'ACTIVE', 4.0, 0.0, 0, 102),
    ('STORAGE_S1',  'storage',  'ACTIVE', 1.0, 1.0, 0, 201),
    ('STORAGE_S2',  'storage',  'ACTIVE', 1.0, 2.0, 0, 202),
    ('STORAGE_S3',  'storage',  'ACTIVE', 1.0, 3.0, 0, 203),
    ('STORAGE_S4',  'storage',  'ACTIVE', 1.0, 4.0, 0, 204),
    ('HOME_01',     'home',     'ACTIVE', 0.0, 0.0, 0, 301),
    ('CHARGE_01',   'charge',   'ACTIVE', -1.0, 0.0, 0, NULL),
    ('scan_INBOUND_01',  'scan', 'ACTIVE', 1.8, 0.0, 0, 101),
    ('scan_OUTBOUND_01', 'scan', 'ACTIVE', 3.8, 0.0, 0, 102),
    ('scan_STORAGE_S1',  'scan', 'ACTIVE', 0.8, 1.0, 0, 201),
    ('scan_STORAGE_S2',  'scan', 'ACTIVE', 0.8, 2.0, 0, 202),
    ('scan_STORAGE_S3',  'scan', 'ACTIVE', 0.8, 3.0, 0, 203),
    ('scan_STORAGE_S4',  'scan', 'ACTIVE', 0.8, 4.0, 0, 204),
    ('scan_HOME_01',     'scan', 'ACTIVE', -0.3, 0.0, 0, 301)
ON CONFLICT (id) DO NOTHING;

INSERT INTO inventory (item_id, location_id, floor, quantity) VALUES
    ('BOX-A', 'STORAGE_S1', 1, 5),
    ('BOX-B', 'STORAGE_S2', 1, 3)
ON CONFLICT (item_id, location_id, floor) DO NOTHING;

INSERT INTO cameras (source_id, label, robot_id, status) VALUES
    ('tb3_1_picam', 'tb3_1 Camera', 'tb3_1', 'not_connected'),
    ('tb3_2_picam', 'tb3_2 Camera', 'tb3_2', 'not_connected')
ON CONFLICT (source_id) DO NOTHING;
