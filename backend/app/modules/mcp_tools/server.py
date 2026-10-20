"""Internal MCP tool server over stdio (no network listener). Launched as a child process by the worker.

Every tool takes a `capability` token that the worker injects; the model never sees or chooses it.
"""

import sys

from mcp.server.fastmcp import FastMCP

from app.core.db import db_session
from app.core.logging import configure_logging
from app.modules.mcp_tools.tools import TOOLS, dispatch

mcp = FastMCP("decisionops-tools")


def _call(tool: str, capability: str, **arguments) -> dict:
    with db_session() as db:
        return dispatch(db, tool, capability, {k: v for k, v in arguments.items() if v is not None})


@mcp.tool(name="rag_search", description=TOOLS["rag_search"][2])
def rag_search(capability: str, query: str, k: int = 5) -> dict:
    return _call("rag_search", capability, query=query, k=k)


@mcp.tool(name="market_get_quotes", description=TOOLS["market_get_quotes"][2])
def market_get_quotes(capability: str, symbols: list[str]) -> dict:
    return _call("market_get_quotes", capability, symbols=symbols)


@mcp.tool(name="market_get_history", description=TOOLS["market_get_history"][2])
def market_get_history(capability: str, symbol: str, days: int = 30) -> dict:
    return _call("market_get_history", capability, symbol=symbol, days=days)


@mcp.tool(name="calendar_get_events", description=TOOLS["calendar_get_events"][2])
def calendar_get_events(capability: str, mic: str, days: int = 7) -> dict:
    return _call("calendar_get_events", capability, mic=mic, days=days)


@mcp.tool(name="instrument_lookup", description=TOOLS["instrument_lookup"][2])
def instrument_lookup(capability: str, query: str) -> dict:
    return _call("instrument_lookup", capability, query=query)


@mcp.tool(name="portfolio_get_positions", description=TOOLS["portfolio_get_positions"][2])
def portfolio_get_positions(capability: str) -> dict:
    return _call("portfolio_get_positions", capability)


@mcp.tool(name="portfolio_get_exposure", description=TOOLS["portfolio_get_exposure"][2])
def portfolio_get_exposure(capability: str) -> dict:
    return _call("portfolio_get_exposure", capability)


@mcp.tool(name="scenario_run", description=TOOLS["scenario_run"][2])
def scenario_run(capability: str, symbols: list[str], proposed_side: str | None = None,
                 proposed_value_home: float | None = None) -> dict:
    return _call("scenario_run", capability, symbols=symbols, proposed_side=proposed_side,
                 proposed_value_home=proposed_value_home)


@mcp.tool(name="checks_run", description=TOOLS["checks_run"][2])
def checks_run(capability: str) -> dict:
    return _call("checks_run", capability)


if __name__ == "__main__":
    configure_logging("WARNING", stream=sys.stderr)  # stdout carries the MCP protocol
    mcp.run("stdio")
