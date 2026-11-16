# Day 1 vision check: what Claude sees in each first image

Run on 2026-11-16 with `python scripts/vision_check.py`. Model: `claude-sonnet-5-5`. The model sees only the initial image, the same one the prompt-only baseline gets.

| Scenario | Ground truth | What Claude saw | Crack confidence | Suggested next observation | Matches design? |
| --- | --- | --- | --- | --- | --- |
| S1 shadow | No defect | Dark, slightly wavy vertical line; plausible crack / scratch / cast shadow | medium | Change lighting (raking both sides, diffuse) and viewpoint; shadow would move or vanish | Yes: ambiguous, and it names the distinguishing action |
| S2 crack | Suspected defect | Thin jagged line, crisp edges; "most consistent with a crack or deep scratch" | medium | Close-up under raking or oblique light; check for depth or step | Yes: suspicious but not definitive from one view |
| S3 seam | No defect | Perfectly straight, even line at the centre; "designed seam most likely" | low | Compare with a reference image; oblique raking light | Yes: the reference + procedure confirm it |
| S4 occluded | Insufficient | Sees a mounted plate with fasteners; no crack visible | low | Oblique viewpoint to see behind or around it | Yes: target hidden behind the clamp |
| S5 no guidance | Insufficient | Straight horizontal line; "strongly suggests a seam" | low | Reference image; oblique raking light | Yes, and a useful trap: the model leans toward "seam, no defect", which the RAG guardrail must block when no procedure applies |

Cost: about 600 input and 600–800 output tokens per image.

Notes for later days:
- S1 and S2 both point to lighting and viewpoint changes. Those are exactly the robot tools the Planning agent can use, so the ToT branches will have real actions to compare.
- S5 is the baseline's likely unsupported conclusion and a good guardrail demo.
- The brushed-metal texture has one bright row that Claude mentions as a possible artifact. It is harmless, but it can be toned down if it distracts.
