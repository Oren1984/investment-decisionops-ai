"""Seed the isolated demo database with a synthetic workspace. Runs the REAL deterministic workflow and Mock order
paths so every screen shows genuine (simulated) state. Idempotent: does nothing if a demo owner exists."""

import uuid
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from app.core.authz import Principal
from app.core.clock import FrozenClock, get_clock, set_clock, utcnow
from app.core.db import db_session
from app.core.logging import get_logger
from app.core.security import hash_password, new_token
from app.modules.collaboration.models import ActionItem, Comment, Note, ShareGrant
from app.modules.identity.models import User
from app.modules.markets.models import Instrument
from app.modules.meetings.models import Meeting, MeetingParticipant
from app.seed import seed_owner_samples

log = get_logger("seed_demo")


def _principal(user: User, stepped_up: bool = True) -> Principal:
    return Principal(user_id=user.id, role="owner", email=user.email, display_name=user.display_name,
                     timezone=user.timezone, stepped_up_at=utcnow() if stepped_up else None)


def _iid(db, symbol: str) -> uuid.UUID:
    return db.scalar(select(Instrument.id).where(Instrument.symbol == symbol))


def seed_demo() -> None:
    from app.modules.agents.flow import FlowRunner
    from app.modules.decisions import service as decisions
    from app.modules.decisions.models import Decision
    from app.modules.identity.service import ensure_demo_user
    from app.modules.mcp_tools.gateway import McpGateway
    from app.modules.workflows.service import start_run

    with db_session() as db:
        ensure_demo_user(db)  # the one read-only sign-in; kept in step with DEMO_USER_* on every migrate
    with db_session() as db:
        if db.scalar(select(User).where(User.role == "owner")) is not None:
            log.info("demo_already_seeded")
            return
        seed_owner_samples(db)
        owner = User(email="owner@demo.invalid", display_name="Demo owner", role="owner", timezone="Asia/Jerusalem",
                     password_hash=hash_password(new_token(24)))  # unusable: the demo has no sign-in
        broker = User(email="broker@demo.invalid", display_name="Dana Levi (broker, London)", role="collaborator",
                      timezone="Europe/London", password_hash=hash_password(new_token(24)))
        trader = User(email="trader@demo.invalid", display_name="Kenji Sato (trader, Tokyo)", role="collaborator",
                      timezone="Asia/Tokyo", password_hash=hash_password(new_token(24)))
        db.add_all([owner, broker, trader])
        db.flush()
        owner_id, broker_id, trader_id = owner.id, broker.id, trader.id

    questions = [
        ("Add to NVDA after data-center growth?", "Should I add to NVDA after the reported data-center growth, given "
         "its valuation and export-restriction risks?", ["NVDA"], "accept"),
        ("Reduce USD exposure?", "Should I reduce my USD exposure (USDILS) given the shekel outlook?", ["USDILS"], "reject"),
        ("Bank Leumi via my Israeli bank?", "Is Bank Leumi (LUMI) worth adding through my Israeli bank account?",
         ["LUMI"], None),
        ("Trim AAPL to rebalance?", "Should I trim AAPL to bring equities back to the policy target?", ["AAPL"], "accept"),
    ]
    gateway = McpGateway()
    created: list[tuple[uuid.UUID, str | None]] = []
    try:
        for title, question, symbols, outcome in questions:
            with db_session() as db:
                owner = db.get(User, owner_id)
                d = decisions.create_decision(db, _principal(owner), title, question, [_iid(db, s) for s in symbols],
                                              "mock")
                run = start_run(db, _principal(owner), d, "deterministic")
                ids = (d.id, run.id)
            FlowRunner(ids[1], gateway).execute()
            created.append((ids[0], outcome))
    finally:
        gateway.close()

    with db_session() as db:
        owner = db.get(User, owner_id)
        p = _principal(owner)
        for decision_id, outcome in created:
            d = db.get(Decision, decision_id)
            if outcome and d.status == "ready_for_decision":
                decisions.record_decision(db, p, d, outcome, {
                    "accept": "Evidence supports the thesis and the position stays within policy limits.",
                    "reject": "Currency view is not strong enough to justify the hedging cost.",
                }[outcome])
        aapl = db.get(Decision, created[3][0])
        if aapl.status == "decided":
            decisions.submit_review(db, p, aapl, {
                "process_rubric": {"evidence_quality": 2, "alternatives_considered": 1, "risk_sizing": 2,
                                   "followed_plan": 2, "timing_discipline": 1},
                "outcome_return_pct": Decimal("2.4"), "benchmark_return_pct": Decimal("3.1"),
                "assumption_observations": [{"assumption_code": "A1", "observation": "AAPL moved +2.4% (synthetic).",
                                             "held": True}],
                "notes": "Rebalance followed the policy. Outcome slightly below the benchmark.",
                "lessons": [{"text": "Rebalancing rules removed the temptation to time the trim.", "tags": ["process", "rebalancing"]}],
                "close": True})
        db.add(Decision(owner_id=owner_id, title="Draft: Toyota after yen move?", question="Does a weaker yen make "
                        "Toyota (7203) attractive for a small position?", instrument_ids=[str(_iid(db, "7203"))],
                        status="draft", mode="mock"))
        nvda_decision = created[0][0]

        # Sharing and collaboration
        db.add(ShareGrant(object_type="decision", object_id=nvda_decision, grantee_id=broker_id, permission="comment",
                          created_by=owner_id))
        meeting = Meeting(owner_id=owner_id, title="NVDA position review with Dana",
                          starts_at=(utcnow() + timedelta(days=2)).replace(hour=14, minute=0, second=0, microsecond=0),
                          duration_minutes=30, timezone="Asia/Jerusalem", provider="mock", provider_status="simulated",
                          agenda="1. Data-center growth vs valuation\n2. Export-restriction risk\n3. Position size vs policy",
                          decision_id=nvda_decision)
        db.add(meeting)
        db.flush()
        db.add_all([
            MeetingParticipant(meeting_id=meeting.id, user_id=broker_id, name="Dana Levi", timezone="Europe/London"),
            MeetingParticipant(meeting_id=meeting.id, user_id=trader_id, name="Kenji Sato", timezone="Asia/Tokyo"),
            ShareGrant(object_type="meeting", object_id=meeting.id, grantee_id=broker_id, permission="comment",
                       created_by=owner_id),
            Note(owner_id=owner_id, title="Pre-meeting notes", body="Ask about broker research on custom accelerators.",
                 meeting_id=meeting.id, decision_id=nvda_decision),
            ActionItem(owner_id=owner_id, meeting_id=meeting.id, title="Send updated position sizing table",
                       assignee_id=broker_id, created_by=owner_id, due_at=utcnow() + timedelta(days=3)),
            ActionItem(owner_id=owner_id, meeting_id=meeting.id, title="Check IBKR paper account eligibility",
                       created_by=owner_id),
            Comment(object_type="decision", object_id=nvda_decision, author_id=broker_id,
                    body="Agree on sizing. Watch the next export-control announcement."),
        ])
        manual = Meeting(owner_id=owner_id, title="Monthly check-in (manual Zoom link example)",
                         starts_at=(utcnow() + timedelta(days=9)).replace(hour=8, minute=0, second=0, microsecond=0),
                         duration_minutes=45, timezone="Asia/Jerusalem", provider="manual", link_provider="zoom",
                         provider_status="linked", join_url="https://zoom.us/j/0000000000", agenda="Portfolio review")
        db.add(manual)
        db.flush()
        db.add(MeetingParticipant(meeting_id=manual.id, user_id=trader_id, name="Kenji Sato", timezone="Asia/Tokyo"))

    _seed_orders(owner_id, nvda_decision)
    log.info("demo_seeded")


def _seed_orders(owner_id: uuid.UUID, decision_id: uuid.UUID) -> None:
    """Exercise real Mock order scenarios so the Orders screen shows each state."""
    from app.modules.orders import service as orders

    scenarios = [("NVDA", "buy", 10, "success", decision_id), ("MSFT", "buy", 20, "partial_fill", None),
                 ("JPM", "buy", 5, "rejection", None), ("QQQ", "buy", 3, "disconnect_after_send", None),
                 ("AAPL", "sell", 10, "timeout", None)]
    ids = []
    for symbol, side, qty, scenario, did in scenarios:
        with db_session() as db:
            owner = db.get(User, owner_id)
            p = _principal(owner)
            inst = db.scalar(select(Instrument).where(Instrument.symbol == symbol))
            from app.modules.markets.models import QuoteSnapshot

            q = db.get(QuoteSnapshot, inst.id)
            t = orders.create_ticket(db, p, {"instrument_id": inst.id, "side": side, "quantity": qty,
                                             "order_type": "limit", "limit_price": q.price, "tif": "DAY",
                                             "decision_id": did, "mock_scenario": scenario})
            orders.preview(db, p, t)
            if not t.preview["all_checks_passed"]:
                # Outside market hours the session rule only blocks market orders; limit orders proceed.
                log.info("demo_order_checks", symbol=symbol, failed=[c["key"] for c in t.preview["limit_checks"]
                                                                     if not c["passed"]])
                continue
            orders.approve(db, p, t)
            ids.append(t.id)
        with db_session() as db:
            owner = db.get(User, owner_id)
            orders.submit(db, _principal(owner), ids[-1])
    real = get_clock()
    try:
        for offset in (5, 65):  # let simulated broker time pass, then reconcile
            set_clock(FrozenClock(real.now() + timedelta(seconds=offset)))
            with db_session() as db:
                orders.reconcile(db, "mock", "periodic")
    finally:
        set_clock(real)
