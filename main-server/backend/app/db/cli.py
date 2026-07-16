"""Database migration and release reference commands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.db.connection import transaction
from app.db.map_reference import DEFAULT_MANIFEST, export_locations, load_manifest, sync_reference, verify_assets
from app.db.migrations import apply_migrations, migration_status


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["migrate", "status", "reference-verify", "reference-sync", "reference-export"])
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.command == "reference-verify":
        manifest = load_manifest(args.manifest)
        verify_assets(manifest)
        print(f"reference OK: {manifest['map_id']} revision={manifest['revision']} locations={len(manifest['locations'])}")
        return 0

    if args.command == "reference-export":
        if args.output is None:
            parser.error("reference-export requires --output; review before replacing the tracked manifest")
        manifest = load_manifest(args.manifest)
        verify_assets(manifest)
        with transaction() as conn:
            exported = export_locations(conn, manifest)
        args.output.write_text(json.dumps(exported, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"exported {len(exported['locations'])} locations: {args.output}")
        return 0


    with transaction() as conn:
        if args.command == "migrate":
            completed = apply_migrations(conn)
            print("applied: " + (", ".join(completed) if completed else "none"))
        elif args.command == "status":
            for row in migration_status(conn):
                state = "applied" if row["applied"] else "pending"
                integrity = "ok" if row["checksum_ok"] else "edited"
                print(f"{row['version']} {state} checksum={integrity} {row['name']}")
        else:
            manifest = load_manifest(args.manifest)
            count = sync_reference(conn, manifest)
            print(f"synchronized {count} locations for revision {manifest['revision']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
