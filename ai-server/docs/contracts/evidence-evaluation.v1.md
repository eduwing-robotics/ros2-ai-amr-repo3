# SmartFactory EvidenceEvaluation v1

`evidence-evaluation.v1` is the connector-facing AI Server response for the hardware-free Stage 1 evidence workflow.

It answers one narrow question:

> Given source/view/operation/expected evidence context, does the current AI/perception evidence look usable?

It does **not** complete a task, write Main DB rows, or promote trusted evidence. Main/connector owns task IDs, command IDs, DB insert, trusted promotion, and state transitions.

## Endpoint

```text
POST /api/v1/evidence/evaluate
```

The endpoint is intended for a Main connector or operator script. The connector may pass `task_ref` through the request; AI treats it as opaque context and returns it without querying Main DB.

Canonical proof-image request policy:

```json
{
  "image_policy": {
    "save_proof": true,
    "proof_label": "lift-up-before-drive"
  }
}
```

- `image_policy.save_proof` is the only request flag that asks AI Server to persist the latest frame as a proof image.
- `image_policy.proof_label` is an optional filename label used only when `save_proof` is `true`.
- `image_uri` is response-only. Callers must not submit it; AI Server generates it after storing a proof image under its configured evidence image root.

Optional conservative quality guardrail:

```json
{
  "quality_flags": {
    "low_pixel_budget": true,
    "details": {
      "object_size_m": 0.04,
      "effective_object_px": 12.8,
      "min_object_px": 16.0
    }
  }
}
```

When a quality flag is set, AI Server returns `UNCERTAIN`/`NEEDS_REVIEW`
instead of promoting the frame. This is used for small GoPro/global-camera
dropped-item targets before increasing continuous inference load.

## Required response fields

| Field | Meaning |
| --- | --- |
| `schema_version` | Always `evidence-evaluation.v1`. |
| `evaluation_id` | UUID for this evaluation response. |
| `source` | Vision source ID such as `global_cam_01`. |
| `view` | Source view such as `full` or `lift_roi`. |
| `operation` | `PICKUP`, `DROPOFF`, `MONITOR`, or `UNKNOWN`. |
| `expected_evidence_type` | Evidence requested by connector/Main, e.g. `ITEM_PICKED`. |
| `proposed_event_type` | AI's proposed event type for later Main storage. |
| `verification_status` | `PASS`, `FAIL`, or `UNCERTAIN`. |
| `validity` | `VALID_CANDIDATE`, `INVALID_CANDIDATE`, or `NEEDS_REVIEW`. |
| `reason_code` | Stable machine-readable judgement reason. |
| `confidence` | AI confidence from 0 to 1, or `null` when unavailable. |
| `trusted` | Always `false` in Stage 1. Main/policy may later promote. |
| `image_uri` | Optional proof image API path, served by the AI Server proof image route `/api/v1/evidence/images/{source}/{view}/{date}/{filename}` when the image is stored locally. It is server-generated and is not an absolute URL in Stage 1. |
| `task_ref` | Opaque pass-through IDs from connector/Main. |
| `data_json` | Detailed AI judgement and original perception payload. |
| `observed_at` | Observation/evaluation timestamp. |

## Judgement vocabulary

```text
verification_status: PASS | FAIL | UNCERTAIN
validity: VALID_CANDIDATE | INVALID_CANDIDATE | NEEDS_REVIEW
reason_code:
  COUNT_MATCH_AND_STABLE
  COUNT_MISMATCH
  DROPPED_ITEM_DETECTED
  LOW_CONFIDENCE
  LOW_PIXEL_BUDGET
  LOW_QUALITY_EVIDENCE
  ROI_NOT_STABLE
  NO_FRAME
  OBJECT_NOT_FOUND
  SOURCE_STALE
  MODEL_UNAVAILABLE
  POLICY_NOT_APPLICABLE
```

`LOW_PIXEL_BUDGET` and `LOW_QUALITY_EVIDENCE` are conservative GoPro/global-camera
guardrail outcomes. They always mean `verification_status=UNCERTAIN` and
`validity=NEEDS_REVIEW`; Main should store/review them as advisory evidence,
not as task-completion truth.

## Stage 1 invariants

- Stream paths remain separate and read-only: `/api/v1/vision/{overlay|frame}/stream`.
- `/api/v1/vision/events` is not a streaming endpoint.
- Direct Main emission is Stage 2 only; Stage 1 does not depend on `wms_client.py` success.
- `trusted` is always `false` in normal AI responses.
- Proof images use server-generated `/api/v1/evidence/images/...` API paths only; request-supplied `image_uri`, absolute URLs, stale `/api/v1/evidence/files/...`, and encoded path traversal are rejected.
- Mappers must not call Main DB or infer task state.
- `dist/SmartFactory_MVP` is not modified.
