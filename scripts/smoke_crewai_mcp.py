"""Day 2 smoke test: one CrewAI agent (Claude) drives the robot through the MCP server.

Starts the MCP server over streamable HTTP, connects a CrewAI agent with a
static tool allow-list, and asks it to run two steps of the S1 inspection.

    python scripts/smoke_crewai_mcp.py
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time

from crewai import LLM, Agent, Crew, Task
from crewai.mcp import MCPServerHTTP
from crewai.mcp.filters import create_static_tool_filter
from dotenv import load_dotenv

PORT = int(os.getenv("INSPECTBOT_MCP_PORT", "8765"))


def wait_for_port(port: int, timeout: float = 20) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.3)
    raise RuntimeError(f"MCP server did not open port {port}")


def main() -> None:
    load_dotenv()
    if not os.getenv("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set")
    server = subprocess.Popen([sys.executable, "-m", "inspectbot.mcp_server.server", "--port", str(PORT)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        wait_for_port(PORT)
        llm = LLM(model=f"anthropic/{os.getenv('INSPECTBOT_TEXT_MODEL', 'claude-haiku-5-5')}", max_tokens=1500)
        robot = Agent(
            role="Robot operator",
            goal="Operate the inspection cell exactly as instructed and report tool results faithfully.",
            backstory="You control a simulated inspection robot through MCP tools. You never invent results.",
            llm=llm,
            mcps=[MCPServerHTTP(
                url=f"http://127.0.0.1:{PORT}/mcp",
                tool_filter=create_static_tool_filter(
                    allowed_tool_names=["start_inspection", "set_lighting", "move_camera", "get_task_record"]),
            )],
            max_iter=8,
            verbose=False,
        )
        task = Task(
            description=(
                "1. Start an inspection of scenario S1.\n"
                "2. Change the light to 'top'.\n"
                "3. Try to move the camera to 'oblique_low'.\n"
                "4. Read the task record.\n"
                "Reply with JSON only: {\"task_id\": str, \"observations\": [obs_id...], "
                "\"attempts\": [{\"tool\": str, \"status\": str}], \"actions_remaining\": int}"
            ),
            expected_output="A JSON object with task_id, observations, attempts and actions_remaining.",
            agent=robot,
        )
        result = Crew(agents=[robot], tasks=[task], verbose=False).kickoff()
        raw = str(result.raw)
        print(raw)
        data = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
        assert data["actions_remaining"] == 3, data
        assert len(data["observations"]) == 3, data
        print("\nSMOKE TEST PASSED: CrewAI agent -> MCP server -> inspection cell")
    finally:
        server.terminate()
        server.wait(timeout=10)


if __name__ == "__main__":
    main()
