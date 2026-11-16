"""Coordinator Flow tests with scripted agents (no API calls) and in-process MCP tools."""

import json

from inspectbot.agents.runner import ScriptedRunner
from inspectbot.agents.schemas import (
    BaselineOutput,
    FindingDraft,
    InspectionOutput,
    PlanOutput,
    VerificationOutput,
)
from inspectbot.baseline.prompt_only import run_baseline
from inspectbot.core.models import Outcome
from inspectbot.flow.gateway import LocalGateway
from inspectbot.flow.guards import check_conclusion, check_plan
from inspectbot.flow.inspection_flow import run_inspection
from inspectbot.mcp_server.session import SessionManager

LINE = FindingDraft(description="dark vertical line", hypotheses=["crack", "cast shadow"], uncertainty="high")


def insp(visible=True, anomaly=True, findings=(LINE,)):
    return InspectionOutput(obs_id="?", target_visible=visible, anomaly_present=anomaly, findings=list(findings))


def verify(outcome, sufficient, cited=(), missing=()):
    return VerificationOutput(proposed_outcome=outcome, evidence_sufficient=sufficient,
                              cited_obs_ids=list(cited), missing_evidence=list(missing), rationale="r")


def gw(tmp_path):
    return LocalGateway(SessionManager(tmp_path))


def test_s1_shadow_resolved_with_one_lighting_change(tmp_path):
    runner = ScriptedRunner({
        "inspection": [insp(), insp(anomaly=False, findings=())],
        "verification": [verify(Outcome.INSUFFICIENT_EVIDENCE, False, missing=["does the line move with light?"]),
                         verify(Outcome.NO_DEFECT_DETECTED, True, cited=["obs_01", "obs_02"])],
        "planning": [PlanOutput(action="set_lighting", setting="top", hypotheses_addressed=["shadow", "crack"],
                                expected_evidence="shadow vanishes; crack stays")],
    })
    g = gw(tmp_path)
    s = run_inspection("S1", g, runner)
    assert s.report["outcome"] == "no_defect_detected"
    assert s.report["scope_note"] and s.stop_reason == "evidence requirements met"
    rec = g.call("get_task_record", task_id=s.task_id)
    assert rec["budget"]["actions_used"] == 1
    saved = json.loads((tmp_path / s.task_id / "report.json").read_text())
    assert saved["evidence"][0]["obs_ids"] == ["obs_01", "obs_02"]


def test_s4_failures_replanned_then_escalated(tmp_path):
    hidden = insp(visible=False, anomaly=False, findings=())
    not_yet = verify(Outcome.INSUFFICIENT_EVIDENCE, False, missing=["view behind clamp"])
    runner = ScriptedRunner({
        "inspection": [hidden] * 4,
        "verification": [not_yet] * 4,
        "planning": [
            PlanOutput(action="move_camera", pose="left_45"),      # unreachable
            PlanOutput(action="move_camera", pose="left_45"),      # rejected: already failed
            PlanOutput(action="move_camera", pose="right_45"),     # timeout
            PlanOutput(action="move_camera", pose="top"),          # success (clamp still visible)
            PlanOutput(action="move_camera", pose="oblique_low"),  # success
            PlanOutput(action="stop", rationale="no remaining pose can see past the clamp"),
        ],
    })
    g = gw(tmp_path)
    s = run_inspection("S4", g, runner)
    assert s.report["outcome"] == "insufficient_evidence" and s.report["needs_human_review"]
    rec = g.call("get_task_record", task_id=s.task_id)
    statuses = [(a["tool"], a["args"].get("pose"), a["status"]) for a in rec["attempts"]][1:]
    assert statuses == [("move_camera", "left_45", "unreachable"), ("move_camera", "right_45", "timeout"),
                        ("move_camera", "top", "success"), ("move_camera", "oblique_low", "success")]
    assert s.stop_reason.startswith("planner found no action")
    assert all(o["obs_id"] in ("obs_01", "obs_02", "obs_03") for o in rec["observations"])
    rejected = [p for p in s.plans if not p["accepted"]]
    assert rejected and "already failed" in rejected[0]["guard"]
    saved = json.loads((tmp_path / s.task_id / "report.json").read_text())
    assert set(saved["failed_attempt_ids"]) == {a["attempt_id"] for a in rec["attempts"] if a["status"] != "success"}


def test_unsupported_conclusion_is_not_reported(tmp_path):
    """Verifier claims a defect but cites a failed attempt's (nonexistent) obs: Coordinator must not conclude."""
    runner = ScriptedRunner({
        "inspection": [insp()],
        "verification": [verify(Outcome.SUSPECTED_DEFECT, True, cited=["obs_07"])],
        "planning": [PlanOutput(action="stop", rationale="nothing else to try")],
    })
    s = run_inspection("S2", gw(tmp_path), runner)
    assert s.report["outcome"] == "insufficient_evidence"


def test_budget_exhaustion_escalates(tmp_path):
    lights = ["right", "top", "diffuse"]
    poses = ["left_45", "top"]
    plans = [PlanOutput(action="set_lighting", setting=x) for x in lights] + \
            [PlanOutput(action="move_camera", pose=x) for x in poses]
    runner = ScriptedRunner({
        "inspection": [insp()] * 6,
        "verification": [verify(Outcome.INSUFFICIENT_EVIDENCE, False)] * 6,
        "planning": plans,
    })
    g = gw(tmp_path)
    s = run_inspection("S1", g, runner)
    assert s.report["outcome"] == "insufficient_evidence"
    assert s.stop_reason == "action budget exhausted"
    assert g.call("get_task_record", task_id=s.task_id)["budget"]["actions_used"] == 5


def test_plan_guard_rules(tmp_path):
    g = gw(tmp_path)
    tid = g.call("start_inspection", scenario_id="S1")["task_id"]
    rec = g.call("get_task_record", task_id=tid)
    task = {"poses": ["front", "left_45", "right_45", "top", "oblique_low"], "lights": ["left", "right", "top", "diffuse"]}
    assert not check_plan(PlanOutput(action="set_lighting", setting="left"), rec, "front", "left", task).ok  # same view
    assert not check_plan(PlanOutput(action="move_camera"), rec, "front", "left", task).ok  # missing pose
    assert check_plan(PlanOutput(action="set_lighting", setting="top"), rec, "front", "left", task).ok


def test_conclusion_guard_needs_visible_target(tmp_path):
    g = gw(tmp_path)
    tid = g.call("start_inspection", scenario_id="S4")["task_id"]
    rec = g.call("get_task_record", task_id=tid)
    v = verify(Outcome.NO_DEFECT_DETECTED, True, cited=["obs_01"])
    hidden = {"obs_01": insp(visible=False, anomaly=False, findings=())}
    assert not check_conclusion(v, rec, hidden).ok
    seen = {"obs_01": insp(visible=True, anomaly=False, findings=())}
    assert check_conclusion(v, rec, seen).ok


def test_messages_trace_every_role(tmp_path):
    runner = ScriptedRunner({
        "inspection": [insp(), insp(anomaly=False, findings=())],
        "verification": [verify(Outcome.INSUFFICIENT_EVIDENCE, False),
                         verify(Outcome.NO_DEFECT_DETECTED, True, cited=["obs_02"])],
        "planning": [PlanOutput(action="set_lighting", setting="top")],
    })
    mgr = SessionManager(tmp_path)
    s = run_inspection("S1", LocalGateway(mgr), runner)
    senders = {m.sender.value for m in mgr.get(s.task_id).record.messages}
    assert senders == {"coordinator", "inspection", "verification", "planning"}
    kinds = [e["kind"] for e in mgr.get(s.task_id).events.read()]
    assert kinds[0] == "task_started" and kinds[-1] == "report"


def test_baseline_uses_same_first_image(tmp_path):
    runner = ScriptedRunner({"baseline": [BaselineOutput(outcome=Outcome.SUSPECTED_DEFECT, rationale="looks like a crack")]})
    b = run_baseline("S1", runner, tmp_path)
    assert b["outcome"] == "suspected_defect"
    assert (tmp_path / "baseline" / "S1.json").exists()


def test_repeated_rejections_escalate(tmp_path):
    same = PlanOutput(action="set_lighting", setting="left")  # already the current view
    runner = ScriptedRunner({
        "inspection": [insp()], "verification": [verify(Outcome.INSUFFICIENT_EVIDENCE, False)],
        "planning": [same, same, same],
    })
    s = run_inspection("S1", gw(tmp_path), runner)
    assert s.report["outcome"] == "insufficient_evidence" and "rejected 3 times" in s.stop_reason


def test_candidate_actions_exclude_seen_and_failed(tmp_path):
    from inspectbot.flow.guards import candidate_actions
    g = gw(tmp_path)
    tid = g.call("start_inspection", scenario_id="S4")["task_id"]
    g.call("move_camera", task_id=tid, pose="left_45")  # unreachable
    rec = g.call("get_task_record", task_id=tid)
    task = {"poses": ["front", "left_45", "right_45", "top", "oblique_low"],
            "lights": ["left", "right", "top", "diffuse"], "object_category": "metal_bracket"}
    c = candidate_actions(rec, "front", "diffuse", task)
    assert not any("diffuse')" in x and "set_lighting" in x for x in c)  # current view
    assert not any("left_45" in x for x in c)  # failed
    assert any(x.startswith("get_reference") for x in c)
