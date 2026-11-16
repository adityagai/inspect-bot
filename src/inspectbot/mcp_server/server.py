"""InspectBot MCP server: the robot cell and shared task record as MCP tools.

Run it as one long-lived process that every agent connects to, so all agents
share the same sessions:

    python -m inspectbot.mcp_server.server                  # streamable HTTP on 127.0.0.1:8765/mcp
    python -m inspectbot.mcp_server.server --transport stdio

Storage and search are implemented behind MCP (JSON task store, cell renderer);
MCP itself only provides the tool interface (Checkpoint 4.1).
"""

from __future__ import annotations

import argparse
import os
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP, Image
from pydantic import ValidationError
from mcp.server.fastmcp.exceptions import ToolError

from inspectbot.mcp_server.session import SessionError, SessionManager

# Tool groups, used by agents' static tool filters (allow-lists) on the client side.
ROBOT_TOOLS = ["move_camera", "set_lighting"]
IMAGE_TOOLS = ["zoom_region", "get_reference", "get_observation_image"]
RECORD_TOOLS = ["get_task_record", "append_finding", "post_message", "submit_report"]
LIFECYCLE_TOOLS = ["start_inspection"]
KNOWLEDGE_TOOLS = ["retrieve_procedures", "record_tot"]

Pose = Literal["front", "left_45", "right_45", "top", "oblique_low"]
Light = Literal["left", "right", "top", "diffuse"]
Role = Literal["coordinator", "planning", "inspection", "verification", "human", "system"]
MsgType = Literal["assignment", "result", "finding", "proposal", "verification", "clarification",
                  "escalation", "report"]


def build_server(manager: SessionManager | None = None, host: str = "127.0.0.1", port: int = 8765) -> FastMCP:
    sessions = manager or SessionManager()
    mcp = FastMCP(
        "inspectbot",
        instructions=(
            "Tools for a simulated robotic visual-inspection cell. Each inspection has a task_id. "
            "move_camera and set_lighting gather new evidence and count against a 5-action budget "
            "(failures count too). A failed action returns a status and NO observation: never cite it "
            "as evidence. Images are referenced by obs_id."
        ),
        host=host,
        port=port,
    )

    def _call(fn, *args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except (SessionError, ValidationError) as e:
            raise ToolError(str(e)) from e

    # ---------------------------------------------------------------- lifecycle

    @mcp.tool()
    def start_inspection(scenario_id: str, goal: str | None = None) -> dict[str, Any]:
        """Start an inspection of one object. Returns task_id, the task definition (category, goal,
        target region, available poses and lights), the initial observation and the budget."""
        return _call(sessions.start, scenario_id, goal)

    # ---------------------------------------------------------------- robot actions (budgeted)

    @mcp.tool()
    def move_camera(task_id: str, pose: Pose) -> dict[str, Any]:
        """Move the robot camera to a pose and capture an image. Counts against the action budget.
        Returns status; on success an observation with obs_id. Unreachable or timed-out moves leave
        the camera where it was and produce no observation."""
        return _call(sessions.run_tool, task_id, "move_camera", pose=pose)

    @mcp.tool()
    def set_lighting(task_id: str, setting: Light) -> dict[str, Any]:
        """Change the inspection light and capture an image from the current pose. Counts against
        the action budget. Shadows move or vanish with lighting; surface damage does not."""
        return _call(sessions.run_tool, task_id, "set_lighting", setting=setting)

    # ---------------------------------------------------------------- image tools (capped, not budgeted)

    @mcp.tool()
    def zoom_region(task_id: str, obs_id: str, bbox: list[int]) -> dict[str, Any]:
        """Crop [x0, y0, x1, y1] (pixels, min 16 px each side) from an existing observation and
        upscale 2x. Enlargement cannot recover detail that was not captured."""
        return _call(sessions.run_tool, task_id, "zoom_region", obs_id=obs_id, bbox=bbox)

    @mcp.tool()
    def get_reference(task_id: str, category: str) -> dict[str, Any]:
        """Fetch the approved defect-free reference image for an object category, if one exists.
        Expected features (e.g. seams) appear on the reference."""
        return _call(sessions.run_tool, task_id, "get_reference", category=category)

    @mcp.tool()
    def get_observation_image(task_id: str, obs_id: str) -> Image:
        """Return the image for an obs_id so a vision model can look at it."""
        path = _call(sessions.observation_path, task_id, obs_id)
        return Image(path=str(path))

    # ---------------------------------------------------------------- shared task record

    @mcp.tool()
    def get_task_record(task_id: str) -> dict[str, Any]:
        """Current task state: budget, every attempt (with status), observations, findings,
        hypotheses, sources used and missing guidance."""
        return _call(sessions.summary, task_id)

    @mcp.tool()
    def append_finding(task_id: str, obs_ids: list[str], description: str,
                       hypotheses: list[str] | None = None,
                       uncertainty: Literal["low", "medium", "high"] = "high",
                       region: list[float] | None = None,
                       source_ids: list[str] | None = None) -> dict[str, Any]:
        """Record a finding. It must cite at least one existing obs_id; findings citing failed
        attempts or unknown observations are rejected."""
        finding = {"obs_ids": obs_ids, "description": description, "hypotheses": hypotheses or [],
                   "uncertainty": uncertainty, "region": tuple(region) if region else None,
                   "source_ids": source_ids or []}
        return _call(sessions.add_finding, task_id, finding)

    @mcp.tool()
    def post_message(task_id: str, sender: Role, recipient: Role, type: MsgType, content: str,
                     obs_refs: list[str] | None = None, source_ids: list[str] | None = None,
                     next_step: str | None = None) -> dict[str, Any]:
        """Post a structured message between agents onto the shared task record."""
        return _call(sessions.post_message, task_id, sender, recipient, type, content,
                     obs_refs, source_ids, next_step)

    # ---------------------------------------------------------------- knowledge + reasoning (Day 4)

    @mcp.tool()
    def retrieve_procedures(task_id: str, query: str) -> dict[str, Any]:
        """Retrieve up to 3 approved procedures for the task's confirmed object category (plus general
        guidance). Also reports higher-scoring passages rejected for being written for another category,
        and missing guidance when no category-specific procedure exists."""
        return _call(sessions.retrieve, task_id, query)

    @mcp.tool()
    def record_tot(task_id: str, candidates: list[dict[str, Any]], selected_branch: str | None = None) -> dict[str, Any]:
        """Store a bounded Tree-of-Thought search (candidates with scores and pruning). Allowed once per
        inspection with at most 15 candidate evaluations."""
        return _call(sessions.record_tot, task_id, candidates, selected_branch)

    @mcp.tool()
    def submit_report(task_id: str, report: dict[str, Any]) -> dict[str, Any]:
        """Submit the final inspection report (outcome, summary, evidence links, remaining
        uncertainty, sources, needs_human_review, scope_note). Rejected unless every definitive
        outcome cites real observations, No defect detected states its scope, and Insufficient
        evidence requests human review."""
        return _call(sessions.submit_report, task_id, report)

    mcp.sessions = sessions  # type: ignore[attr-defined]  # handy for in-process tests and the Flow
    return mcp


def main() -> None:
    ap = argparse.ArgumentParser(description="InspectBot MCP server")
    ap.add_argument("--transport", choices=["streamable-http", "stdio"], default="streamable-http")
    ap.add_argument("--host", default=os.getenv("INSPECTBOT_MCP_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.getenv("INSPECTBOT_MCP_PORT", "8765")))
    a = ap.parse_args()
    build_server(host=a.host, port=a.port).run(transport=a.transport)


if __name__ == "__main__":
    main()
