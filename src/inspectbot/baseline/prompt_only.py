"""Prompt-only baseline: the same vision model, the same first image, one call, no tools.

This is what InspectBot is compared against (Checkpoint 2.1): identical initial
observation, instructions and model, but no evidence gathering, retrieval or
verification.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from inspectbot.agents.prompts import baseline_prompt
from inspectbot.agents.runner import AgentRunner
from inspectbot.agents.schemas import BaselineOutput
from inspectbot.sim.renderer import render_view
from inspectbot.sim.scenario import load_scenario


def run_baseline(scenario_id: str, runner: AgentRunner, runs_dir: str | Path | None = None) -> dict:
    scn = load_scenario(scenario_id)
    out_dir = Path(runs_dir or os.getenv("INSPECTBOT_RUNS_DIR", "runs")) / "baseline"
    out_dir.mkdir(parents=True, exist_ok=True)
    image = out_dir / f"{scn.id}_initial.png"
    render_view(scn, scn.initial_pose, scn.initial_light).save(image)  # identical to InspectBot's obs_01
    result = runner.run("baseline", baseline_prompt(scn.public_view()), BaselineOutput,
                        images={"current": str(image)})
    record = {"scenario_id": scn.id, "mode": "baseline", "outcome": result.outcome.value,
              "rationale": result.rationale, "image": str(image)}
    (out_dir / f"{scn.id}.json").write_text(json.dumps(record, indent=2))
    return record


def run_baseline_image(image_path: str, category: str, runner: AgentRunner) -> dict:
    """Same prompt-only baseline on a real static image (e.g. MVTec AD)."""
    label = category.replace("_", " ")
    task = {"goal": f"Inspect this {label} for defects. Single static image from a fixed camera.",
            "object_category": category}
    result = runner.run("baseline", baseline_prompt(task), BaselineOutput, images={"current": str(image_path)})
    return {"image": str(image_path), "mode": "baseline", "outcome": result.outcome.value,
            "rationale": result.rationale}
