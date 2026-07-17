-- Restore the Movement-owned storage mapping without changing the schema:
-- STORAGE_01=B, STORAGE_02=A, STORAGE_03=D, STORAGE_04=C.
WITH storage_mapping(target_id, source_id) AS (
    VALUES
        ('STORAGE_01', 'STORAGE_02'),
        ('STORAGE_02', 'STORAGE_01'),
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
