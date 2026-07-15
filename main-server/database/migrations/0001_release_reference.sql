-- Track locations managed by the versioned map reference manifest.
ALTER TABLE locations ADD COLUMN IF NOT EXISTS release_managed BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE locations ADD COLUMN IF NOT EXISTS release_revision TEXT;

CREATE INDEX IF NOT EXISTS idx_locations_release_managed
    ON locations(release_managed) WHERE release_managed = TRUE;
