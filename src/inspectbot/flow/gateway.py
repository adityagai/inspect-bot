"""How the Coordinator reaches the MCP tools.

MCPGateway talks to the running MCP server over streamable HTTP (the real path).
LocalGateway calls the same SessionManager in-process (tests, fast offline runs).
Both expose one method, call(tool, **args) -> dict, with identical results.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

import anyio


class GatewayError(RuntimeError):
    pass


class Gateway(Protocol):
    def call(self, tool: str, **args: Any) -> dict[str, Any]: ...


class LocalGateway:
    def __init__(self, manager=None) -> None:
        from inspectbot.mcp_server.server import build_server
        from inspectbot.mcp_server.session import SessionManager

        self.manager = manager or SessionManager()
        self._server = build_server(self.manager)

    def call(self, tool: str, **args: Any) -> dict[str, Any]:
        async def go():
            # FastMCP.call_tool runs the exact tool function and its argument validation.
            return await self._server.call_tool(tool, args)

        try:
            result = anyio.run(go)
        except Exception as e:  # ToolError / validation errors surface as GatewayError
            raise GatewayError(f"{tool}: {e}") from e
        content = result[0] if isinstance(result, tuple) else result
        return json.loads(content[0].text)


class MCPGateway:
    def __init__(self, url: str = "http://127.0.0.1:8765/mcp") -> None:
        self.url = url

    def call(self, tool: str, **args: Any) -> dict[str, Any]:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        async def go():
            async with streamablehttp_client(self.url) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    return await session.call_tool(tool, args)

        result = anyio.run(go)
        if result.isError:
            raise GatewayError(f"{tool}: {result.content[0].text if result.content else 'error'}")
        return json.loads(result.content[0].text)
