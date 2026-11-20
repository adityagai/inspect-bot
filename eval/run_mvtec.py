"""Static-image evaluation on MVTec AD (Checkpoint 2.1): InspectBot vs the prompt-only baseline.

    python eval/run_mvtec.py --root /path/to/MVTec-Dataset            # the fixed 40-image set
    python eval/run_mvtec.py --root /path/to/MVTec-Dataset --set warmup

The selection (eval/mvtec_selection.json) was fixed with a seed before any run. Labels come from the
dataset folder names (test/good vs test/<defect type>) and are used only for scoring.

Scoring (positive class = defect):
  precision = TP / (TP + FP); recall = TP / all defective images. An abstention ("insufficient evidence")
  on a defective image counts as a miss. Decision coverage = definitive outcomes / all images.
Targets from the proposal: precision and recall >= 85%, decision coverage >= 80%.
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

ROOT = Path(__file__).resolve().parents[1]
SEL = json.loads((ROOT / "eval" / "mvtec_selection.json").read_text())


def _quiet() -> None:
    import logging
    import warnings

    warnings.filterwarnings("ignore")
    logging.disable(logging.WARNING)
    os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")


def run_case(rel: str, root: str, runs_dir: str, modes: tuple[str, ...]) -> list[dict]:
    _quiet()
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    from inspectbot.agents.runner import CrewAIRunner
    from inspectbot.baseline.prompt_only import run_baseline_image
    from inspectbot.flow.gateway import LocalGateway
    from inspectbot.flow.inspection_flow import run_static_inspection
    from inspectbot.mcp_server.session import SessionManager

    raw_cat, _, defect_type, _name = rel.split("/")
    category = SEL["category_map"][raw_cat]
    image, ref = str(Path(root) / rel), str(Path(root) / SEL["reference"][raw_cat])
    base = {"image": rel, "category": raw_cat, "defect_type": defect_type, "label": "good" if defect_type == "good" else "defect"}
    runner, out = CrewAIRunner(), []
    if "inspectbot" in modes:
        mgr = SessionManager(runs_dir)
        t0 = time.time()
        try:
            st = run_static_inspection(image, category, LocalGateway(mgr), runner, reference_path=ref,
                                       case_id=rel.replace("/", "_").removesuffix(".png"))
            rec = mgr.get(st.task_id).record
            report = st.report or {}
            obs = {o.obs_id for o in rec.observations}
            cited = [o for e in report.get("evidence", []) for o in e["obs_ids"]]
            definitive = report.get("outcome") in ("suspected_defect", "no_defect_detected")
            out.append({**base, "mode": "inspectbot", "task_id": st.task_id, "outcome": report.get("outcome", "error"),
                        "stop_reason": st.stop_reason, "sources": report.get("sources", []),
                        "grounded": (not definitive) or (bool(cited) and all(o in obs for o in cited)
                                                         and any(s.startswith(("PROC-GB", "PROC-CT")) for s in report.get("sources", []))),
                        "used_reference": any(o.kind == "reference" for o in rec.observations),
                        "aux_calls": rec.budget.aux_calls_used, "summary": report.get("summary", "")[:400],
                        "latency_s": round(time.time() - t0, 1)})
        except Exception as e:  # noqa: BLE001 - scored as an error, never as correct
            out.append({**base, "mode": "inspectbot", "outcome": "error", "error": repr(e)[:300],
                        "grounded": False, "latency_s": round(time.time() - t0, 1)})
    if "baseline" in modes:
        t0 = time.time()
        try:
            b = run_baseline_image(image, category, runner)
            out.append({**base, "mode": "baseline", "outcome": b["outcome"], "rationale": b["rationale"][:300],
                        "latency_s": round(time.time() - t0, 1)})
        except Exception as e:  # noqa: BLE001
            out.append({**base, "mode": "baseline", "outcome": "error", "error": repr(e)[:300],
                        "latency_s": round(time.time() - t0, 1)})
    return out


def score(cases: list[dict]) -> dict:
    defect = [c for c in cases if c["label"] == "defect"]
    good = [c for c in cases if c["label"] == "good"]
    tp = sum(c["outcome"] == "suspected_defect" for c in defect)
    fp = sum(c["outcome"] == "suspected_defect" for c in good)
    fn_abstain = sum(c["outcome"] not in ("suspected_defect", "no_defect_detected") for c in defect)
    fn_cleared = sum(c["outcome"] == "no_defect_detected" for c in defect)
    definitive = [c for c in cases if c["outcome"] in ("suspected_defect", "no_defect_detected")]
    correct = sum((c["label"] == "defect" and c["outcome"] == "suspected_defect") or
                  (c["label"] == "good" and c["outcome"] == "no_defect_detected") for c in cases)
    by_type: dict[str, list[int]] = {}
    for c in defect:
        by_type.setdefault(f"{c['category']}/{c['defect_type']}", [0, 0])
        by_type[f"{c['category']}/{c['defect_type']}"][0] += c["outcome"] == "suspected_defect"
        by_type[f"{c['category']}/{c['defect_type']}"][1] += 1
    m = {
        "images": len(cases), "defective": len(defect), "good": len(good),
        "precision": round(tp / (tp + fp), 3) if tp + fp else None,
        "recall": round(tp / len(defect), 3) if defect else None,
        "decision_coverage": round(len(definitive) / len(cases), 3) if cases else None,
        "accuracy": round(correct / len(cases), 3) if cases else None,
        "tp": tp, "fp": fp, "fn_abstained": fn_abstain, "fn_cleared": fn_cleared,
        "good_cleared": sum(c["outcome"] == "no_defect_detected" for c in good),
        "good_abstained": sum(c["outcome"] not in ("suspected_defect", "no_defect_detected") for c in good),
        "recall_by_type": {k: f"{v[0]}/{v[1]}" for k, v in sorted(by_type.items())},
        "errors": sum(c["outcome"] == "error" for c in cases),
        "mean_latency_s": round(sum(c["latency_s"] for c in cases) / len(cases), 1) if cases else None,
    }
    if cases and cases[0]["mode"] == "inspectbot":
        m["grounding"] = f"{sum(bool(c.get('grounded')) for c in definitive)}/{len(definitive)}"
        m["used_reference"] = f"{sum(bool(c.get('used_reference')) for c in cases)}/{len(cases)}"
    for cat in ("bottle", "tile"):
        sub = [c for c in cases if c["category"] == cat]
        if sub and len(sub) != len(cases):
            m[f"by_category_{cat}"] = {k: v for k, v in score(sub).items() if k in ("precision", "recall", "decision_coverage", "accuracy")}
    return m


def to_markdown(stamp: str, summary: dict, cases: list[dict]) -> str:
    s, b = summary["inspectbot"], summary.get("baseline", {})
    pct = lambda v: "—" if v is None else f"{v:.0%}"  # noqa: E731
    rows = [("Precision (defect)", pct(s["precision"]), pct(b.get("precision")), "≥ 85%", s["precision"] is not None and s["precision"] >= 0.85),
            ("Recall (defect; abstain = miss)", pct(s["recall"]), pct(b.get("recall")), "≥ 85%", s["recall"] is not None and s["recall"] >= 0.85),
            ("Decision coverage", pct(s["decision_coverage"]), pct(b.get("decision_coverage")), "≥ 80%", s["decision_coverage"] is not None and s["decision_coverage"] >= 0.8),
            ("Accuracy", pct(s["accuracy"]), pct(b.get("accuracy")), "—", None)]
    lines = [f"# MVTec AD static-image evaluation ({stamp})", "",
             f"{s['images']} held-out test images ({s['defective']} defective, {s['good']} good) from the bottle and tile "
             "categories, fixed by seed before any run. Single runs; pilot results.", "",
             "| Metric | InspectBot | Prompt-only baseline | Target | Met |", "| --- | --- | --- | --- | --- |"]
    lines += [f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {'' if r[4] is None else ('✓' if r[4] else '✗')} |" for r in rows]
    lines += ["", "| Counts | InspectBot | Baseline |", "| --- | --- | --- |"]
    for k, label in (("tp", "Defects found"), ("fn_abstained", "Defects → insufficient evidence"),
                     ("fn_cleared", "Defects cleared as no defect"), ("fp", "Good images flagged"),
                     ("good_cleared", "Good images cleared"), ("good_abstained", "Good images → insufficient evidence"),
                     ("errors", "Errors"), ("mean_latency_s", "Mean latency (s)")):
        lines.append(f"| {label} | {s.get(k)} | {b.get(k, '—')} |")
    lines += ["", f"Grounding (definitive InspectBot reports citing the image and a category procedure): {s.get('grounding')}. "
              f"Reference image used: {s.get('used_reference')}.", "", "## Recall by defect type", "",
              "| Defect type | InspectBot | Baseline |", "| --- | --- | --- |"]
    for k, v in s["recall_by_type"].items():
        lines.append(f"| {k} | {v} | {b.get('recall_by_type', {}).get(k, '—')} |")
    lines += ["", "## Per image", "", "| Image | Label | InspectBot | Baseline |", "| --- | --- | --- | --- |"]
    by = {(c["image"], c["mode"]): c for c in cases}
    for img in sorted({c["image"] for c in cases}):
        i, bb = by.get((img, "inspectbot"), {}), by.get((img, "baseline"), {})
        ok = lambda c: ("✓ " if (c.get("label") == "defect") == (c.get("outcome") == "suspected_defect") and c.get("outcome") in ("suspected_defect", "no_defect_detected") else "✗ ") + c.get("outcome", "—")  # noqa: E731
        lines.append(f"| {img} | {i.get('label', bb.get('label'))} | {ok(i) if i else '—'} | {ok(bb) if bb else '—'} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    _quiet()
    sys.path.insert(0, str(ROOT / "src"))
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True, help="MVTec AD root folder (contains bottle/, tile/)")
    ap.add_argument("--set", choices=["eval", "warmup"], default="eval")
    ap.add_argument("--modes", default="inspectbot,baseline")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    modes = tuple(a.modes.split(","))
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    out_dir = ROOT / "eval" / "results" / f"mvtec-{a.set}-{stamp}"
    runs_dir = ROOT / "runs" / "mvtec" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    cases: list[dict] = []
    with ProcessPoolExecutor(max_workers=a.workers) as pool:
        futs = {pool.submit(run_case, rel, a.root, str(runs_dir), modes): rel for rel in SEL[a.set]}
        for f in as_completed(futs):
            for c in f.result():
                cases.append(c)
                hit = (c["label"] == "defect") == (c["outcome"] == "suspected_defect") and c["outcome"] in ("suspected_defect", "no_defect_detected")
                print(f"{'ok ' if hit else 'XX '}{c['image']:<36} {c['mode']:<10} {c['label']:<6} -> {c['outcome']:<22} {c['latency_s']}s", flush=True)
    summary = {"stamp": stamp, "set": a.set}
    for mode in modes:
        summary[mode] = score([c for c in cases if c["mode"] == mode])
    (out_dir / "cases.json").write_text(json.dumps(sorted(cases, key=lambda c: (c["image"], c["mode"])), indent=2))
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    if "inspectbot" in modes:
        (out_dir / "summary.md").write_text(to_markdown(stamp, summary, cases))
    print(f"\nResults: {out_dir}")
    print(json.dumps({m: {k: summary[m][k] for k in ("precision", "recall", "decision_coverage", "accuracy")} for m in modes}, indent=1))


if __name__ == "__main__":
    main()
