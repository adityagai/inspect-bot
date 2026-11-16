# InspectBot

InspectBot is a multi-agent research assistant for **simulated robotic visual inspection**, built for the Agentic AI capstone. Given one object and an inspection goal, it gathers evidence by moving a virtual camera arm and changing the light, and it checks that evidence against retrieved inspection procedures. It reports one of three outcomes, each linked to the observations and procedures that support it:

- **Suspected defect**
- **No defect detected**: covers only the inspected region; it is not a safety certification.
- **Insufficient evidence**: always escalated for human review.

The problem it tackles is that a single image often can't tell a crack from a shadow or an expected seam. A one-shot model guesses; InspectBot treats the line as a hypothesis, picks the observation that would tell the explanations apart, and stops when the evidence is either sufficient or unobtainable.

| | |
| --- | --- |
| **Models** | Anthropic Claude: `claude-sonnet-5-5` (Inspection with vision, Verification), `claude-haiku-5-5` (Planning) |
| **Agents** | CrewAI: a Flow as the Coordinator, plus Planning, Inspection and Verification agents |
| **Knowledge** | LangChain + Chroma retrieval over versioned procedures |
| **Tools** | MCP server (FastMCP) exposing the robot cell, the shared task record, retrieval and reports |
| **Robot** | CPU-only simulated inspection cell (numpy + Pillow); no GPU, no physical hardware |

## Pilot results so far

Live single runs on the five demo scenarios ([Day 3](docs/day3_live_results.md), [Day 4](docs/day4_live_results.md)). These are pilot runs, not general performance claims.

| Scenario | Correct outcome | InspectBot | Robot actions | Procedure cited | Prompt-only baseline |
| --- | --- | --- | --- | --- | --- |
| S1 fixture shadow | No defect | ✓ | 1 | PROC-MB-001 | ✗ called it a crack |
| S2 real crack | Suspected defect | ✓ | 2 + reference | PROC-CT-001 | ✓ |
| S3 mold seam | No defect | ✓ | 0 + reference | PROC-GB-001 | ✗ called it a crack |
| S4 clamp hides target | Insufficient → review | ✓ (2 failed moves logged, never cited) | 4 | PROC-MB-002 | ✓ |
| S5 no procedure for part | Insufficient → review | ✓ (decoy procedure rejected) | 0 | missing guidance | ✗ called it a crack |

InspectBot made no incorrect definitive calls (0/5); the baseline made 3/5.

## Architecture

```mermaid
flowchart LR
    U[User: scenario + goal] --> C
    subgraph CrewAI["CrewAI Flow (Coordinator)"]
        C[Coordinator<br/>budgets, guards, stop rules]
        P[Planning agent<br/>Haiku + bounded ToT]
        I[Inspection agent<br/>Sonnet, vision]
        V[Verification agent<br/>Sonnet]
        C <--> P
        C <--> I
        C <--> V
    end
    C <-->|MCP over HTTP| M
    subgraph MCP["MCP server"]
        M[Tools]
        T[(Task record<br/>+ event log)]
        R[(Chroma procedures<br/>LangChain retriever)]
        S[Simulated inspection cell<br/>camera arm + light]
        M --- T
        M --- R
        M --- S
    end
    C --> Rep[Report: outcome, evidence obs_ids,<br/>sources, uncertainty, human review]
```

Each inspection runs as a ReAct loop inside the Flow:

```
begin -> inspect -> verify -> decide --criteria_met---> conclude   (definitive report)
           ^          |          |----need_evidence---> plan_and_act --acted--+
           |      (retrieve      |                                 --needs_human--> escalate
           |       procedures    |                                            |
           |       once)         +----needs_human-----> escalate   (Insufficient evidence + human review)
           +----------------------------------------------------------------+
```

| Agent | Model | Job | Output |
| --- | --- | --- | --- |
| Coordinator | none (code) | Routes work, runs every robot action through MCP, enforces budgets and guards, builds the report | Report |
| Inspection | `claude-sonnet-5-5`, images via CrewAI `input_files` | Describes what each image shows; never gives a verdict | Target visible? anomaly? surface discontinuity? matches reference? |
| Planning | `claude-haiku-5-5` | Picks the next action from a code-generated list of new views, using bounded Tree-of-Thought when explanations compete | One action, or stop |
| Verification | `claude-sonnet-5-5` | Checks evidence against retrieved procedures; scores ToT candidates | Proposed outcome, cited `obs_id`s, applied procedures, missing evidence |
| Baseline | `claude-sonnet-5-5` | One call on the same first image, no tools | Outcome |

Agents only propose. The Coordinator executes every action through the MCP tools, so budgets, failures and evidence are recorded in one place.

## Quick start

```bash
git clone https://github.com/adityagai/inspect-bot-rag.git && cd inspect-bot-rag
python -m venv .venv && source .venv/bin/activate      # Python 3.11+
pip install -e ".[dev,agents]"
cp .env.example .env                                   # add your ANTHROPIC_API_KEY

pytest -q                                              # 58 tests, about 12 s, no API calls
python -m inspectbot.flow.run S1                       # inspect one scenario
python -m inspectbot.flow.run S1 S2 S3 S4 S5 --baseline  # all five, plus the baseline
```

### Other commands

| Command | What it does |
| --- | --- |
| `python -m inspectbot.mcp_server.server` | Start the MCP server (streamable HTTP at `http://127.0.0.1:8765/mcp`) |
| `python -m inspectbot.flow.run S1 --mcp` | Run the inspection through the MCP server over HTTP |
| `python -m inspectbot.flow.run S1 --no-rag` / `--no-tot` | Ablations: built-in general criteria instead of retrieval / plain planning instead of ToT |
| `python -m inspectbot.sim.preview --all` | Render every pose × light view per scenario to `runs/preview/<id>/contact_sheet.png` |
| `python scripts/vision_check.py S1 S2` | Show Claude the first image of each scenario and print what it sees |
| `python scripts/smoke_crewai_mcp.py` | A CrewAI agent drives the robot through the MCP server (end-to-end check) |

Each run writes `runs/<task_id>/` containing:
- `task_record.json`: all attempts, observations, findings, ToT candidates and messages
- `events.jsonl`: for the upcoming Streamlit app
- `report.json`
- `images/`

## How it works

### The simulated inspection cell

The "robot" is a camera arm with 5 poses (`front`, `left_45`, `right_45`, `top`, `oblique_low`) and a light with 4 settings (`left`, `right`, `top`, `diffuse`). Parts are rendered procedurally and warped to each camera pose. Each scenario plants features with deliberate, physically motivated rules:

| Feature | Looks like | What tells it apart |
| --- | --- | --- |
| Crack | dark, slightly jagged line | stays under every light; `oblique_low` shows a raised lip |
| Cast shadow | dark, soft line | moves with side light; gone under `top` or `diffuse` |
| Mold seam | straight, even line | on the reference image at the documented position |
| Occlusion | clamp over the target | visible only from listed poses (which may be unreachable) |

Robot moves can fail on purpose (`unreachable`, `timeout`, `unsupported`). A failed call writes an `ActionAttempt` and **never** an `Observation`, and the data models reject any attempt to store one.

### MCP tools

One long-lived MCP server holds every inspection session, so all agents share one task record.

| Tool | Group | Rules |
| --- | --- | --- |
| `start_inspection` | lifecycle | Returns the public task definition, the first observation and the budget; never ground truth |
| `move_camera`, `set_lighting` | robot | 5 evidence actions per inspection, failures included; a 6th is refused and logged |
| `zoom_region`, `get_reference`, `get_observation_image` | image | Capped at 6 per inspection; zoom cannot add detail |
| `retrieve_procedures` | knowledge | Always uses the task's confirmed category; reports rejected cross-category hits and missing guidance |
| `record_tot` | reasoning | Once per inspection, at most 15 candidate evaluations |
| `get_task_record`, `append_finding`, `post_message` | shared record | Anything citing an unknown `obs_id` is rejected |
| `submit_report` | output | Validates the outcome rules and that every cited observation exists, then saves `report.json` |

### Procedures and retrieval

`corpus/` holds 14 short documents:
- synthetic, versioned procedures per object category
- general guidelines and an escalation policy
- three public references, summarized in our own words

It deliberately includes a superseded version (never indexed) and a decoy tile procedure worded to match the S5 query.

`rag/retriever.py` works like this:
1. **Chunking:** LangChain section-aware chunks of about 150–300 words, so each rule keeps its conditions.
2. **Index:** a Chroma collection.
3. **Filter first:** only the task's category plus `general` guidance is eligible.
4. **Rank:** top 3 by similarity, with duplicates removed.
5. **Visible rejections:** strong matches for other categories are reported as rejected.
6. **Missing guidance:** if no procedure exists for the category, the Coordinator escalates immediately instead of letting an agent invent a criterion.

Embeddings default to `hashing` (offline, deterministic). Set `INSPECTBOT_EMBEDDINGS=minilm` to use Chroma's local MiniLM model.

### Bounded Tree-of-Thought

`reasoning/tot.py` runs at most once per inspection, only when the evidence has competing explanations.

1. Planning proposes up to 3 candidate steps, each with the hypothesis it tests and what each explanation predicts.
2. Verification scores each candidate from 0 to 10:

   | Rubric item | Points |
   | --- | --- |
   | Evidence support | 0–3 |
   | Ability to tell the explanations apart | 0–3 |
   | Procedure compliance | 0–2 |
   | Feasibility and cost | 0–2 |

3. Code then applies the search rules:
   - validity checks first
   - prune below 5
   - beam of 2, depth up to 3, cap of 15 evaluations
   - early stop at 8 or above
   - deterministic tie-breaks

4. The first action of the best branch goes back to the ReAct loop.

Predictions are stored as candidates, never as observations.

### Guardrails (enforced in code, not prompts)

- **Plans:** must produce a new view and must not repeat a failed action. After 3 rejected plans in a row, the Coordinator escalates.
- **Definitive outcomes need:**
  - real cited observations
  - a visible target
  - no unresolved contradiction
  - a retrieved procedure written for the object's category (general guidance alone is not enough)
- **No defect detected** must state its scope. **Insufficient evidence** must request human review.
- **Retrieved text is data, not instructions:** passages with embedded instructions are flagged and excluded.
- **Server-side limits:** the action budget, the auxiliary-call cap and the ToT limits are enforced by the MCP server.
- **Ground truth stays hidden:** it never leaves the scenario files; agents only receive `Scenario.public_view()`.

## Demo scenarios

| ID | Part | First image | Expected path | Correct outcome |
| --- | --- | --- | --- | --- |
| S1 | metal bracket | dark line (fixture shadow) | change the light; the line disappears | No defect detected |
| S2 | ceramic tile | dark line (crack) | persists under two lights, lip at `oblique_low`, absent from reference | Suspected defect |
| S3 | glass bottle | dark line (mold seam) | compare with the reference per the seam procedure | No defect detected |
| S4 | metal bracket | clamp hides the target | `left_45` unreachable, `right_45` times out, other poses still blocked | Insufficient evidence → review |
| S5 | pump housing | dark line | no procedure exists; similar tile procedure rejected | Insufficient evidence → review |

Ground truth lives in `scenarios/*.yaml` and is used only for scoring.

## Configuration (`.env`)

| Variable | Default | Purpose |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | — | Required for live runs |
| `INSPECTBOT_VISION_MODEL` | `claude-sonnet-5-5` | Inspection agent and baseline |
| `INSPECTBOT_VERIFY_MODEL` | `claude-sonnet-5-5` | Verification agent (the judge) |
| `INSPECTBOT_TEXT_MODEL` | `claude-haiku-5-5` | Planning agent |
| `INSPECTBOT_EMBEDDINGS` | `hashing` | `hashing` (offline) or `minilm` |
| `INSPECTBOT_RUNS_DIR` | `runs` | Where runs are written |
| `INSPECTBOT_MCP_PORT` | `8765` | MCP server port |

## Tests

`pytest -q` runs 58 tests in about 12 seconds with no API calls. Agents are replaced by scripted outputs, and MCP tests go through a real in-memory MCP client.

| File | Covers |
| --- | --- |
| `test_models.py` | Evidence rules, budget accounting, report rules |
| `test_sim.py` | Rendering rules per scenario, failure injection, zoom, references, hidden ground truth |
| `test_mcp_server.py` | Every MCP tool, failures never becoming evidence, budget exhaustion, report validation |
| `test_flow.py` | Coordinator routing, replanning after failures, rejection limits, conclusion guards, baseline |
| `test_rag_tot.py` | Corpus versions, category filtering, decoy rejection, injection exclusion, missing guidance, ToT selection, pruning, beam and depth limits, server-side ToT cap |

## Repository layout

```
src/inspectbot/
  core/        models.py (TaskRecord, ActionAttempt, Observation, Finding, Candidate, Message, Report),
               task_store.py, events.py
  sim/         scenario.py, renderer.py, cell.py (robot tools + failures), schematic.py, preview.py
  mcp_server/  session.py (sessions, budget, retrieval, ToT, reports), server.py (FastMCP tools)
  agents/      llm.py (Claude for CrewAI), schemas.py, prompts.py, runner.py (CrewAI / scripted)
  flow/        inspection_flow.py (Coordinator), guards.py, gateway.py (MCP / local), run.py (CLI)
  rag/         retriever.py (corpus, chunking, Chroma, category filter, injection flags)
  reasoning/   tot.py (bounded Tree-of-Thought)
  baseline/    prompt_only.py
corpus/        14 procedure / guideline / reference documents with front matter
scenarios/     S1–S5 YAML (features, scripted failures, ground truth)
scripts/       vision_check.py, smoke_crewai_mcp.py
docs/          day1_vision_check.md, day3_live_results.md, day4_live_results.md
tests/
```

## Build status

| Day | Scope | State |
| --- | --- | --- |
| 1 | Data models, simulated inspection cell, S1–S5 scenarios, cell diagram, preview tool | merged (#1) |
| 2 | MCP server for robot tools and the shared task record; CrewAI → MCP smoke test | merged (#2) |
| 3 | CrewAI Flow Coordinator, Planning / Inspection / Verification agents, ReAct loop, baseline | merged (#3) |
| 4 | Retrieval over versioned procedures, bounded Tree-of-Thought, guardrails | in review (#4) |
| 5 | Streamlit app (live + replay, ToT tree, human-review panel), evaluation over 20 scenarios, demo recordings | next |

## Scope and limitations

- **Simulated only:** one object per inspection, in simulation or advisory mode. No physical equipment is controlled.
- **Synthetic procedures:** they were written for these experiments and are not industry standards. Public references are paraphrased summaries.
- **Pilot results:** the results above come from single pilot runs. Model outputs can vary between runs.
