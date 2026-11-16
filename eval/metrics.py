"""Evaluation metrics (Checkpoints 2.1 and 6.1), computed from per-case records.

A case record is a dict with at least:
    scenario_id, mode ('inspectbot' | 'baseline'), truth (outcome), resolvable (bool),
    defect_present (bool: a crack is physically there, visible or not), outcome,
and for InspectBot also: actions_used, grounded (bool), failed_cited (int), escalated (bool), latency_s.
"""

from __future__ import annotations

from statistics import mean
from typing import Any

DEFINITIVE = {"suspected_defect", "no_defect_detected"}


def _ratio(n: int, d: int) -> dict[str, Any]:
    return {"n": n, "of": d, "rate": round(n / d, 3) if d else None}


def summarize(cases: list[dict[str, Any]]) -> dict[str, Any]:
    res = [c for c in cases if c["resolvable"]]
    unres = [c for c in cases if not c["resolvable"]]
    labeled_defect = [c for c in cases if c["truth"] == "suspected_defect"]
    present_defect = [c for c in cases if c["defect_present"]]
    definitive = [c for c in cases if c["outcome"] in DEFINITIVE]
    wrong_definitive = [c for c in definitive if c["outcome"] != c["truth"]]
    out: dict[str, Any] = {
        "cases": len(cases),
        "accuracy": _ratio(sum(c["outcome"] == c["truth"] for c in cases), len(cases)),
        "resolvable_correct": _ratio(sum(c["outcome"] == c["truth"] for c in res), len(res)),
        "unresolvable_abstained": _ratio(sum(c["outcome"] == "insufficient_evidence" for c in unres), len(unres)),
        "defect_recall": _ratio(sum(c["outcome"] == "suspected_defect" for c in labeled_defect), len(labeled_defect)),
        "false_clear": _ratio(sum(c["outcome"] == "no_defect_detected" for c in present_defect), len(present_defect)),
        "incorrect_definitive": _ratio(len(wrong_definitive), len(cases)),
        "decision_coverage_resolvable": _ratio(sum(c["outcome"] in DEFINITIVE for c in res), len(res)),
        "unnecessary_escalation": _ratio(sum(c["outcome"] == "insufficient_evidence" for c in res), len(res)),
        "escalation_recall": _ratio(sum(c["outcome"] == "insufficient_evidence" for c in unres), len(unres)),
        "wrong_cases": sorted(c["scenario_id"] for c in cases if c["outcome"] != c["truth"]),
    }
    if cases and "actions_used" in cases[0]:
        out["grounding"] = _ratio(sum(bool(c["grounded"]) for c in definitive), len(definitive))
        out["failed_actions_cited"] = sum(c["failed_cited"] for c in cases)
        out["mean_actions_resolvable"] = round(mean(c["actions_used"] for c in res), 2) if res else None
        out["mean_actions_all"] = round(mean(c["actions_used"] for c in cases), 2)
        out["budget_violations"] = sum(c["actions_used"] > 5 for c in cases)
        out["recovery"] = _ratio(sum(c.get("recovered", True) for c in cases if c.get("failed_attempts", 0)),
                                 sum(1 for c in cases if c.get("failed_attempts", 0)))
    if cases and "latency_s" in cases[0]:
        out["mean_latency_s"] = round(mean(c["latency_s"] for c in cases), 1)
    return out


def relative_reduction(system: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    """Relative drop in incorrect definitive outcomes per case (2.1). Falls back to points if baseline has 0."""
    s, b = system["incorrect_definitive"], baseline["incorrect_definitive"]
    if not b["n"]:
        return {"baseline_errors": 0, "system_errors": s["n"],
                "point_difference": round((s["rate"] or 0) - (b["rate"] or 0), 3)}
    return {"baseline_errors": b["n"], "system_errors": s["n"],
            "relative_reduction": round(1 - (s["rate"] / b["rate"]), 3)}


TARGETS = [
    ("resolvable_correct", ">= 8/10", lambda m: m["resolvable_correct"]["n"] >= 0.8 * m["resolvable_correct"]["of"]),
    ("unresolvable_abstained", ">= 8/10", lambda m: m["unresolvable_abstained"]["n"] >= 0.8 * m["unresolvable_abstained"]["of"]),
    ("false_clear", "0", lambda m: m["false_clear"]["n"] == 0),
    ("escalation_recall", "100%", lambda m: m["escalation_recall"]["n"] == m["escalation_recall"]["of"]),
    ("grounding", "100%", lambda m: m["grounding"]["n"] == m["grounding"]["of"]),
    ("failed_actions_cited", "0", lambda m: m["failed_actions_cited"] == 0),
    ("mean_actions_resolvable", "<= 3", lambda m: (m["mean_actions_resolvable"] or 0) <= 3),
    ("budget_violations", "0", lambda m: m["budget_violations"] == 0),
]


def check_targets(m: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"metric": k, "target": t, "met": bool(f(m))} for k, t, f in TARGETS]
