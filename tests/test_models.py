import pytest
from pydantic import ValidationError

from inspectbot.core.models import (
    ActionAttempt,
    ActionStatus,
    EvidenceLink,
    Finding,
    Observation,
    Outcome,
    Report,
    TaskRecord,
)
from inspectbot.core.task_store import BudgetExhausted, TaskStore, check_budget, record_result


def _record() -> TaskRecord:
    return TaskRecord(scenario_id="S1", object_category="metal_bracket", goal="test")


def test_failed_attempt_cannot_carry_observation():
    with pytest.raises(ValidationError):
        ActionAttempt(tool="move_camera", status=ActionStatus.TIMEOUT, obs_id="obs_01")


def test_record_rejects_observation_from_failed_attempt():
    rec = _record()
    bad = ActionAttempt(attempt_id="act_01", tool="move_camera", status=ActionStatus.UNREACHABLE)
    obs = Observation(obs_id="obs_01", attempt_id="act_01", kind="camera", image_path="x.png")
    with pytest.raises(ValueError):
        record_result(rec, bad, obs)


def test_task_record_validator_catches_unbacked_observation():
    with pytest.raises(ValidationError):
        TaskRecord(
            scenario_id="S1", object_category="x", goal="g",
            attempts=[ActionAttempt(attempt_id="a1", tool="move_camera", status=ActionStatus.TIMEOUT)],
            observations=[Observation(obs_id="o1", attempt_id="a1", kind="camera", image_path="x.png")],
        )


def test_finding_must_cite_known_observation():
    with pytest.raises(ValidationError):
        TaskRecord(scenario_id="S1", object_category="x", goal="g",
                   findings=[Finding(obs_ids=["obs_99"], description="line")])


def test_budget_counts_failures_and_stops_at_five():
    rec = _record()
    for i in range(5):
        check_budget(rec, True)
        record_result(rec, ActionAttempt(tool="move_camera", status=ActionStatus.TIMEOUT), None)
    assert rec.budget.actions_remaining == 0
    with pytest.raises(BudgetExhausted):
        check_budget(rec, True)


def test_report_rules():
    with pytest.raises(ValidationError):  # definitive outcome without evidence
        Report(task_id="t", scenario_id="S1", outcome=Outcome.SUSPECTED_DEFECT, summary="s")
    with pytest.raises(ValidationError):  # no-defect needs a scope note
        Report(task_id="t", scenario_id="S1", outcome=Outcome.NO_DEFECT_DETECTED, summary="s",
               evidence=[EvidenceLink(claim="c", obs_ids=["obs_01"])])
    with pytest.raises(ValidationError):  # insufficient evidence must escalate
        Report(task_id="t", scenario_id="S1", outcome=Outcome.INSUFFICIENT_EVIDENCE, summary="s")
    ok = Report(task_id="t", scenario_id="S1", outcome=Outcome.INSUFFICIENT_EVIDENCE, summary="s",
                needs_human_review=True)
    assert ok.needs_human_review


def test_task_store_roundtrip(tmp_path):
    store = TaskStore(tmp_path)
    rec = _record()
    store.save(rec)
    assert store.load(rec.task_id).task_id == rec.task_id
