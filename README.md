# InspectBot

InspectBot is a multi-agent research assistant for **simulated robotic visual inspection**, built for the Agentic AI capstone. It inspects one object at a time and gathers evidence by moving a virtual camera arm and changing the light. It reports one of three outcomes, each linked to the observations that support it:

- **Suspected defect**
- **No defect detected**: covers only the inspected region; it is not a certification.
- **Insufficient evidence**: always escalated for human review.

Stack: Anthropic Claude (Sonnet for vision, Haiku for text agents), CrewAI (Flow + agents), LangChain (RAG, Tree-of-Thought search), MCP (robot and task-store tools) and Streamlit. Everything runs on CPU.

## Status

| Day | Scope | State |
| --- | --- | --- |
| 1 | Repo scaffold, data models, virtual inspection cell, S1–S5 scenarios, schematic, preview tool | merged (#1) |
| 2 | MCP server for robot tools + task store; CrewAI agent → MCP smoke test | merged (#2) |
| 3 | CrewAI Flow Coordinator + Planning / Inspection / Verification agents, ReAct loop, baseline | this branch |
| 4 | LangChain RAG, bounded ToT, guardrails, escalation | planned |
| 5 | Streamlit app (live + replay), evaluation | planned |

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env               # add ANTHROPIC_API_KEY (needed from Day 2; optional today)

pytest -q                          # 45 tests, about 10 s (no API calls)
python -m inspectbot.sim.preview --all   # writes runs/preview/<id>/contact_sheet.png
python scripts/vision_check.py S1 S2     # optional: what Claude sees in the first image
```

## Running an inspection (Day 3)

```bash
python -m inspectbot.flow.run S1                    # in-process tools
python -m inspectbot.flow.run S1 S4 --baseline      # plus the prompt-only baseline
python -m inspectbot.mcp_server.server &            # or through the MCP server ...
python -m inspectbot.flow.run S1 --mcp              # ... over HTTP
```

The Coordinator is a CrewAI Flow (`flow/inspection_flow.py`) that runs a ReAct loop:

```
begin -> inspect -> verify -> decide --criteria_met---> conclude   (definitive report)
           ^                     |----need_evidence---> plan_and_act --acted--+
           |                     |                                 --needs_human--> escalate
           +---------------------+-------------------------------------------+
                                 +----needs_human-----> escalate   (Insufficient evidence + human review)
```

| Agent | Model | Output |
| --- | --- | --- |
| Inspection | `claude-sonnet-5-5` (vision, via CrewAI `input_files`) | target visible? anomaly? surface discontinuity? matches reference? |
| Verification | `claude-sonnet-5-5` | proposed outcome, sufficient?, cited `obs_id`s, missing evidence |
| Planning | `claude-haiku-5-5` | one next action from a code-generated candidate list, or stop |
| Baseline | `claude-sonnet-5-5` | one-shot outcome from the first image |

Rules enforced in code (`flow/guards.py`), not prompts:
- a plan must be a new view and must not repeat a failed action
- 3 rejected plans in a row means escalate
- a conclusion needs real cited observations, a visible target and no contradictions
- the budget is enforced server-side

Live pilot results are in [`docs/day3_live_results.md`](docs/day3_live_results.md): InspectBot was 5/5, the baseline 2/5.

## MCP server (Day 2)

One long-lived server process holds every inspection session, so all agents share the same task record:

```bash
pip install -e ".[dev,agents]"
python -m inspectbot.mcp_server.server          # streamable HTTP at http://127.0.0.1:8765/mcp
python scripts/smoke_crewai_mcp.py              # CrewAI agent (Claude) drives S1 through MCP
```

| Tool | Group | Notes |
| --- | --- | --- |
| `start_inspection(scenario_id)` | lifecycle | returns `task_id`, the public task definition, the initial observation and the budget; never ground truth |
| `move_camera(task_id, pose)`, `set_lighting(task_id, setting)` | robot (budgeted) | 5 per inspection, failures included; a 6th call returns `budget_exhausted` and does not run |
| `zoom_region`, `get_reference`, `get_observation_image` | image (capped at 6) | `get_observation_image` returns the PNG as MCP image content for vision models |
| `get_task_record`, `append_finding`, `post_message` | shared record | findings and messages that cite unknown `obs_id`s are rejected |

Each run writes `runs/<task_id>/task_record.json`, `events.jsonl` (for the Streamlit app) and `images/`. Agents get a per-role tool allow-list through CrewAI's `create_static_tool_filter`.

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
  core/        models.py (TaskRecord, ActionAttempt, Observation, Finding, Candidate, Message, Report), task_store.py, events.py
  sim/         scenario.py, renderer.py, cell.py, schematic.py, preview.py
  mcp_server/  session.py (sessions, budget, logging, reports), server.py (FastMCP tools)
  agents/      llm.py (Claude for CrewAI), schemas.py, prompts.py, runner.py (CrewAI / scripted)
  flow/        inspection_flow.py (Coordinator), guards.py, gateway.py (MCP / local), run.py
  baseline/    prompt_only.py
  reasoning/  rag/   # Day 4
scenarios/     S1–S5 YAML
scripts/       vision_check.py, smoke_crewai_mcp.py
docs/          day1_vision_check.md, day3_live_results.md
tests/
```
