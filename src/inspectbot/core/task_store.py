"""JSON-file task store: one directory per inspection run.

The store is the only writer of TaskRecord evidence lists, so the invariants
(failed attempts never become observations, budget counted on every attempt)
are enforced in one place. Day 2 exposes it through the MCP server.
"""

from __future__ import annotations

from pathlib import Path

from inspectbot.core.models import ActionAttempt, ActionStatus, Observation, TaskRecord


class BudgetExhausted(RuntimeError):
    pass


class TaskStore:
    def __init__(self, root: str | Path = "runs") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def run_dir(self, task_id: str) -> Path:
        d = self.root / task_id
        (d / "images").mkdir(parents=True, exist_ok=True)
        return d

    def save(self, record: TaskRecord) -> Path:
        path = self.run_dir(record.task_id) / "task_record.json"
        path.write_text(record.model_dump_json(indent=2))
        return path

    def load(self, task_id: str) -> TaskRecord:
        path = self.root / task_id / "task_record.json"
        return TaskRecord.model_validate_json(path.read_text())


def check_budget(record: TaskRecord, counts_against_budget: bool) -> None:
    """Raise before a tool runs if it would exceed the inspection budget."""
    b = record.budget
    if counts_against_budget and b.actions_remaining == 0:
        raise BudgetExhausted(f"action budget of {b.max_actions} used")
    if not counts_against_budget and b.aux_remaining == 0:
        raise BudgetExhausted(f"auxiliary-call cap of {b.max_aux_calls} used")


def record_result(record: TaskRecord, attempt: ActionAttempt, observation: Observation | None) -> None:
    """Append an attempt (and its observation, if any) and charge the budget."""
    if observation is not None:
        if attempt.status != ActionStatus.SUCCESS:
            raise ValueError("refusing to store an observation from a failed attempt")
        if observation.attempt_id != attempt.attempt_id:
            raise ValueError("observation does not belong to this attempt")
    if attempt.counts_against_budget:
        record.budget.actions_used += 1
    elif attempt.tool != "initial_capture":
        record.budget.aux_calls_used += 1
    record.attempts.append(attempt)
    if observation is not None:
        record.observations.append(observation)
