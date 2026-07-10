-- No-hardware DB seam fixture. Idempotent and safe for disposable test DBs only.

INSERT INTO items (id, name) VALUES
    ('NOHW_BOX_A', 'No-hardware Box A')
ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name;

INSERT INTO robots (id, domain_id, status, battery_level) VALUES
    ('tb3_1', 1, 'IDLE', 100)
ON CONFLICT (id) DO UPDATE SET
    domain_id = EXCLUDED.domain_id,
    status = EXCLUDED.status,
    battery_level = EXCLUDED.battery_level,
    last_seen_at = now();

INSERT INTO locations (id, type, status, x, y, yaw, marker_id, map_id) VALUES
    ('NOHW_INBOUND_01', 'inbound', 'ACTIVE', 2.0, 0.0, 0.0, 1101, 'robot1_map'),
    ('NOHW_STORAGE_01', 'storage', 'ACTIVE', 1.0, 1.0, 0.0, 1201, 'robot1_map'),
    ('scan_NOHW_INBOUND_01', 'scan', 'ACTIVE', 1.8, 0.0, 0.0, 1101, 'robot1_map'),
    ('scan_NOHW_STORAGE_01', 'scan', 'ACTIVE', 0.8, 1.0, 0.0, 1201, 'robot1_map'),
    ('NOHW_HOME_01', 'home', 'ACTIVE', 0.0, 0.0, 0.0, NULL, 'robot1_map')
ON CONFLICT (id) DO UPDATE SET
    type = EXCLUDED.type,
    status = EXCLUDED.status,
    x = EXCLUDED.x,
    y = EXCLUDED.y,
    yaw = EXCLUDED.yaw,
    marker_id = EXCLUDED.marker_id,
    map_id = EXCLUDED.map_id;
