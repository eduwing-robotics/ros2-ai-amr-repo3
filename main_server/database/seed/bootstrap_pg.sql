-- Operational bootstrap seed. Idempotent INSERT ... ON CONFLICT DO NOTHING.
-- Applied on every init_db() — mutable demo data is NOT included here.
-- Test fixtures (items/locations/inventory): backend/tests/support/demo_seed_pg.sql (tests only).

INSERT INTO robots (id, domain_id, status, battery_level) VALUES
    ('tb3_1', 1, 'IDLE', 100),
    ('tb3_2', 1, 'IDLE', 100)
ON CONFLICT (id) DO NOTHING;

-- Vision allowlist / operate tile registry. Required for fresh DB UI.
INSERT INTO cameras (source_id, label, robot_id, status) VALUES
    ('global_cam_01', 'Global Camera 01', NULL, 'not_connected')
ON CONFLICT (source_id) DO NOTHING;
