-- Static command definitions per task_type. Idempotent.

INSERT INTO commands (task_type, sequence_no, command_type, target_system, required_evidence_type, request_template_json, timeout_sec, is_active) VALUES
    ('MOVE',     1, 'move_to_point',  'movement', 'ARRIVED', '{"kind":"move_to_point"}'::jsonb, 120, true),
    ('INBOUND',  1, 'move_to_point',  'movement', 'ARRIVED', '{"kind":"move_to_point","target":"inbound_precision","transfer_action":"load"}'::jsonb, 180, true),
    ('INBOUND',  2, 'move_to_point',  'movement', 'ARRIVED', '{"kind":"move_to_point","target":"storage_precision","transfer_action":"unload"}'::jsonb, 180, true),
    ('INBOUND',  3, 'move_to_point',  'movement', 'ARRIVED', '{"kind":"move_to_point","target":"home"}'::jsonb, 120, true),
    ('INBOUND',  4, 'dock_transfer',  'movement', 'DONE',    '{"kind":"dock_transfer","mode":"legacy_storage_unload"}'::jsonb, 180, false),
    ('INBOUND',  5, 'move_to_point',  'movement', 'ARRIVED', '{"kind":"move_to_point","target":"legacy_home"}'::jsonb, 120, false),
    ('OUTBOUND', 1, 'move_to_point',  'movement', 'ARRIVED', '{"kind":"move_to_point","target":"storage_precision","transfer_action":"load"}'::jsonb, 180, true),
    ('OUTBOUND', 2, 'move_to_point',  'movement', 'ARRIVED', '{"kind":"move_to_point","target":"outbound_precision","transfer_action":"unload"}'::jsonb, 180, true),
    ('OUTBOUND', 3, 'move_to_point',  'movement', 'ARRIVED', '{"kind":"move_to_point","target":"home"}'::jsonb, 120, true),
    ('OUTBOUND', 4, 'dock_transfer',  'movement', 'DONE',    '{"kind":"dock_transfer","mode":"legacy_outbound_unload"}'::jsonb, 180, false),
    ('OUTBOUND', 5, 'move_to_point',  'movement', 'ARRIVED', '{"kind":"move_to_point","target":"legacy_home"}'::jsonb, 120, false),
    ('CHARGE',   1, 'move_to_point',  'movement', 'ARRIVED', '{"kind":"move_to_point","target":"charge"}'::jsonb, 120, true),
    ('CHARGE',   2, 'dock_transfer',  'movement', 'DONE',    '{"kind":"dock_transfer","mode":"charge"}'::jsonb, 180, true)
ON CONFLICT (task_type, sequence_no) DO UPDATE SET
    command_type = EXCLUDED.command_type,
    target_system = EXCLUDED.target_system,
    required_evidence_type = EXCLUDED.required_evidence_type,
    request_template_json = EXCLUDED.request_template_json,
    timeout_sec = EXCLUDED.timeout_sec,
    is_active = EXCLUDED.is_active;
