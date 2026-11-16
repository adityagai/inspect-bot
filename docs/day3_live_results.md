# Day 3 live results: InspectBot vs prompt-only baseline

Run on 2026-11-16 with `python -m inspectbot.flow.run S2 S4 S5 S1 S3 --baseline`. Inspection used `claude-sonnet-5-5` (vision), Verification used `claude-sonnet-5-5`, Planning used `claude-haiku-5-5`, and the baseline used `claude-sonnet-5-5` on the same first image. S1 was repeated through the MCP server over HTTP (`--mcp`) with the same result.

These are single pilot runs, not general performance claims. Day 4 adds retrieval (RAG) and Tree-of-Thought; Day 5 adds the full evaluation.

| Scenario | Correct | InspectBot | Evidence actions | Time | Baseline |
| --- | --- | --- | --- | --- | --- |
| S1 shadow | No defect | ✓ No defect detected | 1 (light right) | 25 s | ✗ Suspected defect |
| S2 crack | Suspected defect | ✓ Suspected defect | 2 (light right, oblique_low) | 36 s | ✓ Suspected defect |
| S3 seam | No defect | ✓ No defect detected | 2 + reference | 54 s | ✗ Suspected defect |
| S4 occluded | Insufficient | ✓ Insufficient → human review | 5 (2 failed, never cited) | 62 s | ✓ Insufficient |
| S5 no guidance | Insufficient | ✓ Insufficient → human review | 5 | 89 s | ✗ Suspected defect |

- **Incorrect definitive outcomes:** InspectBot 0 of 5; baseline 3 of 5.
- **Average actions on resolvable cases (S1–S3):** 1.7, against a target of 3 or fewer.
- **Grounding:** every definitive report cites real observations, and no failed attempt is cited.

## What the live runs taught us (and what changed)

| Problem seen | Fix |
| --- | --- |
| The verifier could not tell which attached image was which | The prompt states the image order (FIRST = current, SECOND = earlier) |
| The verifier did not know each observation's pose and light, so it could not apply the same-pose shadow rule | Every inspection result carries its `view` (kind, pose, light) from the robot, plus a deterministic same-pose table |
| The Inspection agent speculated that "the camera may have moved", and the verifier treated that as a contradiction | The robot's pose and light are declared authoritative; speculation is ignored |
| The planner kept proposing views it already had | It now picks from a code-generated list of actions that produce a new view; guards still reject repeats |
| The planner spent lighting changes on an occluded target | Prompt: lighting cannot reveal a covered region; only camera moves can |
| The planner sometimes wrote the string "None" for empty fields | A validator maps it to null, and the runner retries once on malformed output |
| The verifier listed leftover hypotheses as "contradictions", which blocked a valid conclusion | The field is defined as conflicting observations only, and the Coordinator logs its reason whenever it refuses a conclusion |
