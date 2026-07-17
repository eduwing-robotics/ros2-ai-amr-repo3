-- Align Main storage numbering with Movement warehouse names:
-- STORAGE_01=A, STORAGE_02=B, STORAGE_03=C, STORAGE_04=D.
-- Preserve business IDs and inventory foreign keys while remapping physical poses.
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
