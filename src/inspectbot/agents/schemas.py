"""Structured outputs for each agent (CrewAI `response_format`)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from inspectbot.core.models import Outcome


class FindingDraft(BaseModel):
    description: str = Field(description="What is visible, in neutral terms (e.g. 'dark vertical line'), not a verdict")
    hypotheses: list[str] = Field(default_factory=list,
                                  description="Plausible explanations, e.g. crack, cast shadow, seam, scratch")
    uncertainty: Literal["low", "medium", "high"] = "high"


class InspectionOutput(BaseModel):
    obs_id: str = Field(description="The observation being analysed")
    target_visible: bool = Field(description="Is the target region clearly visible (not hidden, not blurred)?")
    anomaly_present: bool = Field(description="Is a line or anomaly visible in the target region?")
    findings: list[FindingDraft] = Field(default_factory=list)
    surface_discontinuity: bool = Field(default=False, description=(
        "True only if a raised/broken edge, bright lip or visible gap runs along the line (a step in the surface)"))
    matches_reference: bool | None = Field(default=None, description=(
        "Only when the current image is the approved reference: does the line seen in the earlier image also "
        "appear on the reference at the same place? Otherwise null"))
    comparison: str = Field(default="", description="How this view differs from the earlier observation, if any")


class PlanOutput(BaseModel):
    action: Literal["move_camera", "set_lighting", "zoom_region", "get_reference", "stop"]
    pose: Literal["front", "left_45", "right_45", "top", "oblique_low"] | None = None
    setting: Literal["left", "right", "top", "diffuse"] | None = None
    obs_id: str | None = None
    bbox: list[int] | None = Field(default=None, description="[x0, y0, x1, y1] for zoom_region")
    category: str | None = None
    hypotheses_addressed: list[str] = Field(default_factory=list)
    expected_evidence: str = Field(default="", description="What each hypothesis predicts this action will show")
    rationale: str = ""

    @field_validator("pose", "setting", "obs_id", "bbox", "category", mode="before")
    @classmethod
    def _none_strings(cls, v):  # models sometimes write the string "None" for an empty field
        return None if isinstance(v, str) and v.strip().lower() in ("", "none", "null", "n/a") else v

    def tool_args(self) -> dict:
        return {
            "move_camera": {"pose": self.pose},
            "set_lighting": {"setting": self.setting},
            "zoom_region": {"obs_id": self.obs_id, "bbox": self.bbox},
            "get_reference": {"category": self.category},
            "stop": {},
        }[self.action]


class VerificationOutput(BaseModel):
    proposed_outcome: Outcome
    evidence_sufficient: bool = Field(description="True only if the cited observations meet the criteria")
    cited_obs_ids: list[str] = Field(default_factory=list,
                                     description="Observations that support the outcome; never failed attempts")
    criteria_checked: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    source_ids_applied: list[str] = Field(default_factory=list, description=(
        "source_ids of the retrieved procedures whose criteria decided the outcome"))
    inapplicable_source_ids: list[str] = Field(default_factory=list, description=(
        "Retrieved passages you judged NOT applicable (wrong object, conditions not met)"))
    contradictions: list[str] = Field(default_factory=list, description=(
        "Only direct conflicts between observations that would change the outcome (e.g. the line fixed in one "
        "same-pose pair but moving in another). Leave EMPTY when a criterion is met; residual alternative "
        "hypotheses go in missing_evidence, not here"))
    rationale: str = ""


class BaselineOutput(BaseModel):
    outcome: Outcome
    rationale: str


class ToTDraft(BaseModel):
    """One candidate inspection plan step proposed during Tree-of-Thought search."""
    hypothesis: str = Field(description="The explanation this step is designed to test")
    step: PlanOutput
    expected_evidence: str = Field(description="What each competing hypothesis predicts this step will show (a prediction)")
    source_ids: list[str] = Field(default_factory=list, description="Retrieved procedures that motivate this step")


class ToTProposal(BaseModel):
    candidates: list[ToTDraft] = Field(default_factory=list, max_length=3)


class ToTScore(BaseModel):
    branch_id: str
    evidence_support: int = Field(ge=0, le=3, description="0-3: grounded in observed evidence")
    distinguishing: int = Field(ge=0, le=3, description="0-3: expected ability to separate the competing explanations")
    procedure_compliance: int = Field(ge=0, le=2, description="0-2: follows the applicable retrieved procedure")
    feasibility_cost: int = Field(ge=0, le=2, description="0-2: feasible and cheap (2 = one cheap action)")
    note: str = ""


class ToTScores(BaseModel):
    scores: list[ToTScore]
