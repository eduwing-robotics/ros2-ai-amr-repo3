# Documentation governance

This guide is the repository-wide policy for Root, Hardware, Nav, Main, and AI documentation.
Service-local guides may add service details, but must link here rather than
repeat these rules.

## Contract

- A document has one primary type: reference/current behavior, operations,
  decision, history/evidence, plan/work-in-progress, or index/supporting asset.
- The filesystem path is part of that type contract. The normative mapping is
  [`documentation-path-matrix.json`](documentation-path-matrix.json).
- Subject and document type are separate. A feature is a subject, not a generic
  `feature/` document type.
- One fact has one canonical owner. Other documents use a short link instead of
  copying prose or command blocks.
- `nav-server/config/robots.json` remains the canonical hardware-facts source.
- Synthetic HIL is nonphysical evidence. It uses `SIMULATION_MODE=0` and must
  retain `PHYSICAL_LIFT_NOT_VERIFIED`; it never proves a physical lift.

## Type boundaries

| Type | Content | Canonical roots |
| --- | --- | --- |
| Reference/current behavior | Current contracts and as-built behavior | registered `reference`, `api`, `interfaces`, `architecture`, `ui-ux`, `as-built` roots |
| Operations | Executable procedures only | root/Main `operations`, Nav `runbook` |
| Decision | Decisions and tradeoffs only | Main `decisions`, Nav `adr` |
| History/evidence | Past events and retained evidence | root `history`, registered worklogs |
| Plan/work-in-progress | Proposed work, not current behavior | `.omx/plans`, `.omx/specs`, registered worklogs |
| Index/support | Routing, templates, and declared assets | explicit matrix exceptions |

## Change workflow

1. Run `./scripts/check_docs.sh` before and after documentation changes.
2. Use the local `docs-governance` skill to audit and generate an inventory.
3. Review the inventory; `apply` is dry-run unless `--execute` is explicit.
4. Propose material policy changes with `policy-proposal` and `$ralplan`; normal
   cleanup must not silently edit this guide or the matrix.
5. Keep the complete skill under `${CODEX_HOME:-$HOME/.codex}/skills/` only.

Only deterministic structure is mechanically enforced: registered paths,
indexes, first-level titles, and local Markdown links. Prose quality and type
purity remain review requirements.
