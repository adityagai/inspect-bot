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

from inspectbot.agents.prompts import GENERAL_CRITERIA_ID, inspection_prompt, static_inspection_prompt, planning_prompt, verification_prompt
from inspectbot.reasoning.tot import candidates_payload, run_tot
from inspectbot.agents.runner import AgentRunner
from inspectbot.agents.schemas import InspectionOutput, PlanOutput, VerificationOutput
from inspectbot.core.models import Outcome
from inspectbot.flow.gateway import Gateway
from inspectbot.flow.guards import candidate_actions, check_conclusion, check_plan, observed_views

MAX_REJECTIONS = 2  # guard-rejected proposals per step before escalating; failed actions are bounded by the budget


class InspectionState(BaseModel):
    scenario_id: str = ""
    static: dict[str, Any] | None = None  # {"image_path", "category", "reference_path", "case_id"}
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
    procedures: list[dict[str, Any]] | None = None
    retrieval: dict[str, Any] | None = None
    tot: dict[str, Any] | None = None
    plans: list[dict[str, Any]] = Field(default_factory=list)
    steps: int = 0
    stop_reason: str = ""
    report: dict[str, Any] | None = None


class InspectionFlow(Flow[InspectionState]):
    _gateway: Any = PrivateAttr(default=None)
    _runner: Any = PrivateAttr(default=None)
    _max_steps: int = PrivateAttr(default=6)
    _use_rag: bool = PrivateAttr(default=True)
    _use_tot: bool = PrivateAttr(default=True)

    def __init__(self, gateway: Gateway, runner: AgentRunner, max_steps: int = 6, use_rag: bool = True,
                 use_tot: bool = True, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._gateway, self._runner, self._max_steps = gateway, runner, max_steps
        self._use_rag, self._use_tot = use_rag, use_tot

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
        if self.state.static:
            out = self.gateway.call("start_static_inspection", **self.state.static)
        else:
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
            if s.task.get("static_image"):
                prompt = static_inspection_prompt(s.task, oid, earlier)
            else:
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

    def _retrieve(self) -> None:
        """Once per inspection: fetch procedures for the confirmed category through MCP."""
        s = self.state
        first = s.inspections.get(s.initial_obs, {})
        seen = "; ".join(f"{f['description']} ({', '.join(f['hypotheses'])})" for f in first.get("findings", []))
        query = f"{s.task['goal']} {s.task['object_category']} {seen}"
        r = self.gateway.call("retrieve_procedures", task_id=s.task_id, query=query)
        s.retrieval, s.procedures = r, r["passages"]
        rejected = "; ".join(f"{x['source_id']} ({x['reason']})" for x in r["rejected"]) or "none"
        self._say("planning", "coordinator", "result",
                  f"Retrieved {[p['source_id'] + '@' + p['version'] for p in r['passages']]}. Rejected: {rejected}."
                  + (f" MISSING: {r['missing_guidance']}" if r["missing_guidance"] else ""),
                  source_ids=[p["source_id"] for p in r["passages"]])

    @listen(inspect)
    def verify(self) -> None:
        s = self.state
        if self._use_rag and s.procedures is None:
            self._retrieve()
            if s.retrieval["missing_guidance"]:
                # No criterion to apply: do not let an agent invent one (Checkpoint 3.1).
                s.verification = VerificationOutput(
                    proposed_outcome=Outcome.INSUFFICIENT_EVIDENCE, evidence_sufficient=False,
                    missing_evidence=[s.retrieval["missing_guidance"]],
                    rationale=(f"{s.retrieval['missing_guidance']}. Similar procedures for other categories were "
                               "rejected; without an applicable criterion the line cannot be classified.")).model_dump(mode="json")
                return
        record = self._record()
        attempts = [{k: a[k] for k in ("attempt_id", "tool", "args", "status", "obs_id")} for a in record["attempts"]]
        v = self.runner.run("verification", verification_prompt(s.task, list(s.inspections.values()), attempts,
                                                                s.procedures if self._use_rag else None),
                            VerificationOutput)
        s.verification = v.model_dump(mode="json")
        self._say("verification", "coordinator", "verification",
                  f"proposed={v.proposed_outcome.value}, sufficient={v.evidence_sufficient}. {v.rationale}",
                  obs_refs=[o for o in v.cited_obs_ids if o in s.obs_paths],
                  source_ids=v.source_ids_applied or ([GENERAL_CRITERIA_ID] if s.procedures is None else []))

    @router(verify)
    def decide(self) -> str:
        s = self.state
        v = VerificationOutput.model_validate(s.verification)
        if s.retrieval and s.retrieval["missing_guidance"]:
            s.stop_reason = s.retrieval["missing_guidance"]
            return "needs_human"
        record = self._record()
        inspections = {k: InspectionOutput.model_validate(x) for k, x in s.inspections.items()}
        guard = check_conclusion(v, record, inspections, s.procedures if self._use_rag else None,
                                 s.task["object_category"])
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
            plan = self._tot_plan(record, state) if feedback is None else None
            if plan is None:
                plan = self.runner.run("planning", planning_prompt(s.task, state, list(s.inspections.values()),
                                                                   s.verification, feedback,
                                                                   s.procedures if self._use_rag else None), PlanOutput)
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

    def _competing(self) -> bool:
        latest = list(self.state.inspections.values())[-1] if self.state.inspections else {}
        hyps = {h.lower() for f in latest.get("findings", []) for h in f.get("hypotheses", [])}
        return len(hyps) >= 2

    def _tot_plan(self, record: dict[str, Any], state: dict[str, Any]) -> PlanOutput | None:
        """Bounded ToT, at most once per inspection, only when explanations compete."""
        s = self.state
        if not self._use_tot or s.tot is not None or not self._competing():
            return None
        res = run_tot(self.runner, s.task, state, record, list(s.inspections.values()), s.procedures,
                      s.pose, s.light)
        self.gateway.call("record_tot", task_id=s.task_id, candidates=candidates_payload(res),
                          selected_branch=res.selected.branch_id if res.selected else None)
        s.tot = {"selected": res.selected.branch_id if res.selected else None, "evaluations": res.evaluations,
                 "llm_calls": res.llm_calls, "stop_reason": res.stop_reason,
                 "nodes": candidates_payload(res)}
        if res.selected:
            c = res.selected
            self._say("planning", "coordinator", "proposal",
                      f"ToT selected {c.branch_id} (score {c.score:.0f}/10, {res.evaluations} candidates evaluated, "
                      f"{res.stop_reason}). Tests: {c.hypothesis}. Expects: {c.expected_evidence}",
                      source_ids=c.source_ids)
        return res.selected_step

    # ------------------------------------------------------------------ outcomes

    def _sources(self, applied: list[str] | None = None) -> list[str]:
        """Source ids with versions; all retrieved ones unless a specific applied set is given."""
        procs = self.state.procedures
        if procs is None:
            return [GENERAL_CRITERIA_ID]
        ids = applied if applied else [p["source_id"] for p in procs]
        ver = {p["source_id"]: p["version"] for p in procs}
        return [f"{i}@{ver[i]}" if i in ver else i for i in ids]

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
                          "source_ids": self._sources(v.source_ids_applied)}],
            "remaining_uncertainty": v.missing_evidence,
            "sources": self._sources(v.source_ids_applied),
            "needs_human_review": False,
            "scope_note": ((f"Covers only what is visible in this single fixed-camera image, compared with the approved "
                            f"reference. Not a safety certification.") if s.task.get("static_image") else
                           f"Covers only target region {s.task['target_region']} of this part, viewed as "
                           f"{views}. Not a safety certification.") if v.proposed_outcome == Outcome.NO_DEFECT_DETECTED else None,
        }
        self._say("coordinator", "human", "report", f"{v.proposed_outcome.value}: {v.rationale}",
                  obs_refs=report["evidence"][0]["obs_ids"], source_ids=report["sources"])
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
                          "source_ids": self._sources()}] if all_obs else [],
            "remaining_uncertainty": (v.missing_evidence + v.contradictions) if v else [s.stop_reason],
            "sources": self._sources(),
            "needs_human_review": True,
        }
        self._say("coordinator", "human", "escalation",
                  f"Insufficient evidence ({s.stop_reason}). Human review requested.", obs_refs=all_obs)
        return self._submit(report)


def run_static_inspection(image_path: str, category: str, gateway: Gateway, runner: AgentRunner,
                          reference_path: str | None = None, case_id: str | None = None,
                          max_steps: int = 4) -> InspectionState:
    """One real photo: retrieval + verification as usual; no robot moves, no ToT (nothing to branch on)."""
    flow = InspectionFlow(gateway=gateway, runner=runner, max_steps=max_steps, use_rag=True, use_tot=False)
    flow.kickoff(inputs={"static": {"image_path": image_path, "category": category,
                                    "reference_path": reference_path, "case_id": case_id}})
    return flow.state


def run_inspection(scenario_id: str, gateway: Gateway, runner: AgentRunner, max_steps: int = 6,
                   use_rag: bool = True, use_tot: bool = True) -> InspectionState:
    flow = InspectionFlow(gateway=gateway, runner=runner, max_steps=max_steps, use_rag=use_rag, use_tot=use_tot)
    flow.kickoff(inputs={"scenario_id": scenario_id})
    return flow.state
