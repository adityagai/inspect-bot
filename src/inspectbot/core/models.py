"""Shared data models for InspectBot.

Design rules carried over from the checkpoints:
- Attempted actions and acquired observations are stored separately, so a failed
  tool call can never become evidence (Checkpoint 2.1).
- Predictions (ToT expected evidence) live on Candidates, never as Observations
  (Checkpoint 4.1).
- Definitive outcomes must link to recorded observations (Checkpoints 2.1, 6.1).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


def _now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# --------------------------------------------------------------------------- enums


class Outcome(str, Enum):
    SUSPECTED_DEFECT = "suspected_defect"
    NO_DEFECT_DETECTED = "no_defect_detected"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class Pose(str, Enum):
    FRONT = "front"
    LEFT_45 = "left_45"
    RIGHT_45 = "right_45"
    TOP = "top"
    OBLIQUE_LOW = "oblique_low"


class Lighting(str, Enum):
    LEFT = "left"
    RIGHT = "right"
    TOP = "top"
    DIFFUSE = "diffuse"


class ActionStatus(str, Enum):
    SUCCESS = "success"
    UNREACHABLE = "unreachable"  # pose blocked (collision / workspace limit)
    TIMEOUT = "timeout"
    UNSUPPORTED = "unsupported"  # setting not available in this cell
    INVALID_ARGS = "invalid_args"
    NOT_FOUND = "not_found"
    BUDGET_EXHAUSTED = "budget_exhausted"


class AgentRole(str, Enum):
    COORDINATOR = "coordinator"
    PLANNING = "planning"
    INSPECTION = "inspection"
    VERIFICATION = "verification"
    HUMAN = "human"
    SYSTEM = "system"


class MessageType(str, Enum):
    ASSIGNMENT = "assignment"
    RESULT = "result"
    FINDING = "finding"
    PROPOSAL = "proposal"
    VERIFICATION = "verification"
    CLARIFICATION = "clarification"
    ESCALATION = "escalation"
    REPORT = "report"


# --------------------------------------------------------------------------- evidence


class ActionAttempt(BaseModel):
    """Every tool call, successful or not. Failed attempts carry no obs_id."""

    attempt_id: str = Field(default_factory=lambda: new_id("act"))
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    status: ActionStatus
    error: str | None = None
    counts_against_budget: bool = True
    obs_id: str | None = None
    created_at: datetime = Field(default_factory=_now)

    @model_validator(mode="after")
    def _obs_only_on_success(self) -> ActionAttempt:
        if self.status != ActionStatus.SUCCESS and self.obs_id is not None:
            raise ValueError("a failed attempt cannot produce an observation")
        return self

    @property
    def succeeded(self) -> bool:
        return self.status == ActionStatus.SUCCESS


class Observation(BaseModel):
    """An image actually acquired from the cell (camera view, zoom crop or reference)."""

    obs_id: str
    attempt_id: str
    kind: Literal["camera", "zoom", "reference"]
    pose: Pose | None = None
    light: Lighting | None = None
    image_path: str
    parent_obs_id: str | None = None  # zoom crops point at the image they came from
    bbox: tuple[int, int, int, int] | None = None  # pixel box in the parent image
    source_id: str | None = None  # reference images carry a source identifier
    created_at: datetime = Field(default_factory=_now)


class Finding(BaseModel):
    finding_id: str = Field(default_factory=lambda: new_id("fnd"))
    obs_ids: list[str] = Field(min_length=1)
    description: str
    region: tuple[float, float, float, float] | None = None  # normalized x0, y0, x1, y1
    hypotheses: list[str] = Field(default_factory=list)
    uncertainty: Literal["low", "medium", "high"] = "high"
    source_ids: list[str] = Field(default_factory=list)


class Candidate(BaseModel):
    """A Tree-of-Thought node. expected_evidence is a prediction, never an observation."""

    branch_id: str
    parent_id: str | None = None
    depth: int = Field(ge=0, le=3)
    hypothesis: str
    proposed_action: dict[str, Any]  # {"tool": ..., "args": {...}}
    expected_evidence: str
    source_ids: list[str] = Field(default_factory=list)
    unresolved_constraints: list[str] = Field(default_factory=list)
    score: float | None = Field(default=None, ge=0, le=10)
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    pruned: bool = False
    prune_reason: str | None = None


class Message(BaseModel):
    message_id: str = Field(default_factory=lambda: new_id("msg"))
    task_id: str
    sender: AgentRole
    recipient: AgentRole
    type: MessageType
    content: str
    obs_refs: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    action_status: ActionStatus | None = None
    next_step: str | None = None
    created_at: datetime = Field(default_factory=_now)


# --------------------------------------------------------------------------- task state


class Budget(BaseModel):
    max_actions: int = 5  # evidence-gathering actions, failures included
    actions_used: int = 0
    max_aux_calls: int = 6  # zoom / reference lookups: free of the action budget but capped
    aux_calls_used: int = 0
    max_tot_invocations: int = 1
    tot_invocations: int = 0
    max_tot_evaluations: int = 15
    tot_evaluations_used: int = 0

    @property
    def actions_remaining(self) -> int:
        return max(0, self.max_actions - self.actions_used)

    @property
    def aux_remaining(self) -> int:
        return max(0, self.max_aux_calls - self.aux_calls_used)


class TaskRecord(BaseModel):
    """Short-term memory for one inspection (one object)."""

    task_id: str = Field(default_factory=lambda: new_id("task"))
    scenario_id: str
    object_category: str
    goal: str
    criteria: list[str] = Field(default_factory=list)
    budget: Budget = Field(default_factory=Budget)

    attempts: list[ActionAttempt] = Field(default_factory=list)
    observations: list[Observation] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    candidates: list[Candidate] = Field(default_factory=list)
    messages: list[Message] = Field(default_factory=list)

    hypotheses: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    sources_used: list[str] = Field(default_factory=list)
    missing_guidance: list[str] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=_now)

    def observation(self, obs_id: str) -> Observation | None:
        return next((o for o in self.observations if o.obs_id == obs_id), None)

    def attempt(self, attempt_id: str) -> ActionAttempt | None:
        return next((a for a in self.attempts if a.attempt_id == attempt_id), None)

    @property
    def failed_attempts(self) -> list[ActionAttempt]:
        return [a for a in self.attempts if not a.succeeded]

    @model_validator(mode="after")
    def _evidence_integrity(self) -> TaskRecord:
        ok_attempts = {a.attempt_id for a in self.attempts if a.succeeded}
        for obs in self.observations:
            if obs.attempt_id not in ok_attempts:
                raise ValueError(f"observation {obs.obs_id} is not backed by a successful attempt")
        obs_ids = {o.obs_id for o in self.observations}
        for f in self.findings:
            missing = set(f.obs_ids) - obs_ids
            if missing:
                raise ValueError(f"finding {f.finding_id} cites unknown observations {sorted(missing)}")
        return self


# --------------------------------------------------------------------------- output


class EvidenceLink(BaseModel):
    claim: str
    obs_ids: list[str] = Field(min_length=1)
    source_ids: list[str] = Field(default_factory=list)


class Report(BaseModel):
    task_id: str
    scenario_id: str
    outcome: Outcome
    summary: str
    evidence: list[EvidenceLink] = Field(default_factory=list)
    remaining_uncertainty: list[str] = Field(default_factory=list)
    failed_attempt_ids: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    needs_human_review: bool = False
    scope_note: str | None = None

    @model_validator(mode="after")
    def _outcome_rules(self) -> Report:
        if self.outcome != Outcome.INSUFFICIENT_EVIDENCE and not self.evidence:
            raise ValueError("a definitive outcome must link to recorded observations")
        if self.outcome == Outcome.NO_DEFECT_DETECTED and not self.scope_note:
            raise ValueError("'No defect detected' must state the inspected scope (it is not a certification)")
        if self.outcome == Outcome.INSUFFICIENT_EVIDENCE and not self.needs_human_review:
            raise ValueError("'Insufficient evidence' always requests human review")
        return self
