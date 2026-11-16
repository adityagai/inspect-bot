"""The Coordinator: a CrewAI Flow that runs one inspection as a ReAct loop.

    begin ──► inspect ──► verify ──► decide ─┬─ "criteria_met" ──► conclude (definitive report)
                ▲                            ├─ "need_evidence" ──► plan_and_act ─┬─ "acted" ─┐
                │                            │                                    └─ "needs_human"
                └────────────────────────────┼────────────────────────────────────────────────┘
                                             └─ "needs_human" ──► escalate (Insufficient evidence + human review)

Agents (CrewAI, Claude) propose; the Coordinator decides. Budgets, plan guards and
conclusion guards are enforced here in code, and every robot action goes through
the MCP tools, so failures and budget use are recorded server-side.
"""

from __future__ import annotations

from typing import Any

from crewai.flow.flow import Flow, listen, or_, router, start
from pydantic import BaseModel, Field, PrivateAttr

from inspectbot.agents.prompts import GENERAL_CRITERIA_ID, inspection_prompt, planning_prompt, verification_prompt
from inspectbot.agents.runner import AgentRunner
from inspectbot.agents.schemas import InspectionOutput, PlanOutput, VerificationOutput
from inspectbot.core.models import Outcome
from inspectbot.flow.gateway import Gateway
from inspectbot.flow.guards import candidate_actions, check_conclusion, check_plan, observed_views

MAX_REJECTIONS = 2  # guard-rejected proposals per step before escalating; failed actions are bounded by the budget


class InspectionState(BaseModel):
    scenario_id: str = ""
    task_id: str = ""
    task: dict[str, Any] = Field(default_factory=dict)
    pose: str = ""
    light: str = ""
    obs_paths: dict[str, str] = Field(default_factory=dict)
    obs_meta: dict[str, dict[str, Any]] = Field(default_factory=dict)
    initial_obs: str = ""
    pending_obs: list[str] = Field(default_factory=list)
    inspections: dict[str, dict[str, Any]] = Field(default_factory=dict)
    verification: dict[str, Any] | None = None
    plans: list[dict[str, Any]] = Field(default_factory=list)
    steps: int = 0
    stop_reason: str = ""
    report: dict[str, Any] | None = None


class InspectionFlow(Flow[InspectionState]):
    _gateway: Any = PrivateAttr(default=None)
    _runner: Any = PrivateAttr(default=None)
    _max_steps: int = PrivateAttr(default=6)

    def __init__(self, gateway: Gateway, runner: AgentRunner, max_steps: int = 6, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._gateway, self._runner, self._max_steps = gateway, runner, max_steps

    @property
    def gateway(self) -> Gateway:
        return self._gateway

    @property
    def runner(self) -> AgentRunner:
        return self._runner

    @property
    def max_steps(self) -> int:
        return self._max_steps

    # ------------------------------------------------------------------ helpers

    def _say(self, sender: str, recipient: str, type: str, content: str, **kw: Any) -> None:
        self.gateway.call("post_message", task_id=self.state.task_id, sender=sender, recipient=recipient,
                          type=type, content=content[:2000], **kw)

    def _record(self) -> dict[str, Any]:
        return self.gateway.call("get_task_record", task_id=self.state.task_id)

    def _remember_obs(self, obs: dict[str, Any]) -> str:
        oid = obs["obs_id"]
        self.state.obs_paths[oid] = obs["image_path"]
        self.state.obs_meta[oid] = {k: obs.get(k) for k in ("kind", "pose", "light", "parent_obs_id", "source_id")}
        return oid

    # ------------------------------------------------------------------ steps

    @start()
    def begin(self) -> None:
        out = self.gateway.call("start_inspection", scenario_id=self.state.scenario_id)
        s = self.state
        s.task_id, s.task = out["task_id"], out["task"]
        s.pose, s.light = s.task["initial_pose"], s.task["initial_light"]
        s.initial_obs = self._remember_obs(out["initial_observation"])
        s.pending_obs = [s.initial_obs]
        self._say("coordinator", "inspection", "assignment",
                  f"Inspect {s.initial_obs} for: {s.task['goal']}", obs_refs=[s.initial_obs])

    @listen(or_(begin, "acted"))
    def inspect(self) -> None:
        s = self.state
        for oid in s.pending_obs:
            meta = s.obs_meta[oid]
            earlier = [s.initial_obs] if oid != s.initial_obs else []
            prompt = inspection_prompt(s.task, oid, meta.get("pose") or "", meta.get("light") or "", earlier)
            if meta["kind"] == "reference":
                prompt = ("This image is the APPROVED REFERENCE of a defect-free part of this category "
                          f"(source {meta.get('source_id')}). Features on it are expected.\n" + prompt)
            elif meta["kind"] == "zoom":
                prompt = f"This image is a 2x zoom crop of {meta.get('parent_obs_id')}.\n" + prompt
            images = {"current": s.obs_paths[oid]}
            if earlier:
                images["earlier"] = s.obs_paths[earlier[0]]
            result = self.runner.run("inspection", prompt, InspectionOutput, images=images)
            result.obs_id = oid
            # Agents downstream need to know how each image was taken, not just what it shows.
            s.inspections[oid] = {"obs_id": oid, "view": {"kind": meta["kind"], "pose": meta.get("pose"),
                                                         "light": meta.get("light"), "source_id": meta.get("source_id"),
                                                         "parent_obs_id": meta.get("parent_obs_id")},
                                  **{k: v for k, v in result.model_dump().items() if k != "obs_id"}}
            if result.findings:
                f = result.findings[0]
                self.gateway.call("append_finding", task_id=s.task_id, obs_ids=[oid], description=f.description,
                                  hypotheses=f.hypotheses, uncertainty=f.uncertainty)
            self._say("inspection", "verification", "finding",
                      f"{oid}: target_visible={result.target_visible}, anomaly={result.anomaly_present}; "
                      + "; ".join(f.description for f in result.findings) + (f" | {result.comparison}" if result.comparison else ""),
                      obs_refs=[oid])
        s.pending_obs = []

    @listen(inspect)
    def verify(self) -> None:
        s = self.state
        record = self._record()
        attempts = [{k: a[k] for k in ("attempt_id", "tool", "args", "status", "obs_id")} for a in record["attempts"]]
        v = self.runner.run("verification", verification_prompt(s.task, list(s.inspections.values()), attempts),
                            VerificationOutput)
        s.verification = v.model_dump(mode="json")
        self._say("verification", "coordinator", "verification",
                  f"proposed={v.proposed_outcome.value}, sufficient={v.evidence_sufficient}. {v.rationale}",
                  obs_refs=[o for o in v.cited_obs_ids if o in s.obs_paths],
                  source_ids=[GENERAL_CRITERIA_ID])

    @router(verify)
    def decide(self) -> str:
        s = self.state
        v = VerificationOutput.model_validate(s.verification)
        record = self._record()
        inspections = {k: InspectionOutput.model_validate(x) for k, x in s.inspections.items()}
        guard = check_conclusion(v, record, inspections)
        if guard.ok:
            s.stop_reason = "evidence requirements met"
            return "criteria_met"
        if v.evidence_sufficient and v.proposed_outcome != Outcome.INSUFFICIENT_EVIDENCE:
            # The verifier wanted to conclude; record why the Coordinator refused.
            self._say("coordinator", "verification", "clarification", f"Not concluding: {guard.reason}")
        if record["budget"]["actions_remaining"] == 0:
            s.stop_reason = "action budget exhausted"
            return "needs_human"
        if s.steps >= self.max_steps:
            s.stop_reason = "step limit reached"
            return "needs_human"
        return "need_evidence"

    @router("need_evidence")
    def plan_and_act(self) -> str:
        s = self.state
        feedback: str | None = None
        rejections = 0
        while rejections <= MAX_REJECTIONS:
            record = self._record()
            if record["budget"]["actions_remaining"] == 0:
                s.stop_reason = "action budget exhausted"
                return "needs_human"
            cands = candidate_actions(record, s.pose, s.light, s.task)
            if not cands:
                s.stop_reason = "every reachable view has been captured"
                return "needs_human"
            state = {"pose": s.pose, "light": s.light, "actions_remaining": record["budget"]["actions_remaining"],
                     "candidates": cands,
                     "observed_views": sorted(observed_views(record)),
                     "failed": [(a["tool"], a["args"], a["status"]) for a in record["attempts"]
                                if a["status"] != "success"]}
            plan = self.runner.run("planning", planning_prompt(s.task, state, list(s.inspections.values()),
                                                               s.verification, feedback), PlanOutput)
            guard = check_plan(plan, record, s.pose, s.light, s.task)
            entry = {**plan.model_dump(), "accepted": guard.ok, "guard": guard.reason}
            s.plans.append(entry)
            if plan.action == "stop":
                s.stop_reason = f"planner found no action that could change the conclusion: {plan.rationale}"
                return "needs_human"
            if not guard.ok:
                rejections += 1
                feedback = guard.reason
                self._say("coordinator", "planning", "clarification", f"Rejected {plan.action}: {guard.reason}")
                continue
            self._say("planning", "coordinator", "proposal",
                      f"{plan.action} {plan.tool_args()}: {plan.rationale} | expects: {plan.expected_evidence}",
                      next_step=plan.action)
            res = self.gateway.call(plan.action, task_id=s.task_id, **plan.tool_args())
            s.steps += 1
            entry["status"] = res["status"]
            self._say("coordinator", "planning", "result",
                      f"{plan.action} {plan.tool_args()} -> {res['status']}" + (f": {res['error']}" if res.get("error") else ""))
            if res["status"] == "success":
                s.pose, s.light = res["cell"]["pose"], res["cell"]["light"]
                s.pending_obs = [self._remember_obs(res["observation"])]
                return "acted"
            feedback = f"{plan.action} {plan.tool_args()} failed with '{res['status']}': {res.get('error')}"
        s.stop_reason = f"planner proposals rejected {rejections} times in a row"
        return "needs_human"

    # ------------------------------------------------------------------ outcomes

    def _submit(self, report: dict[str, Any]) -> dict[str, Any]:
        self.gateway.call("submit_report", task_id=self.state.task_id, report=report)
        self.state.report = report
        return report

    @listen("criteria_met")
    def conclude(self) -> dict[str, Any]:
        s = self.state
        v = VerificationOutput.model_validate(s.verification)
        record = self._record()
        views = sorted(observed_views(record))
        report = {
            "outcome": v.proposed_outcome.value,
            "summary": v.rationale,
            "evidence": [{"claim": v.rationale[:500], "obs_ids": [o for o in v.cited_obs_ids if o in s.obs_paths],
                          "source_ids": [GENERAL_CRITERIA_ID]}],
            "remaining_uncertainty": v.missing_evidence,
            "sources": [GENERAL_CRITERIA_ID],
            "needs_human_review": False,
            "scope_note": (f"Covers only target region {s.task['target_region']} of this part, viewed as "
                           f"{views}. Not a safety certification.") if v.proposed_outcome == Outcome.NO_DEFECT_DETECTED else None,
        }
        self._say("coordinator", "human", "report", f"{v.proposed_outcome.value}: {v.rationale}",
                  obs_refs=report["evidence"][0]["obs_ids"], source_ids=[GENERAL_CRITERIA_ID])
        return self._submit(report)

    @listen("needs_human")
    def escalate(self) -> dict[str, Any]:
        s = self.state
        v = VerificationOutput.model_validate(s.verification) if s.verification else None
        record = self._record()
        all_obs = [o["obs_id"] for o in record["observations"]]
        report = {
            "outcome": Outcome.INSUFFICIENT_EVIDENCE.value,
            "summary": f"Stopped: {s.stop_reason}. " + (v.rationale if v else ""),
            "evidence": [{"claim": "Observations reviewed before escalation", "obs_ids": all_obs,
                          "source_ids": [GENERAL_CRITERIA_ID]}] if all_obs else [],
            "remaining_uncertainty": (v.missing_evidence + v.contradictions) if v else [s.stop_reason],
            "sources": [GENERAL_CRITERIA_ID],
            "needs_human_review": True,
        }
        self._say("coordinator", "human", "escalation",
                  f"Insufficient evidence ({s.stop_reason}). Human review requested.", obs_refs=all_obs)
        return self._submit(report)


def run_inspection(scenario_id: str, gateway: Gateway, runner: AgentRunner, max_steps: int = 6) -> InspectionState:
    flow = InspectionFlow(gateway=gateway, runner=runner, max_steps=max_steps)
    flow.kickoff(inputs={"scenario_id": scenario_id})
    return flow.state
