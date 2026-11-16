"""Inspection sessions: the state behind the MCP tools.

One session = one TaskRecord + one InspectionCell + one event log. The manager
is the single place where tool calls are budget-checked, executed, recorded and
logged, so the MCP layer stays a thin adapter and tests can call this directly.

Ground truth never leaves this module: agents get Scenario.public_view() only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from inspectbot.core.events import EventLog
from inspectbot.core.models import (
    ActionAttempt,
    ActionStatus,
    AgentRole,
    Finding,
    Message,
    MessageType,
    Outcome,
    Report,
    TaskRecord,
)
from inspectbot.core.task_store import BudgetExhausted, TaskStore, check_budget, record_result
from inspectbot.sim.cell import EVIDENCE_TOOLS, InspectionCell, ToolResult
from inspectbot.sim.scenario import Scenario, load_scenario


class SessionError(ValueError):
    pass


@dataclass
class Session:
    scenario: Scenario
    record: TaskRecord
    cell: InspectionCell
    events: EventLog


class SessionManager:
    def __init__(self, runs_dir: str | Path | None = None) -> None:
        self.store = TaskStore(runs_dir or os.getenv("INSPECTBOT_RUNS_DIR", "runs"))
        self._sessions: dict[str, Session] = {}

    # ------------------------------------------------------------------ lifecycle

    def start(self, scenario_id: str, goal: str | None = None, max_actions: int = 5) -> dict[str, Any]:
        scenario = load_scenario(scenario_id)
        record = TaskRecord(scenario_id=scenario.id, object_category=scenario.category,
                            goal=goal or scenario.goal)
        record.budget.max_actions = max_actions
        run_dir = self.store.run_dir(record.task_id)
        session = Session(scenario, record, InspectionCell(scenario, run_dir / "images"),
                          EventLog(run_dir / "events.jsonl"))
        self._sessions[record.task_id] = session
        session.events.emit("task_started", task_id=record.task_id, public=scenario.public_view())
        initial = session.cell.capture_initial()
        record_result(record, initial.attempt, initial.observation)
        session.events.emit("tool_result", **initial.to_dict(), schematic_state=session.cell.state())
        self.store.save(record)
        return {
            "task_id": record.task_id,
            "task": scenario.public_view(),
            "initial_observation": initial.to_dict()["observation"],
            "budget": self.budget(record.task_id),
        }

    def get(self, task_id: str) -> Session:
        try:
            return self._sessions[task_id]
        except KeyError:
            raise SessionError(f"unknown task_id '{task_id}'; call start_inspection first") from None

    # ------------------------------------------------------------------ tools

    def run_tool(self, task_id: str, tool: str, **kwargs: Any) -> dict[str, Any]:
        s = self.get(task_id)
        counts = tool in EVIDENCE_TOOLS
        try:
            check_budget(s.record, counts)
        except BudgetExhausted as e:
            # Logged, but not executed and not charged.
            attempt = ActionAttempt(tool=tool, args=kwargs, status=ActionStatus.BUDGET_EXHAUSTED,
                                    error=str(e), counts_against_budget=False)
            s.record.attempts.append(attempt)
            result = ToolResult(attempt)
        else:
            result: ToolResult = getattr(s.cell, tool)(**kwargs)
            record_result(s.record, result.attempt, result.observation)
        out = {**result.to_dict(), "budget": self.budget(task_id), "cell": s.cell.state()}
        s.events.emit("tool_result", **result.to_dict(), schematic_state=s.cell.state())
        self.store.save(s.record)
        return out

    def observation_path(self, task_id: str, obs_id: str) -> Path:
        obs = self.get(task_id).record.observation(obs_id)
        if obs is None:
            raise SessionError(f"no observation '{obs_id}' in task {task_id} (failed attempts have none)")
        return Path(obs.image_path)

    # ------------------------------------------------------------------ shared record

    def budget(self, task_id: str) -> dict[str, int]:
        b = self.get(task_id).record.budget
        return {
            "actions_used": b.actions_used,
            "actions_remaining": b.actions_remaining,
            "aux_calls_remaining": b.aux_remaining,
            "tot_evaluations_remaining": b.max_tot_evaluations - b.tot_evaluations_used,
        }

    def summary(self, task_id: str) -> dict[str, Any]:
        r = self.get(task_id).record
        return {
            "task_id": r.task_id,
            "goal": r.goal,
            "object_category": r.object_category,
            "budget": self.budget(task_id),
            "attempts": [
                {"attempt_id": a.attempt_id, "tool": a.tool, "args": a.args, "status": a.status.value,
                 "error": a.error, "obs_id": a.obs_id}
                for a in r.attempts
            ],
            "observations": [
                {"obs_id": o.obs_id, "kind": o.kind, "pose": o.pose, "light": o.light,
                 "parent_obs_id": o.parent_obs_id, "source_id": o.source_id}
                for o in r.observations
            ],
            "findings": [f.model_dump(mode="json") for f in r.findings],
            "hypotheses": r.hypotheses,
            "open_questions": r.open_questions,
            "sources_used": r.sources_used,
            "missing_guidance": r.missing_guidance,
        }

    def add_finding(self, task_id: str, finding: dict[str, Any]) -> dict[str, Any]:
        s = self.get(task_id)
        f = Finding.model_validate(finding)
        unknown = [o for o in f.obs_ids if s.record.observation(o) is None]
        if unknown:
            raise SessionError(f"finding cites observations that do not exist: {unknown}")
        s.record.findings.append(f)
        s.events.emit("finding", **f.model_dump(mode="json"))
        self.store.save(s.record)
        return {"finding_id": f.finding_id, "recorded": True}

    def post_message(self, task_id: str, sender: str, recipient: str, type: str, content: str,
                     obs_refs: list[str] | None = None, source_ids: list[str] | None = None,
                     next_step: str | None = None) -> dict[str, Any]:
        s = self.get(task_id)
        unknown = [o for o in (obs_refs or []) if s.record.observation(o) is None]
        if unknown:
            raise SessionError(f"message cites observations that do not exist: {unknown}")
        m = Message(task_id=task_id, sender=AgentRole(sender), recipient=AgentRole(recipient),
                    type=MessageType(type), content=content, obs_refs=obs_refs or [],
                    source_ids=source_ids or [], next_step=next_step)
        s.record.messages.append(m)
        s.events.emit("message", **m.model_dump(mode="json"))
        self.store.save(s.record)
        return {"message_id": m.message_id}

    def submit_report(self, task_id: str, report: dict[str, Any]) -> dict[str, Any]:
        """Validate and store the final report. Every cited obs_id must be a real observation."""
        s = self.get(task_id)
        rep = Report.model_validate({**report, "task_id": task_id, "scenario_id": s.scenario.id})
        cited = {o for link in rep.evidence for o in link.obs_ids}
        unknown = sorted(o for o in cited if s.record.observation(o) is None)
        if unknown:
            raise SessionError(f"report cites observations that do not exist: {unknown}")
        failed = {a.attempt_id for a in s.record.failed_attempts}
        rep.failed_attempt_ids = sorted(failed)
        path = self.store.run_dir(task_id) / "report.json"
        path.write_text(rep.model_dump_json(indent=2))
        s.events.emit("report", **rep.model_dump(mode="json"))
        return {"saved": str(path), "outcome": rep.outcome.value,
                "needs_human_review": rep.needs_human_review or rep.outcome == Outcome.INSUFFICIENT_EVIDENCE}
