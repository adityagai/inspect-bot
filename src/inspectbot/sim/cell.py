"""The virtual inspection cell: the robot's only interface to the world.

Every tool call returns a ToolResult holding an ActionAttempt and, only when the
call succeeded, an Observation with a saved image. Failures (unreachable pose,
timeout, unsupported light, bad arguments) are reported with a status and leave
the cell state unchanged. Day 2 wraps these methods as MCP tools.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

from inspectbot.core.models import ActionAttempt, ActionStatus, Lighting, Observation, Pose
from inspectbot.sim.renderer import render_reference, render_view
from inspectbot.sim.scenario import Scenario

# Robot actions that gather new evidence count against the 5-action budget.
EVIDENCE_TOOLS = {"move_camera", "set_lighting"}
# Image processing and reference lookups are logged and capped separately.
AUX_TOOLS = {"zoom_region", "get_reference"}


@dataclass
class ToolResult:
    attempt: ActionAttempt
    observation: Observation | None = None
    image: Image.Image | None = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe summary for agents / MCP. Images travel as file paths, never bytes."""
        out: dict[str, Any] = {
            "attempt_id": self.attempt.attempt_id,
            "tool": self.attempt.tool,
            "args": self.attempt.args,
            "status": self.attempt.status.value,
            "error": self.attempt.error,
            "counts_against_budget": self.attempt.counts_against_budget,
        }
        if self.observation is not None:
            out["observation"] = self.observation.model_dump(mode="json", exclude={"created_at"})
        return out


class InspectionCell:
    def __init__(self, scenario: Scenario, output_dir: str | Path) -> None:
        self.scenario = scenario
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.pose: Pose = scenario.initial_pose
        self.light: Lighting = scenario.initial_light
        self._n_attempts = 0
        self._n_obs = 0
        self._failures_used: dict[int, int] = {}
        self._images: dict[str, Path] = {}

    # ------------------------------------------------------------------ helpers

    def _attempt(self, tool: str, args: dict[str, Any], status: ActionStatus, error: str | None = None,
                 obs_id: str | None = None) -> ActionAttempt:
        self._n_attempts += 1
        return ActionAttempt(
            attempt_id=f"act_{self._n_attempts:02d}",
            tool=tool,
            args=args,
            status=status,
            error=error,
            obs_id=obs_id,
            counts_against_budget=tool in EVIDENCE_TOOLS,
        )

    def _fail(self, tool: str, args: dict[str, Any], status: ActionStatus, error: str) -> ToolResult:
        return ToolResult(self._attempt(tool, args, status, error))

    def _scripted_failure(self, tool: str, args: dict[str, Any]) -> tuple[ActionStatus, str] | None:
        for i, sf in enumerate(self.scenario.scripted_failures):
            if sf.tool != tool or any(args.get(k) != v for k, v in sf.args.items()):
                continue
            used = self._failures_used.get(i, 0)
            if sf.times == -1 or used < sf.times:
                self._failures_used[i] = used + 1
                return sf.status, sf.message or f"{tool} failed ({sf.status.value})"
        return None

    def _save(self, tool: str, args: dict[str, Any], image: Image.Image, kind: str, **obs_kw: Any) -> ToolResult:
        self._n_obs += 1
        obs_id = f"obs_{self._n_obs:02d}"
        path = self.output_dir / f"{obs_id}.png"
        image.save(path)
        self._images[obs_id] = path
        attempt = self._attempt(tool, args, ActionStatus.SUCCESS, obs_id=obs_id)
        obs = Observation(obs_id=obs_id, attempt_id=attempt.attempt_id, kind=kind, image_path=str(path), **obs_kw)
        return ToolResult(attempt, obs, image)

    def _capture(self, tool: str, args: dict[str, Any]) -> ToolResult:
        img = render_view(self.scenario, self.pose, self.light)
        return self._save(tool, args, img, "camera", pose=self.pose, light=self.light)

    # ------------------------------------------------------------------ tools

    def capture_initial(self) -> ToolResult:
        """The first image the user's task starts from. Not an agent action."""
        return self._capture("initial_capture", {"pose": self.pose.value, "light": self.light.value})

    def move_camera(self, pose: str) -> ToolResult:
        args = {"pose": pose}
        try:
            target = Pose(pose)
        except ValueError:
            return self._fail("move_camera", args, ActionStatus.INVALID_ARGS,
                              f"unknown pose '{pose}'; valid: {[p.value for p in Pose]}")
        if target in self.scenario.unreachable_poses:
            return self._fail("move_camera", args, ActionStatus.UNREACHABLE,
                              f"pose '{pose}' is unreachable: arm would collide with the fixture")
        failure = self._scripted_failure("move_camera", args)
        if failure:
            return self._fail("move_camera", args, *failure)
        self.pose = target
        return self._capture("move_camera", args)

    def set_lighting(self, setting: str) -> ToolResult:
        args = {"setting": setting}
        try:
            target = Lighting(setting)
        except ValueError:
            return self._fail("set_lighting", args, ActionStatus.INVALID_ARGS,
                              f"unknown light setting '{setting}'; valid: {[lt.value for lt in Lighting]}")
        if target not in self.scenario.supported_lights:
            return self._fail("set_lighting", args, ActionStatus.UNSUPPORTED,
                              f"light setting '{setting}' is not available in this cell")
        failure = self._scripted_failure("set_lighting", args)
        if failure:
            return self._fail("set_lighting", args, *failure)
        self.light = target
        return self._capture("set_lighting", args)

    def zoom_region(self, obs_id: str, bbox: list[int] | tuple[int, int, int, int]) -> ToolResult:
        """Crop a region of an existing observation and upscale 2x. Cannot add detail."""
        args = {"obs_id": obs_id, "bbox": list(bbox)}
        parent = self._images.get(obs_id)
        if parent is None:
            return self._fail("zoom_region", args, ActionStatus.NOT_FOUND, f"no observation '{obs_id}'")
        img = Image.open(parent)
        try:
            x0, y0, x1, y1 = (int(v) for v in bbox)
        except (TypeError, ValueError):
            return self._fail("zoom_region", args, ActionStatus.INVALID_ARGS, "bbox must be [x0, y0, x1, y1]")
        if not (0 <= x0 < x1 <= img.width and 0 <= y0 < y1 <= img.height) or (x1 - x0) < 16 or (y1 - y0) < 16:
            return self._fail("zoom_region", args, ActionStatus.INVALID_ARGS,
                              f"bbox must lie inside {img.width}x{img.height} and be at least 16 px each side")
        crop = img.crop((x0, y0, x1, y1))
        crop = crop.resize((crop.width * 2, crop.height * 2), Image.LANCZOS)
        return self._save("zoom_region", args, crop, "zoom", parent_obs_id=obs_id, bbox=(x0, y0, x1, y1))

    def get_reference(self, category: str) -> ToolResult:
        """Golden sample of a defect-free part of this category, if one exists."""
        args = {"category": category}
        if category != self.scenario.category or not self.scenario.reference_available:
            return self._fail("get_reference", args, ActionStatus.NOT_FOUND,
                              f"no approved reference image for category '{category}'")
        img = render_reference(self.scenario)
        return self._save("get_reference", args, img, "reference", pose=Pose.FRONT, light=Lighting.DIFFUSE,
                          source_id=f"REF-{category.upper()}-v1")

    def state(self) -> dict[str, Any]:
        return {"pose": self.pose.value, "light": self.light.value, "observations": sorted(self._images)}
