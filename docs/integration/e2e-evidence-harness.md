# E2E evidence harness

`scripts/run-e2e-evidence.py` wraps an existing E2E command and retains its
stdout, stderr, exit code, Git revision/dirty state, and SHA-256 hashes in a
machine-readable bundle. The caller must select one provenance value:
`physical`, `simulation`, or `synthetic-hil`.

```bash
python3 scripts/run-e2e-evidence.py \
  --provenance synthetic-hil \
  --output-root /tmp/amr-e2e-evidence \
  -- ./scripts/test-nohardware.sh
```

The command's exit code is preserved. Every manifest contains
`PHYSICAL_LIFT_NOT_VERIFIED`; neither a passing command nor selection of the
`physical` provenance upgrades lift actuation to verified. A physical run may
attach an operator artifact with `--physical-lift-evidence`, but the harness
only hashes that artifact and still does not assert that its contents prove
physical lift motion. A separately approved physical validation protocol is
required to remove the limitation.

Bundles are written to `<output-root>/<run-id>/`. An existing run directory is
never overwritten. Use `--run-id` when an external test plan supplies the
identifier; otherwise the harness creates a UUID.
