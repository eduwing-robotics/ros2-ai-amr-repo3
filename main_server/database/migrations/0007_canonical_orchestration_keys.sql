-- Normalize persisted orchestration JSON to the canonical steps/step_index keys.
UPDATE evidence_events
SET data_json = (data_json - 'legs' - 'cursor')
    || jsonb_build_object(
        'steps', COALESCE(data_json -> 'steps', data_json -> 'legs', '[]'::jsonb),
        'step_index', COALESCE(data_json -> 'step_index', data_json -> 'cursor', '0'::jsonb)
    )
WHERE event_type = 'ORCHESTRATION_STATE'
  AND (data_json ? 'legs' OR data_json ? 'cursor');
