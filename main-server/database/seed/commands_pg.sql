-- Static command definitions per task_type (PHASE_63-A). Idempotent.

INSERT INTO commands (task_type, sequence_no, command_type, target_system, required_evidence_type, request_template_json, timeout_sec, is_active) VALUES
    ('MOVE',     1, 'move_to_point',  'movement', 'ARRIVED', '{"kind":"move_to_point"}'::jsonb, 120, true),
    ('INBOUND',  1, 'move_to_point',  'movement', 'ARRIVED', '{"kind":"move_to_point","target":"inbound_scan"}'::jsonb, 120, true),
    ('INBOUND',  2, 'dock_transfer',  'movement', 'DONE',    '{"kind":"dock_transfer","mode":"inbound_load"}'::jsonb, 180, true),
    ('INBOUND',  3, 'verify_post_pick_up', 'vision', 'ITEM_PICKED', '{"operation":"POST_PICK_UP"}'::jsonb, 30, true),
    ('INBOUND',  4, 'move_to_point',  'movement', 'ARRIVED', '{"kind":"move_to_point","target":"storage_scan","human_hazard_monitor":true}'::jsonb, 120, true),
    ('INBOUND',  5, 'verify_pre_drop_off', 'vision', 'ITEM_PLACEMENT_READY', '{"operation":"PRE_DROP_OFF"}'::jsonb, 30, true),
    ('INBOUND',  6, 'dock_transfer',  'movement', 'DONE',    '{"kind":"dock_transfer","mode":"storage_unload"}'::jsonb, 180, true),
    ('INBOUND',  7, 'move_to_point',  'movement', 'ARRIVED', '{"kind":"move_to_point","target":"home"}'::jsonb, 120, true),
    ('OUTBOUND', 1, 'move_to_point',  'movement', 'ARRIVED', '{"kind":"move_to_point","target":"storage_scan"}'::jsonb, 120, true),
    ('OUTBOUND', 2, 'dock_transfer',  'movement', 'DONE',    '{"kind":"dock_transfer","mode":"storage_load"}'::jsonb, 180, true),
    ('OUTBOUND', 3, 'verify_post_pick_up', 'vision', 'ITEM_PICKED', '{"operation":"POST_PICK_UP"}'::jsonb, 30, true),
    ('OUTBOUND', 4, 'move_to_point',  'movement', 'ARRIVED', '{"kind":"move_to_point","target":"outbound_scan","human_hazard_monitor":true}'::jsonb, 120, true),
    ('OUTBOUND', 5, 'verify_pre_drop_off', 'vision', 'ITEM_PLACEMENT_READY', '{"operation":"PRE_DROP_OFF"}'::jsonb, 30, true),
    ('OUTBOUND', 6, 'dock_transfer',  'movement', 'DONE',    '{"kind":"dock_transfer","mode":"outbound_unload"}'::jsonb, 180, true),
    ('OUTBOUND', 7, 'move_to_point',  'movement', 'ARRIVED', '{"kind":"move_to_point","target":"home"}'::jsonb, 120, true),
    ('CHARGE',   1, 'move_to_point',  'movement', 'ARRIVED', '{"kind":"move_to_point","target":"charge"}'::jsonb, 120, true),
    ('CHARGE',   2, 'dock_transfer',  'movement', 'DONE',    '{"kind":"dock_transfer","mode":"charge"}'::jsonb, 180, true),
    ('LOCALIZATION_RECOVERY', 1, 'restart_localization', 'movement', 'LOCALIZATION_RESTART_ACCEPTED', '{"strategy":"observe_only","allow_motion":false}'::jsonb, 30, true)
ON CONFLICT (task_type, sequence_no) DO UPDATE SET
    command_type = EXCLUDED.command_type,
    target_system = EXCLUDED.target_system,
    required_evidence_type = EXCLUDED.required_evidence_type,
    request_template_json = EXCLUDED.request_template_json,
    timeout_sec = EXCLUDED.timeout_sec,
    is_active = EXCLUDED.is_active;
