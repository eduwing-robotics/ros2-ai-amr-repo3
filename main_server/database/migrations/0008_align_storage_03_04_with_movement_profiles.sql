-- Align STORAGE_03/04 business poses with the Movement-owned profiles without changing the schema:
-- STORAGE_01=B and STORAGE_02=A remain unchanged; STORAGE_03=C, STORAGE_04=D.
-- Runner transaction swaps only x/y/yaw/marker_id; inventory rows and foreign keys are unchanged.
WITH storage_mapping(target_id, source_id) AS (
    VALUES
        ('STORAGE_03', 'STORAGE_04'),
        ('STORAGE_04', 'STORAGE_03')
), source_snapshot AS (
    SELECT mapping.target_id, source.x, source.y, source.yaw, source.marker_id
    FROM storage_mapping AS mapping
    JOIN locations AS source ON source.id = mapping.source_id
)
UPDATE locations AS target
SET x = source_snapshot.x,
    y = source_snapshot.y,
    yaw = source_snapshot.yaw,
    marker_id = source_snapshot.marker_id
FROM source_snapshot
WHERE target.id = source_snapshot.target_id;
