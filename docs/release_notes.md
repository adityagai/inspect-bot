# InspectBot release notes

## mvp-v1 (updated 2026-11-20)

InspectBot is a multi-agent research assistant for robotic visual inspection. It reports one of three outcomes: **suspected defect**, **no defect detected** (for the inspected region only) or **insufficient evidence** (always escalated to a human). Every outcome cites the observations and versioned procedures behind it.

**Stack:** CrewAI Flow coordinator with Planning, Inspection and Verification agents on Claude · LangChain + Chroma retrieval over versioned procedures · an MCP server for the robot cell, the shared task record and reports · a CPU-only simulated inspection cell · a Streamlit replay and live app.

### Results (single pilot runs)

| | InspectBot | Prompt-only baseline |
| --- | --- | --- |
| **Simulation**, 20 scenarios: correct outcomes | **20/20** | 8/20 |
| Simulation: incorrect definitive outcomes | **0** | 12 |
| **MVTec AD**, 40 real images (bottle, tile): precision / recall | **86% / 95%** | 75% / 90% |
| MVTec AD: decision coverage | 92% | 100% |
| MVTec AD: good images flagged as defects | **3** | 6 |

All Checkpoint 2.1 and 6.1 targets are met.

### New in this update
- **Static-image mode for real photos:** MVTec AD images from a fixed camera. The approved reference image is the only extra evidence, checked under new procedures PROC-GB-004 and PROC-CT-004.
- **40-image MVTec evaluation** with a selection fixed by seed before any run ([details](day7_mvtec_evaluation.md)).
- **Three replayable MVTec demo runs (M1–M3)** in the app, and an Evaluation tab selector.
- **Demo video extended to 3:51** with the MVTec scenes.
- **69 tests**, all passing with no API calls.

### Assets
- `inspectbot_demo.mp4`: captioned demo video (1920×1080, no audio); narration script in `docs/demo_script.md`.

### Limits
- Results are single runs, on 20 synthetic scenarios and on 2 of the 15 MVTec AD categories.
- The procedures are synthetic.
- Simulation and advisory use only.
- MVTec AD images are used under CC BY-NC-SA 4.0 (see `demo_runs/MVTEC_NOTICE.md`).
