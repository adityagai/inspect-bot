# InspectBot

InspectBot is a multi-agent research assistant for **simulated robotic visual inspection**, built for the Agentic AI capstone. It inspects one object at a time and gathers evidence by moving a virtual camera arm and changing the light. It reports one of three outcomes, each linked to the observations that support it:

- **Suspected defect**
- **No defect detected**: covers only the inspected region; it is not a certification.
- **Insufficient evidence**: always escalated for human review.

Stack: Anthropic Claude (Sonnet for vision, Haiku for text agents), CrewAI (Flow + agents), LangChain (RAG, Tree-of-Thought search), MCP (robot and task-store tools) and Streamlit. Everything runs on CPU.

## Status

| Day | Scope | State |
| --- | --- | --- |
| 1 | Repo scaffold, data models, virtual inspection cell, S1–S5 scenarios, schematic, preview tool | this branch |
| 2 | MCP server for robot tools + task store | planned |
| 3 | CrewAI Flow Coordinator + Planning / Inspection / Verification agents, ReAct loop, baseline | planned |
| 4 | LangChain RAG, bounded ToT, guardrails, escalation | planned |
| 5 | Streamlit app (live + replay), evaluation | planned |

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env               # add ANTHROPIC_API_KEY (needed from Day 2; optional today)

pytest -q                          # 21 tests, under 2 s
python -m inspectbot.sim.preview --all   # writes runs/preview/<id>/contact_sheet.png
python scripts/vision_check.py S1 S2     # optional: what Claude sees in the first image
```

## The virtual inspection cell

The "robot" is a camera arm with 5 poses (`front`, `left_45`, `right_45`, `top`, `oblique_low`) and a light with 4 settings (`left`, `right`, `top`, `diffuse`). Parts are rendered procedurally with numpy and Pillow, then warped to each camera pose.

| Tool | Budget | Can fail with |
| --- | --- | --- |
| `move_camera(pose)` | counts (max 5 evidence actions per inspection, failures included) | `unreachable`, `timeout`, `invalid_args` |
| `set_lighting(setting)` | counts | `unsupported`, `invalid_args` |
| `zoom_region(obs_id, bbox)` | auxiliary (capped at 6) | `invalid_args`, `not_found` |
| `get_reference(category)` | auxiliary | `not_found` |

A failed call writes an `ActionAttempt` and **never** an `Observation`. The models reject any attempt to store one. Images travel as file paths, not bytes.

Feature rules the scenarios rely on:

| Feature | Looks like | Tells it apart |
| --- | --- | --- |
| crack | dark, slightly jagged line | stays under every light; `oblique_low` shows a raised lip |
| cast shadow | dark, soft line | moves with side light; gone under `top` or `diffuse` |
| seam | straight, even line | on the reference image at the documented position |
| occlusion | clamp over the target | visible only from listed poses |

## Demo scenarios

| ID | Part | First image | Expected outcome |
| --- | --- | --- | --- |
| S1 | metal bracket | dark line (fixture shadow) | No defect detected after a lighting change |
| S2 | ceramic tile | dark line (crack) | Suspected defect: persists + lip at `oblique_low` |
| S3 | glass bottle | dark line (mold seam) | No defect detected: matches the procedure and reference |
| S4 | metal bracket | clamp hides the target; `left_45` unreachable, `right_45` times out | Insufficient evidence → human review |
| S5 | pump housing | dark line; no procedure for this category | Insufficient evidence → human review |

Ground truth lives in `scenarios/*.yaml` and is used only for scoring. Agents receive `Scenario.public_view()`.

## Layout

```
src/inspectbot/
  core/        models.py (TaskRecord, ActionAttempt, Observation, Finding, Candidate, Message, Report), task_store.py
  sim/         scenario.py, renderer.py, cell.py, schematic.py, preview.py
  mcp_server/  flow/  agents/  reasoning/  rag/  baseline/   # later days
scenarios/     S1–S5 YAML
scripts/       vision_check.py
tests/
```
