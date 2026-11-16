# Day 4 live results: retrieval (RAG) + bounded Tree-of-Thought + guardrails

Run on 2026-11-16 with `python -m inspectbot.flow.run S1 S2 S3 S4 S5`. Models are the same as Day 3. Embeddings use `hashing` (offline). These are single pilot runs, not general performance claims.

| Scenario | Correct | Outcome | Robot actions (Day 3 → Day 4) | Procedure cited | Time |
| --- | --- | --- | --- | --- | --- |
| S1 shadow | No defect | ✓ No defect detected | 1 → 1 (`set_lighting top`) | PROC-MB-001 v2.1 (MB-1) | 32 s |
| S2 crack | Suspected defect | ✓ Suspected defect | 2 → 2 + reference | PROC-CT-001 v1.3 (CT-1) | 59 s |
| S3 seam | No defect | ✓ No defect detected | 2 → 0 + reference | PROC-GB-001 v3.0 (GB-1) | 29 s |
| S4 occluded | Insufficient | ✓ Insufficient → human review | 5 → 4 (2 failed, never cited) | PROC-MB-002 v1.0 | 58 s |
| S5 no guidance | Insufficient | ✓ Insufficient → human review | 5 → 0 | none (missing guidance recorded) | 5 s |

The prompt-only baseline is unchanged from Day 3: it was correct on 2 of 5 and called S1, S3 and S5 cracks.

## What retrieval changed
- **S3:** procedure GB-1 says to compare with the reference, so InspectBot fetched the reference first and concluded with zero robot moves (Day 3 needed two).
- **S5:** the decoy procedure `PROC-CT-003` ("straight persistent line on a flat cover is a crack") had the highest similarity overall (0.27). The category filter rejected it as written for `ceramic_tile`. No `pump_housing` procedure exists, so the Coordinator escalated immediately: no budget spent, and no agent was asked to invent a criterion.
- **S2:** `PROC-CT-003` is a legitimate tile procedure, so it was retrieved too, and it conflicts with `PROC-CT-001`. The verifier applied the more demanding CT-1 (lighting persistence + discontinuity + absent from reference), as the prompt requires for conflicting procedures.
- **S4:** `PROC-MB-002` says only `left_45` can see past the clamp and lighting does not help. Once `left_45` was unreachable, the planner stopped instead of spending its last action.

## What Tree-of-Thought did (once per inspection, at most 15 evaluations)
| Scenario | Candidates | Selected | Pruned |
| --- | --- | --- | --- |
| S1 | 1 | `set_lighting(top)`, 10/10 (MB-1 shadow test) | none |
| S2 | 3 | `set_lighting(right)`, 10/10 (CT-1 persistence test) | 1 outside beam (6/10) |
| S3 | 3 | `get_reference(glass_bottle)`, 10/10 (GB-1) | 1 outside beam (6/10) |
| S4 | 3 | `move_camera(left_45)`, 10/10 (MB-2 required view; then guarded, since it had already failed) | lighting (4/10) and oblique (3/10), below 5 |

Every search stopped at depth 1 because a candidate met the selection threshold (8/10 or above), so each ToT invocation cost 2 LLM calls. Deeper search (beam 2, depth 3, cap 15) is exercised in the tests.

## Guardrails added
- Conclusions must cite a retrieved procedure written for the object's category. General guidance alone, or a procedure that wasn't retrieved, is refused.
- Retrieval uses the task's confirmed category on the server side; agents cannot choose a different category.
- Retrieved passages are delimited as reference data. Passages containing embedded instructions are flagged and excluded.
- Superseded procedure versions are never indexed.
- ToT is limited to once per inspection and 15 evaluations, enforced by the MCP server. Its predictions are stored as candidates, never as observations.
