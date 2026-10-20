"""Tool gateways used by role executors.

McpGateway   — real MCP client: spawns the stdio tool server as a child process (used by the worker).
LocalGateway — same `dispatch` in-process (same authorization); used in unit tests only.
"""

import asyncio
import json
import os
import sys
import threading

from app.core.db import db_session
from app.modules.mcp_tools.tools import dispatch


class ToolGateway:
    kind = "abstract"

    def call(self, tool: str, capability: str, arguments: dict) -> dict:
        raise NotImplementedError

    def list_tools(self) -> list[dict]:
        raise NotImplementedError

    def close(self) -> None:
        pass


class LocalGateway(ToolGateway):
    kind = "local"

    def call(self, tool: str, capability: str, arguments: dict) -> dict:
        with db_session() as db:
            return dispatch(db, tool, capability, arguments)

    def list_tools(self) -> list[dict]:
        from app.modules.mcp_tools.tools import TOOLS

        return [{"name": n, "description": t[2]} for n, t in TOOLS.items()]


class McpGateway(ToolGateway):
    kind = "mcp-stdio"

    def __init__(self, timeout: float = 60):
        from mcp import StdioServerParameters

        self.timeout = timeout
        self._params = StdioServerParameters(command=sys.executable,
                                             args=["-m", "app.modules.mcp_tools.server"], env=dict(os.environ))
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._error: BaseException | None = None
        self._session = None
        self._stop: asyncio.Event | None = None
        self._thread = threading.Thread(target=self._run, name="mcp-client", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=60):
            raise RuntimeError("MCP tool server did not start in time")
        if self._error:
            raise RuntimeError(f"MCP tool server failed to start: {self._error}")

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._main())
        except BaseException as exc:  # noqa: BLE001
            self._error = exc
            self._ready.set()

    async def _main(self) -> None:
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        self._stop = asyncio.Event()
        async with stdio_client(self._params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            self._session = session
            self._ready.set()
            await self._stop.wait()

    def _submit(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout=self.timeout)

    def call(self, tool: str, capability: str, arguments: dict) -> dict:
        result = self._submit(self._session.call_tool(tool, {"capability": capability, **arguments}))
        structured = getattr(result, "structuredContent", None)
        if isinstance(structured, dict):
            return structured.get("result", structured) if set(structured) == {"result"} else structured
        for part in result.content:
            if getattr(part, "type", None) == "text":
                try:
                    return json.loads(part.text)
                except ValueError:  # the MCP layer rejected the call (e.g. arguments failed its input schema)
                    code = ("invalid_result" if not getattr(result, "isError", False) else
                            "unknown_tool" if "unknown tool" in part.text.lower() else "invalid_arguments")
                    return {"ok": False, "error": {"code": code, "message": part.text[:300]}}
        return {"ok": False, "error": {"code": "empty_result", "message": "Tool returned no content"}}

    def list_tools(self) -> list[dict]:
        listed = self._submit(self._session.list_tools())
        return [{"name": t.name, "description": t.description, "input_schema": t.inputSchema} for t in listed.tools]

    def close(self) -> None:
        if self._stop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._stop.set)
            self._thread.join(timeout=10)
