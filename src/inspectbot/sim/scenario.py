"""Scenario definitions for the virtual inspection cell.

A scenario plants features (cracks, shadows, seams, glare, occlusions) on one
part and scripts how the cell responds to robot actions. Ground truth is used
only for scoring: agents get `public_view()`, never the full scenario.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any, Literal, Union

import yaml
from pydantic import BaseModel, Field

from inspectbot.core.models import ActionStatus, Lighting, Outcome, Pose

Box = tuple[float, float, float, float]  # normalized x0, y0, x1, y1 on the part face


class Crack(BaseModel):
    """Real damage: dark under every light; shows a raised lip from oblique_low."""

    type: Literal["crack"] = "crack"
    points: list[tuple[float, float]] = Field(min_length=2)  # normalized polyline
    width_px: int = 3
    jitter: float = 0.0045  # jaggedness, normalized


class Mark(BaseModel):
    """Surface mark or stain: persists under every light like a crack, but has NO relief (no lip)."""

    type: Literal["mark"] = "mark"
    points: list[tuple[float, float]] = Field(min_length=2)
    width_px: int = 3
    jitter: float = 0.0045


class Seam(BaseModel):
    """Expected feature: straight, even width, present on the reference sample."""

    type: Literal["seam"] = "seam"
    orientation: Literal["vertical", "horizontal"] = "vertical"
    position: float  # normalized x (vertical) or y (horizontal)
    width_px: int = 3


class CastShadow(BaseModel):
    """A shadow from the fixture: moves with the light, absent for lights not listed."""

    type: Literal["cast_shadow"] = "cast_shadow"
    orientation: Literal["vertical", "horizontal"] = "vertical"
    positions: dict[Lighting, float]  # light -> normalized position of the band
    width_px: int = 4
    extent: tuple[float, float] = (0.05, 0.95)  # start / end along the band


class Glare(BaseModel):
    type: Literal["glare"] = "glare"
    center: tuple[float, float]
    radius: float = 0.12
    lights: list[Lighting]


Feature = Annotated[Union[Crack, Mark, Seam, CastShadow, Glare], Field(discriminator="type")]


class Occlusion(BaseModel):
    region: Box
    visible_from: list[Pose] = Field(default_factory=list)  # poses that see past it
    label: str = "clamp"


class ScriptedFailure(BaseModel):
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    status: ActionStatus
    message: str = ""
    times: int = 1  # how many matching calls fail; -1 = always


class GroundTruth(BaseModel):
    outcome: Outcome
    resolvable: bool
    notes: str = ""


class Scenario(BaseModel):
    id: str
    name: str
    category: str
    goal: str
    seed: int = 0
    initial_pose: Pose = Pose.FRONT
    initial_light: Lighting = Lighting.LEFT
    target_region: Box
    features: list[Feature] = Field(default_factory=list)
    occlusion: Occlusion | None = None
    unreachable_poses: list[Pose] = Field(default_factory=list)
    supported_lights: list[Lighting] = Field(default_factory=lambda: list(Lighting))
    reference_available: bool = True
    scripted_failures: list[ScriptedFailure] = Field(default_factory=list)
    ground_truth: GroundTruth
    demo_notes: str = ""

    def public_view(self) -> dict[str, Any]:
        """What agents may know: task definition and supported actions, no ground truth."""
        return {
            "scenario_id": self.id,
            "object_category": self.category,
            "goal": self.goal,
            "target_region": self.target_region,
            "initial_pose": self.initial_pose.value,
            "initial_light": self.initial_light.value,
            "poses": [p.value for p in Pose],
            "lights": [lt.value for lt in self.supported_lights],
        }


def scenario_dir() -> Path:
    env = os.getenv("INSPECTBOT_SCENARIO_DIR")
    if env:
        return Path(env)
    # src/inspectbot/sim/scenario.py -> repo root
    return Path(__file__).resolve().parents[3] / "scenarios"


def load_scenario(id_or_path: str | Path) -> Scenario:
    p = Path(id_or_path)
    if not p.suffix:
        matches = []
        for d in (scenario_dir(), scenario_dir() / "eval"):
            matches += sorted(d.glob(f"{id_or_path}_*.yaml")) + sorted(d.glob(f"{id_or_path}.yaml"))
        if not matches:
            raise FileNotFoundError(f"no scenario '{id_or_path}' in {scenario_dir()}")
        p = matches[0]
    return Scenario.model_validate(yaml.safe_load(p.read_text()))


def list_scenarios(include_eval: bool = False) -> list[Scenario]:
    paths = sorted(scenario_dir().glob("*.yaml"))
    if include_eval:
        paths += sorted((scenario_dir() / "eval").glob("*.yaml"))
    return [Scenario.model_validate(yaml.safe_load(p.read_text())) for p in paths]
