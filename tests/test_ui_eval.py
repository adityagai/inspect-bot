"""Day 5: replay reconstruction for the app, evaluation metrics, and the evaluation scenario set."""

import sys
from pathlib import Path

import numpy as np

from inspectbot.agents.runner import ScriptedRunner
from inspectbot.agents.schemas import InspectionOutput, PlanOutput, VerificationOutput
from inspectbot.core.models import Lighting, Outcome, Pose
from inspectbot.flow.gateway import LocalGateway
from inspectbot.flow.inspection_flow import run_inspection
from inspectbot.mcp_server.session import SessionManager
from inspectbot.sim.renderer import part_to_image_xy, render_view
from inspectbot.sim.scenario import list_scenarios, load_scenario
from inspectbot.ui.replay import list_runs, run_label, tot_dot, view_at

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))
from metrics import check_targets, relative_reduction, summarize  # noqa: E402


def _s4_run(tmp_path):
    hidden = InspectionOutput(obs_id="?", target_visible=False, anomaly_present=False)
    runner = ScriptedRunner({
        "inspection": [hidden, hidden],
        "verification": [VerificationOutput(proposed_outcome=Outcome.INSUFFICIENT_EVIDENCE, evidence_sufficient=False)] * 2,
        "planning": [PlanOutput(action="move_camera", pose="left_45"), PlanOutput(action="move_camera", pose="top"),
                     PlanOutput(action="stop", rationale="nothing sees past the clamp")],
    })
    mgr = SessionManager(tmp_path)
    s = run_inspection("S4", LocalGateway(mgr), runner, use_tot=False)
    return tmp_path / s.task_id


# ------------------------------------------------------------------ replay


def test_replay_final_and_intermediate_views(tmp_path):
    run = _s4_run(tmp_path)
    final = view_at(run)
    assert final.report["outcome"] == "insufficient_evidence"
    assert final.actions_used == 2 and len(final.observations) == 2  # failed move: no observation
    assert final.retrieval and final.retrieval["passages"]
    first = view_at(run, 2)
    assert first.task["scenario_id"] == "S4" and first.report is None and first.pose == "front"
    # find the step right after the unreachable move: the schematic must mark it
    for k in range(1, final.total_steps + 1):
        v = view_at(run, k)
        if v.attempts and v.attempts[-1]["status"] == "unreachable":
            assert v.failed_pose == "left_45" and "failed: left_45" in v.schematic_svg
            break
    else:
        raise AssertionError("unreachable attempt not replayed")
    assert final.image_path(final.current_obs).exists()
    assert run_label(run).startswith("S4 · insufficient_evidence")


def test_list_runs_puts_first_root_first(tmp_path):
    a, b = tmp_path / "demo", tmp_path / "runs"
    for root, names in ((a, ["S2", "S1"]), (b, ["t1"])):
        for n in names:
            (root / n).mkdir(parents=True)
            (root / n / "events.jsonl").write_text("")
    assert [p.name for p in list_runs(a, b)] == ["S1", "S2", "t1"]


def test_tot_dot_marks_selected_and_pruned():
    tot = {"selected_branch": "b1.1", "candidates": [
        {"branch_id": "b1.1", "parent_id": None, "depth": 1, "hypothesis": "shadow", "score": 10,
         "proposed_action": {"action": "set_lighting", "setting": "top"}, "pruned": False},
        {"branch_id": "b1.2", "parent_id": None, "depth": 1, "hypothesis": "crack", "score": 3,
         "proposed_action": {"action": "move_camera", "pose": "oblique_low"}, "pruned": True, "prune_reason": "score 3 < 5"}]}
    dot = tot_dot(tot)
    assert "set_lighting(top)" in dot and "#2fb37a" in dot and "score 3 < 5" in dot and '"root" -> "b1.2"' in dot


# ------------------------------------------------------------------ metrics


def _case(sid, truth, out, resolvable=True, defect=False, **kw):
    base = dict(scenario_id=sid, truth=truth, outcome=out, resolvable=resolvable, defect_present=defect,
                actions_used=kw.get("a", 1), grounded=kw.get("g", True), failed_cited=0,
                failed_attempts=kw.get("f", 0), latency_s=1.0)
    return base


def test_metrics_counts():
    cases = [
        _case("A", "no_defect_detected", "no_defect_detected"),
        _case("B", "suspected_defect", "suspected_defect", defect=True, a=2),
        _case("C", "insufficient_evidence", "insufficient_evidence", resolvable=False, defect=True, a=5, f=2),
        _case("D", "insufficient_evidence", "no_defect_detected", resolvable=False, defect=True),  # false clear
    ]
    m = summarize(cases)
    assert m["accuracy"]["n"] == 3 and m["false_clear"]["n"] == 1 and m["incorrect_definitive"]["n"] == 1
    assert m["escalation_recall"] == {"n": 1, "of": 2, "rate": 0.5}
    assert m["mean_actions_resolvable"] == 1.5 and m["budget_violations"] == 0
    met = {t["metric"]: t["met"] for t in check_targets(m)}
    assert met["false_clear"] is False and met["budget_violations"] is True


def test_relative_reduction():
    sys_m = {"incorrect_definitive": {"n": 1, "of": 20, "rate": 0.05}}
    base_m = {"incorrect_definitive": {"n": 8, "of": 20, "rate": 0.4}}
    assert relative_reduction(sys_m, base_m)["relative_reduction"] == 0.875
    zero = {"incorrect_definitive": {"n": 0, "of": 20, "rate": 0.0}}
    assert "point_difference" in relative_reduction(sys_m, zero)


# ------------------------------------------------------------------ evaluation scenarios


def test_eval_set_is_balanced():
    scns = list_scenarios(include_eval=True)
    assert len(scns) == 20 and len({s.id for s in scns}) == 20
    assert sum(s.ground_truth.resolvable for s in scns) == 10
    assert all(s.ground_truth.outcome == Outcome.INSUFFICIENT_EVIDENCE for s in scns if not s.ground_truth.resolvable)
    assert [s.id for s in list_scenarios()] == ["S1", "S2", "S3", "S4", "S5"]  # demo set unchanged


def test_mark_has_no_lip_but_crack_does():
    """oblique_low reveals a bright lip along a crack; a flat surface mark shows none."""
    def brightest_near_line(sid, x):
        img = np.asarray(render_view(load_scenario(sid), Pose.OBLIQUE_LOW, Lighting.LEFT).convert("L"), np.float32)
        x0, y0 = map(int, part_to_image_xy(Pose.OBLIQUE_LOW, x - 0.08, 0.35))
        x1, y1 = map(int, part_to_image_xy(Pose.OBLIQUE_LOW, x + 0.08, 0.65))
        region = img[y0:y1, x0:x1]
        return region.max() - np.median(region)
    assert brightest_near_line("V07", 0.54) > brightest_near_line("V13", 0.47) + 15
