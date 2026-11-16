"""Rebuild what the UI shows at any step of a run, from its events.jsonl.

Used by the Streamlit app for both replay (step slider) and live mode (latest step).
Pure Python, so it is unit-tested without Streamlit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from inspectbot.core.models import Lighting, Pose
from inspectbot.sim.schematic import render_schematic

AGENT_COLORS = {"coordinator": "#7c8aa5", "planning": "#4f8cff", "inspection": "#2fb37a",
                "verification": "#e0a030", "human": "#d0607a", "system": "#888888"}


@dataclass
class RunView:
    run_dir: Path
    step: int
    total_steps: int
    task: dict[str, Any] = field(default_factory=dict)
    task_id: str = ""
    pose: str = "front"
    light: str = "left"
    failed_pose: str | None = None
    current_obs: dict[str, Any] | None = None
    observations: list[dict[str, Any]] = field(default_factory=list)
    attempts: list[dict[str, Any]] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    retrieval: dict[str, Any] | None = None
    tot: dict[str, Any] | None = None
    report: dict[str, Any] | None = None
    actions_used: int = 0
    last_event: dict[str, Any] | None = None

    @property
    def schematic_svg(self) -> str:
        return render_schematic(Pose(self.pose), Lighting(self.light),
                                failed_pose=Pose(self.failed_pose) if self.failed_pose else None,
                                category=self.task.get("object_category", ""), step=self.actions_used)

    def image_path(self, obs: dict[str, Any]) -> Path:
        """Images are stored next to the run; resolve paths even if the run folder was moved."""
        p = Path(obs["image_path"])
        return p if p.exists() else self.run_dir / "images" / p.name


def read_events(run_dir: str | Path) -> list[dict[str, Any]]:
    path = Path(run_dir) / "events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def view_at(run_dir: str | Path, step: int | None = None) -> RunView:
    run_dir = Path(run_dir)
    events = read_events(run_dir)
    n = len(events)
    step = n if step is None else max(1, min(step, n))
    v = RunView(run_dir=run_dir, step=step, total_steps=n)
    for e in events[:step]:
        v.last_event = e
        k = e["kind"]
        if k == "task_started":
            v.task, v.task_id = e["public"], e["task_id"]
            v.pose, v.light = v.task["initial_pose"], v.task["initial_light"]
        elif k == "tool_result":
            v.attempts.append({x: e.get(x) for x in ("attempt_id", "tool", "args", "status", "error",
                                                     "counts_against_budget")})
            cell = e.get("schematic_state") or {}
            v.pose, v.light = cell.get("pose", v.pose), cell.get("light", v.light)
            if e.get("counts_against_budget") and e["status"] != "budget_exhausted":
                v.actions_used += 1
            if e["status"] == "success" and e.get("observation"):
                v.observations.append(e["observation"])
                v.current_obs = e["observation"]
                v.failed_pose = None
            else:
                v.failed_pose = e["args"].get("pose") if e["tool"] == "move_camera" else None
        elif k == "message":
            v.messages.append(e)
        elif k == "retrieval":
            v.retrieval = e
        elif k == "tot":
            v.tot = e
        elif k == "report":
            v.report = e
    return v


def tot_dot(tot: dict[str, Any]) -> str:
    """Graphviz DOT for the ToT tree: kept nodes solid, pruned grey, selected highlighted."""
    lines = ['digraph tot {', 'rankdir=LR; bgcolor="transparent"; size="10,4"; nodesep=0.25;',
             'node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=10];',
             'root [label="confirmed\\nstate", fillcolor="#2b2f38", fontcolor="white"];']
    for c in tot.get("candidates", []):
        a = c["proposed_action"]
        arg = {"move_camera": a.get("pose"), "set_lighting": a.get("setting"),
               "get_reference": a.get("category"), "zoom_region": a.get("obs_id")}.get(a.get("action"), "")
        score = "-" if c.get("score") is None else f"{c['score']:.0f}/10"
        hyp = c["hypothesis"].replace('"', "'")[:46]
        note = f"\\n✂ {c['prune_reason'][:40]}" if c.get("pruned") else ""
        selected = c["branch_id"] == tot.get("selected_branch")
        fill = "#2fb37a" if selected else ("#d9d9d9" if c.get("pruned") else "#cfe0ff")
        font = "white" if selected else "black"
        label = f"{c['branch_id']}  {a.get('action')}({arg})\\nscore {score}\\n{hyp}{note}"
        lines.append(f'"{c["branch_id"]}" [label="{label}", fillcolor="{fill}", fontcolor="{font}"];')
        lines.append(f'"{c.get("parent_id") or "root"}" -> "{c["branch_id"]}";')
    lines.append("}")
    return "\n".join(lines)


def list_runs(*roots: str | Path) -> list[Path]:
    """Run folders (containing events.jsonl): earlier roots first (demo runs by name), then newest first."""
    out: list[Path] = []
    for i, root in enumerate(roots):
        root = Path(root)
        if not root.exists():
            continue
        found = sorted({p.parent for p in root.rglob("events.jsonl")} - set(out),
                       key=(lambda p: p.name) if i == 0 else (lambda p: -p.stat().st_mtime))
        out += found
    return out


def run_label(run_dir: Path) -> str:
    events = read_events(run_dir)
    start = next((e for e in events if e["kind"] == "task_started"), None)
    report = next((e for e in events if e["kind"] == "report"), None)
    sid = start["public"]["scenario_id"] if start else "?"
    outcome = report["outcome"] if report else "running"
    return f"{sid} · {outcome} · {run_dir.name}"
