"""MCP tool server permissions through the real stdio transport (McpGateway spawns the server as a child process):
read/compute-only inventory, server-side capability checks per role, expiry, inactive runs and call budgets."""

import uuid

import pytest

from app.core.db import db_session
from app.modules.mcp_tools.gateway import McpGateway
from app.modules.mcp_tools.tools import ROLE_CALL_BUDGET, ROLE_TOOLS, TOOLS, issue_capability
from tests.conftest import instrument_id

FORBIDDEN_WORDS = ("order", "submit", "approve", "cancel", "share", "invite", "setting", "delete", "erase", "stop")


@pytest.fixture(scope="module")
def gateway(database):
    gw = McpGateway()
    yield gw
    gw.close()


@pytest.fixture
def running_run(owner):
    r = owner.post("/api/decisions", {"title": "MCP test", "question": "Should I add to NVDA?",
                                      "instrument_ids": [instrument_id(owner, "NVDA")], "start_run": True})
    run_id = uuid.UUID(r.json()["run_id"])
    from app.modules.workflows.models import WorkflowRun

    with db_session() as db:
        db.get(WorkflowRun, run_id).status = "running"
    return run_id


def _code(res: dict) -> str | None:
    return None if res.get("ok") else res["error"]["code"]


def test_inventory_over_stdio_is_read_compute_only(gateway):
    names = {t["name"] for t in gateway.list_tools()}
    assert names == set(TOOLS)
    assert not [n for n in names if any(w in n for w in FORBIDDEN_WORDS)]
    assert all(t.get("input_schema") for t in gateway.list_tools())


def test_role_permissions_enforced_server_side(gateway, running_run):
    research = issue_capability(running_run, "research")
    assert gateway.call("rag_search", research, {"query": "export restrictions", "k": 3})["ok"] is True
    assert _code(gateway.call("portfolio_get_positions", research, {})) == "tool_not_permitted"
    analysis = issue_capability(running_run, "analysis")
    assert _code(gateway.call("rag_search", analysis, {"query": "x y"})) == "tool_not_permitted"
    manager = issue_capability(running_run, "manager")
    assert _code(gateway.call("rag_search", manager, {"query": "export restrictions"})) == "tool_not_permitted"
    for tool in TOOLS:  # denied either by the capability check or by the MCP input schema; never executed
        assert gateway.call(tool, manager, {}).get("ok") is False
    assert _code(gateway.call("rag_search", research, {})) == "invalid_arguments"  # MCP-layer schema rejection
    assert _code(gateway.call("rag_search", "forged.token", {"query": "abc"})) == "invalid_capability"
    assert _code(gateway.call("rag_search", issue_capability(running_run, "research", ttl_minutes=-1),
                              {"query": "abc"})) == "capability_expired"
    assert _code(gateway.call("rag_search", research, {"query": "a" * 600})) == "invalid_arguments"
    assert _code(gateway.call("place_order", research, {})) == "unknown_tool"


def test_inactive_run_and_budget(gateway, running_run):
    from app.modules.workflows.models import WorkflowRun

    cap = issue_capability(running_run, "scenario")
    budget = ROLE_CALL_BUDGET["scenario"]
    codes = [_code(gateway.call("scenario_run", cap, {"symbols": ["NVDA"]})) for _ in range(budget + 1)]
    assert codes[-1] == "budget_exhausted" and "budget_exhausted" not in codes[:budget]
    with db_session() as db:
        db.get(WorkflowRun, running_run).cancel_requested = True
    critic = issue_capability(running_run, "critic")
    assert _code(gateway.call("checks_run", critic, {})) == "run_not_active"


def test_every_role_tool_exists():
    for role, tools in ROLE_TOOLS.items():
        assert tools <= set(TOOLS), role
