"""Bounded Tree-of-Thought planning (Checkpoint 4.1).

Invoked by the Coordinator at most once per inspection, when the evidence has
competing explanations. Planning generates candidate steps; Verification scores
them; this module (code, not a prompt) applies validity checks, pruning, beam
search and tie-breaks, and returns the first action of the best branch.

    root (confirmed state)
      depth 1: up to 3 candidates            -> keep best 2 (beam)
      depth 2: up to 3 children per kept node -> keep best 2
      depth 3: up to 3 children per kept node -> keep best 2
    hard cap: 3 + 6 + 6 = 15 candidate evaluations; early stop when a candidate scores >= 8.

Expected evidence on a candidate is a prediction and is never stored as an observation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from inspectbot.agents.prompts import tot_expand_prompt, tot_score_prompt
from inspectbot.agents.runner import AgentRunner
from inspectbot.agents.schemas import PlanOutput, ToTProposal, ToTScores
from inspectbot.core.models import Candidate
from inspectbot.flow.guards import check_plan

CHILDREN, BEAM, MAX_DEPTH, MAX_EVALS = 3, 2, 3, 15
PRUNE_BELOW, SELECT_AT = 5, 8


@dataclass
class ToTResult:
    selected: Candidate | None
    nodes: list[Candidate] = field(default_factory=list)
    evaluations: int = 0
    llm_calls: int = 0
    stop_reason: str = ""

    @property
    def selected_step(self) -> PlanOutput | None:
        return PlanOutput.model_validate(self.selected.proposed_action) if self.selected else None


def _key(c: Candidate) -> tuple:
    """Rank: score, then observed-evidence support, then information gain, then low cost, then branch id."""
    b = c.score_breakdown
    return (-(c.score or 0), -b.get("evidence_support", 0), -b.get("distinguishing", 0),
            -b.get("feasibility_cost", 0), c.branch_id)


def _step_sig(step: dict) -> str:
    return f"{step.get('action')}:{step.get('pose') or step.get('setting') or step.get('category') or step.get('obs_id')}"


def run_tot(runner: AgentRunner, task: dict, state: dict, record: dict, inspections: list[dict],
            procedures: list[dict] | None, pose: str, light: str) -> ToTResult:
    res = ToTResult(selected=None)
    known_sources = {p["source_id"] for p in (procedures or [])}
    by_id: dict[str, Candidate] = {}
    frontier: list[Candidate | None] = [None]  # None = root

    for depth in range(1, MAX_DEPTH + 1):
        children: list[Candidate] = []
        for parent in frontier:
            if res.evaluations >= MAX_EVALS:
                break
            path = _path(parent, by_id)
            proposal = runner.run("planning", tot_expand_prompt(task, state, inspections, procedures,
                                                                [{"step": c.proposed_action, "expects": c.expected_evidence}
                                                                 for c in path]), ToTProposal)
            res.llm_calls += 1
            for i, draft in enumerate(proposal.candidates[:CHILDREN]):
                if res.evaluations >= MAX_EVALS:
                    break
                bid = f"b{depth}.{len(children) + 1}"
                node = Candidate(branch_id=bid, parent_id=parent.branch_id if parent else None, depth=depth,
                                 hypothesis=draft.hypothesis, proposed_action=draft.step.model_dump(),
                                 expected_evidence=draft.expected_evidence, source_ids=draft.source_ids)
                res.evaluations += 1
                reason = _invalid(draft.step, depth, path, record, pose, light, task, known_sources, draft.source_ids)
                if reason:
                    node.pruned, node.prune_reason, node.score = True, reason, 0
                children.append(node)
                by_id[bid] = node

        valid = [c for c in children if not c.pruned]
        if valid:
            scores = runner.run("verification", tot_score_prompt(
                task, inspections, procedures,
                [{"branch_id": c.branch_id, "hypothesis": c.hypothesis, "step": c.proposed_action,
                  "expected_evidence": c.expected_evidence, "path": [p.proposed_action for p in _path(by_id.get(c.parent_id), by_id)]}
                 for c in valid]), ToTScores)
            res.llm_calls += 1
            got = {s.branch_id: s for s in scores.scores}
            for c in valid:
                s = got.get(c.branch_id)
                if s is None:
                    c.pruned, c.prune_reason, c.score = True, "not scored", 0
                    continue
                c.score_breakdown = {"evidence_support": s.evidence_support, "distinguishing": s.distinguishing,
                                     "procedure_compliance": s.procedure_compliance, "feasibility_cost": s.feasibility_cost}
                c.score = float(sum(c.score_breakdown.values()))
                if c.score < PRUNE_BELOW:
                    c.pruned, c.prune_reason = True, f"score {c.score:.0f} < {PRUNE_BELOW}"
        res.nodes.extend(children)
        kept = sorted([c for c in children if not c.pruned], key=_key)[:BEAM]
        for c in children:
            if not c.pruned and c not in kept:
                c.pruned, c.prune_reason = True, "outside beam"
        if not kept:
            res.stop_reason = f"no eligible candidates at depth {depth}"
            break
        if (kept[0].score or 0) >= SELECT_AT:
            res.stop_reason = f"selection criteria met at depth {depth} (score {kept[0].score:.0f})"
            frontier = kept
            break
        if res.evaluations >= MAX_EVALS:
            res.stop_reason = "evaluation budget exhausted"
            frontier = kept
            break
        frontier = kept
        res.stop_reason = f"depth limit {MAX_DEPTH}"

    # Best surviving leaf -> its depth-1 ancestor is the action to execute now.
    survivors = [c for c in res.nodes if not c.pruned]
    if survivors:
        best = sorted(survivors, key=lambda c: (-c.depth, *_key(c)))[0]
        while best.parent_id:
            best = by_id[best.parent_id]
        res.selected = best
    return res


def _path(node: Candidate | None, by_id: dict[str, Candidate]) -> list[Candidate]:
    out: list[Candidate] = []
    while node is not None:
        out.append(node)
        node = by_id.get(node.parent_id) if node.parent_id else None
    return list(reversed(out))


def _invalid(step: PlanOutput, depth: int, path: list[Candidate], record: dict, pose: str, light: str,
             task: dict, known_sources: set[str], source_ids: list[str]) -> str | None:
    """Deterministic validity checks (applied before any scoring)."""
    if step.action == "stop":
        return "stop is not a plan step"
    if unknown := [s for s in source_ids if s not in known_sources]:
        return f"cites procedures that were not retrieved: {unknown}"
    if depth == 1:
        g = check_plan(step, record, pose, light, task)
        return None if g.ok else g.reason
    if any(_step_sig(c.proposed_action) == _step_sig(step.model_dump()) for c in path):
        return "repeats a step already on this branch"
    if any(v is None for v in step.tool_args().values()):
        return f"{step.action} is missing arguments"
    return None


def candidates_payload(result: ToTResult) -> list[dict[str, Any]]:
    return [c.model_dump(mode="json") for c in result.nodes]
