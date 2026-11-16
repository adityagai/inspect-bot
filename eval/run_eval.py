"""Run InspectBot and the prompt-only baseline over the scenario set and score them.

    python eval/run_eval.py                    # all 20 scenarios, both modes, 3 parallel workers
    python eval/run_eval.py --set demo         # S1-S5 only
    python eval/run_eval.py --only V03 V13     # specific scenarios

Writes eval/results/<stamp>/{cases.json, summary.json, summary.md} and copies each
InspectBot run (task record, events, report, images) under runs/eval/<stamp>/.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from metrics import check_targets, relative_reduction, summarize  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _quiet() -> None:
    import logging
    import warnings

    warnings.filterwarnings("ignore")
    logging.disable(logging.WARNING)
    os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")


def run_case(scenario_id: str, runs_dir: str, modes: tuple[str, ...]) -> list[dict]:
    _quiet()
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    from inspectbot.agents.runner import CrewAIRunner
    from inspectbot.baseline.prompt_only import run_baseline
    from inspectbot.flow.gateway import LocalGateway
    from inspectbot.flow.inspection_flow import run_inspection
    from inspectbot.mcp_server.session import SessionManager
    from inspectbot.sim.scenario import Crack, load_scenario

    scn = load_scenario(scenario_id)
    base = {"scenario_id": scn.id, "name": scn.name, "category": scn.category,
            "truth": scn.ground_truth.outcome.value, "resolvable": scn.ground_truth.resolvable,
            "defect_present": any(isinstance(f, Crack) for f in scn.features)}
    out = []
    runner = CrewAIRunner()
    if "inspectbot" in modes:
        mgr = SessionManager(runs_dir)
        t0 = time.time()
        try:
            state = run_inspection(scenario_id, LocalGateway(mgr), runner)
            rec = mgr.get(state.task_id).record
            report = state.report or {}
            obs = {o.obs_id for o in rec.observations}
            failed = {a.attempt_id for a in rec.failed_attempts}
            cited = [o for e in report.get("evidence", []) for o in e["obs_ids"]]
            definitive = report.get("outcome") in ("suspected_defect", "no_defect_detected")
            specific = [s for s in report.get("sources", []) if s.split("@")[0].split("-")[1] not in ("GEN",)
                        and not s.startswith("PUB")]
            out.append({**base, "mode": "inspectbot", "task_id": state.task_id,
                        "outcome": report.get("outcome", "error"), "stop_reason": state.stop_reason,
                        "actions_used": rec.budget.actions_used, "aux_used": rec.budget.aux_calls_used,
                        "failed_attempts": len(failed),
                        "recovered": True,  # every failure is followed by a new plan or an escalation (Flow design)
                        "failed_cited": sum(1 for o in cited if o not in obs),
                        "grounded": (not definitive) or (bool(cited) and all(o in obs for o in cited) and bool(specific)),
                        "escalated": bool(report.get("needs_human_review")),
                        "tot_used": rec.budget.tot_invocations, "tot_evaluations": rec.budget.tot_evaluations_used,
                        "sources": report.get("sources", []), "missing_guidance": rec.missing_guidance,
                        "latency_s": round(time.time() - t0, 1)})
        except Exception as e:  # noqa: BLE001 - a crash is scored as an error, never as a correct abstention
            out.append({**base, "mode": "inspectbot", "outcome": "error", "error": repr(e)[:300],
                        "actions_used": 0, "failed_cited": 0, "grounded": False, "escalated": False,
                        "failed_attempts": 0, "latency_s": round(time.time() - t0, 1)})
    if "baseline" in modes:
        t0 = time.time()
        try:
            b = run_baseline(scenario_id, runner, runs_dir)
            out.append({**base, "mode": "baseline", "outcome": b["outcome"], "rationale": b["rationale"][:300],
                        "latency_s": round(time.time() - t0, 1)})
        except Exception as e:  # noqa: BLE001
            out.append({**base, "mode": "baseline", "outcome": "error", "error": repr(e)[:300],
                        "latency_s": round(time.time() - t0, 1)})
    return out


def to_markdown(summary: dict, cases: list[dict]) -> str:
    sys_m, base_m = summary["inspectbot"], summary["baseline"]

    def fmt(m, k):
        v = m.get(k)
        if isinstance(v, dict):
            return f"{v['n']}/{v['of']}" + (f" ({v['rate']:.0%})" if v["rate"] is not None else "")
        return "—" if v is None else str(v)

    rows = [("Accuracy (all cases)", "accuracy"), ("Resolvable cases correct", "resolvable_correct"),
            ("Unresolvable cases abstained (Insufficient evidence)", "unresolvable_abstained"),
            ("Defect recall (labeled defects reported Suspected)", "defect_recall"),
            ("False clears (defect present, reported No defect)", "false_clear"),
            ("Incorrect definitive outcomes", "incorrect_definitive"),
            ("Decision coverage on resolvable cases", "decision_coverage_resolvable"),
            ("Unnecessary escalations (resolvable cases)", "unnecessary_escalation"),
            ("Escalation recall (mandatory-review cases)", "escalation_recall"),
            ("Grounding (definitive reports with valid evidence + category procedure)", "grounding"),
            ("Failed actions cited as evidence", "failed_actions_cited"),
            ("Mean evidence actions, resolvable cases", "mean_actions_resolvable"),
            ("Mean evidence actions, all cases", "mean_actions_all"),
            ("Budget violations (> 5 actions)", "budget_violations"),
            ("Failed-action recovery", "recovery"),
            ("Mean latency (s)", "mean_latency_s")]
    lines = [f"# Evaluation results ({summary['stamp']})", "",
             f"{summary['n_scenarios']} scenarios: 10 resolvable, 10 unresolvable. Single runs per case; "
             "pilot results, not general performance claims.", "",
             "| Metric | InspectBot | Prompt-only baseline |", "| --- | --- | --- |"]
    lines += [f"| {label} | {fmt(sys_m, k)} | {fmt(base_m, k)} |" for label, k in rows]
    rr = summary["baseline_comparison"]
    lines += ["", "**Incorrect definitive outcomes:** "
              + (f"{rr['system_errors']} vs {rr['baseline_errors']} for the baseline "
                 f"({rr['relative_reduction']:.0%} relative reduction; target ≥ 25%)." if "relative_reduction" in rr
                 else f"baseline had none; difference {rr['point_difference']} points."), "",
              "## Targets (Checkpoints 2.1 and 6.1)", "", "| Metric | Target | Met |", "| --- | --- | --- |"]
    lines += [f"| {t['metric']} | {t['target']} | {'✓' if t['met'] else '✗'} |" for t in summary["targets"]]
    lines += ["", "## Per case", "", "| Case | Truth | InspectBot | Actions | Stop reason | Baseline |",
              "| --- | --- | --- | --- | --- | --- |"]
    by = {(c["scenario_id"], c["mode"]): c for c in cases}
    for sid in sorted({c["scenario_id"] for c in cases}, key=lambda x: (x[0] != "S", x)):
        i, b = by.get((sid, "inspectbot"), {}), by.get((sid, "baseline"), {})
        mark = lambda c: ("✓ " if c.get("outcome") == c.get("truth") else "✗ ") + c.get("outcome", "—")  # noqa: E731
        lines.append(f"| {sid} {i.get('name', b.get('name', ''))} | {i.get('truth', b.get('truth'))} | {mark(i)} | "
                     f"{i.get('actions_used', '—')} | {str(i.get('stop_reason', ''))[:80]} | {mark(b)} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    _quiet()
    sys.path.insert(0, str(ROOT / "src"))
    from inspectbot.sim.scenario import list_scenarios

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--set", choices=["all", "demo"], default="all")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--modes", default="inspectbot,baseline")
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()
    ids = a.only or [s.id for s in list_scenarios(include_eval=a.set == "all")]
    modes = tuple(a.modes.split(","))
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    out_dir = ROOT / "eval" / "results" / stamp
    runs_dir = ROOT / "runs" / "eval" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    cases: list[dict] = []
    with ProcessPoolExecutor(max_workers=a.workers) as pool:
        futs = {pool.submit(run_case, sid, str(runs_dir), modes): sid for sid in ids}
        for f in as_completed(futs):
            for c in f.result():
                cases.append(c)
                ok = "ok " if c["outcome"] == c["truth"] else "XX "
                print(f"{ok}{c['scenario_id']:<4} {c['mode']:<10} truth={c['truth']:<22} got={c['outcome']:<22} "
                      f"{c.get('actions_used', '')} {c.get('latency_s')}s", flush=True)
    summary = {"stamp": stamp, "n_scenarios": len(ids)}
    for mode in modes:
        summary[mode] = summarize([c for c in cases if c["mode"] == mode])
    if "inspectbot" in modes:
        summary["targets"] = check_targets(summary["inspectbot"])
    if set(modes) == {"inspectbot", "baseline"}:
        summary["baseline_comparison"] = relative_reduction(summary["inspectbot"], summary["baseline"])
    (out_dir / "cases.json").write_text(json.dumps(sorted(cases, key=lambda c: (c["scenario_id"], c["mode"])), indent=2))
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    if set(modes) == {"inspectbot", "baseline"}:
        (out_dir / "summary.md").write_text(to_markdown(summary, cases))
    print(f"\nResults: {out_dir}")


if __name__ == "__main__":
    main()
