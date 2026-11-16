"""Deterministic checks the Coordinator applies around the LLM agents.

These are code, not prompts: an agent can propose anything, but only actions
that pass these checks are executed, and only conclusions that pass them are
reported as definitive.
"""

from __future__ import annotations

from dataclasses import dataclass

from inspectbot.agents.schemas import InspectionOutput, PlanOutput, VerificationOutput
from inspectbot.core.models import Outcome


@dataclass
class GuardResult:
    ok: bool
    reason: str = ""


def observed_views(record: dict) -> set[tuple[str, str]]:
    return {(o["pose"], o["light"]) for o in record["observations"] if o["kind"] == "camera"}


def failed_actions(record: dict) -> set[tuple[str, str]]:
    return {(a["tool"], str(sorted(a["args"].items()))) for a in record["attempts"]
            if a["status"] not in ("success",)}


def candidate_actions(record: dict, pose: str, light: str, task: dict) -> list[str]:
    """Every single action that would produce a view not captured yet (failed ones excluded)."""
    seen, failed = observed_views(record), failed_actions(record)
    out = []
    for lt in task["lights"]:
        if (pose, lt) not in seen and ("set_lighting", str(sorted({"setting": lt}.items()))) not in failed:
            out.append(f"set_lighting(setting='{lt}')  -> new view {pose}/{lt}")
    for p in task["poses"]:
        if (p, light) not in seen and ("move_camera", str(sorted({"pose": p}.items()))) not in failed:
            out.append(f"move_camera(pose='{p}')  -> new view {p}/{light}")
    if not any(o["kind"] == "reference" for o in record["observations"]):
        out.append(f"get_reference(category='{task['object_category']}')  -> approved defect-free reference image")
    return out


def check_plan(plan: PlanOutput, record: dict, pose: str, light: str, task: dict) -> GuardResult:
    if plan.action == "stop":
        return GuardResult(True)
    args = plan.tool_args()
    if any(v is None for v in args.values()):
        return GuardResult(False, f"{plan.action} is missing arguments: {args}")
    if (plan.action, str(sorted(args.items()))) in failed_actions(record):
        return GuardResult(False, f"{plan.action} {args} already failed; choose a different action")
    if plan.action == "move_camera":
        if plan.pose not in task["poses"]:
            return GuardResult(False, f"pose '{plan.pose}' is not available")
        if (plan.pose, light) in observed_views(record):
            return GuardResult(False, f"view {plan.pose}/{light} was already captured")
    if plan.action == "set_lighting":
        if plan.setting not in task["lights"]:
            return GuardResult(False, f"light '{plan.setting}' is not available")
        if (pose, plan.setting) in observed_views(record):
            return GuardResult(False, f"view {pose}/{plan.setting} was already captured")
    if plan.action == "zoom_region" and not any(o["obs_id"] == plan.obs_id for o in record["observations"]):
        return GuardResult(False, f"cannot zoom into unknown observation {plan.obs_id}")
    return GuardResult(True)


def check_conclusion(v: VerificationOutput, record: dict, inspections: dict[str, InspectionOutput]) -> GuardResult:
    """May this verification be reported as a definitive outcome?"""
    if v.proposed_outcome == Outcome.INSUFFICIENT_EVIDENCE:
        return GuardResult(False, "verification proposes insufficient evidence")
    if not v.evidence_sufficient:
        return GuardResult(False, "verification says evidence is not yet sufficient")
    real = {o["obs_id"] for o in record["observations"]}
    cited = [o for o in v.cited_obs_ids if o in real]
    if not cited:
        return GuardResult(False, "no valid observation cited")
    if bad := [o for o in v.cited_obs_ids if o not in real]:
        return GuardResult(False, f"cites observations that do not exist: {bad}")
    if v.contradictions:
        return GuardResult(False, f"unresolved contradictions: {v.contradictions}")
    if not any(inspections.get(o) and inspections[o].target_visible for o in cited):
        return GuardResult(False, "target region is not visible in any cited observation")
    return GuardResult(True)
