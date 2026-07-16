-- Main owns the item-to-ArUco catalog used by physical lift/load evidence.
-- Existing operator/demo rows remain untouched; the six field item rows are
-- additive and can be renamed later without changing their stable item code.
ALTER TABLE items
    ADD COLUMN IF NOT EXISTS unit TEXT NOT NULL DEFAULT 'EA';

ALTER TABLE items
    ADD COLUMN IF NOT EXISTS aruco_marker_id INTEGER;

DO $$
BEGIN
    ALTER TABLE items
        ADD CONSTRAINT items_aruco_marker_id_chk CHECK (
            aruco_marker_id IS NULL OR aruco_marker_id BETWEEN 20 AND 49
        );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END
$$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_items_aruco_marker_id
    ON items(aruco_marker_id)
    WHERE aruco_marker_id IS NOT NULL;

INSERT INTO items (id, name, unit, aruco_marker_id) VALUES
    ('PART-BEARING',    '베어링',      'EA', 20),
    ('PART-GEAR',       '기어',        'EA', 22),
    ('PART-MOTOR',      '구동 모터',   'EA', 23),
    ('PART-SENSOR',     '센서 모듈',   'EA', 24),
    ('PART-BRACKET',    '장착 브래킷', 'EA', 27),
    ('PART-CONTROLLER', '제어 모듈',   'EA', 29)
ON CONFLICT (id) DO UPDATE SET
    aruco_marker_id = EXCLUDED.aruco_marker_id;
