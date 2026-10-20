# Broker integration, orders and controls

## Modes

| Mode | Adapter | Status |
| --- | --- | --- |
| **Mock** (default) | `MockAdapter` (`backend/app/modules/brokers/mock.py`), simulated account `MOCK-0001` | **Implemented and verified locally.** Mock success never counts as broker verification |
| **Paper** | `IbkrAdapter` (`ibkr.py`) via IB Gateway + `ib_async`, if `IBKR_HOST` / `IBKR_PAPER_PORT` are configured | **Implemented but externally unverified**: contract-tested against a fake client only; no IBKR account, gateway or subscription is configured or assumed (D1) |
| **Live** | — | **Not implemented or blocked: not authorized.** The API refuses Live regardless of configuration |

The mode is stored on every order record; Mock cannot be pointed at real endpoints.

## Supported-market matrix

| Venue | Calendar | Zone | Clock / calendar | Reference data (Mock) | Execution |
| --- | --- | --- | --- | --- | --- |
| Tel Aviv SE | XTAE | Asia/Jerusalem | Yes (Mon–Fri from 5 Jan 2026, Friday early close) | Yes + **manual holdings** | Out of scope (D2) |
| NYSE / Nasdaq | XNYS / XNAS | America/New_York | Yes (early closes) | Yes | Mock; IBKR Paper unverified |
| Tokyo SE | XTKS | Asia/Tokyo | Yes (lunch break) | Yes | Mock; unverified |
| Shanghai SE | XSHG | Asia/Shanghai | Yes (lunch break) | Yes | Reference only |
| London SE | XLON | Europe/London | Yes | Yes | Mock; unverified |
| Xetra | XETR | Europe/Berlin | Yes | Yes | Mock; unverified |
| FX spot | in-house 24×5 | America/New_York (17:00 week boundary) | Yes | Yes | Mock; IBKR Paper unverified |
| Indices (SPX, TA-35, N225 …) | — | venue zone | — | Yes | **Reference only: not tradable** |

Calendars are computed offline from the installed `exchange_calendars` package; accuracy depends on its release.
Quotes are **synthetic Mock data**; no real market-data feed is configured or claimed.

## Adapter contract

`BrokerAdapter` (`base.py`): capabilities, connection status, accounts, balances, positions, open orders,
executions, instrument lookup (keyed by venue MIC + broker instrument ID, not an IBKR `conid`), preview (costs may
be `UNKNOWN`), submit (`accepted | rejected | uncertain`), cancel. The contract test suite is
adapter-independent and runs against Mock and the fake IBKR client. Order scope: market, limit, stop, stop-limit;
DAY/GTC; long-only, cash-account behaviour.

## Order flow and controls (all enforced in the backend)

1. **Preview** shows mode, broker and account, instrument and venue, currency, side/quantity/type, prices, TIF,
   estimated commission or **Unknown**, notional in instrument and home currency with the FX as-of time, quote
   time and freshness, venue session state, the linked decision, and these checks: per-order notional limit,
   position % of portfolio, orders per day, instrument allowlist per mode, price collar, market orders only while
   the venue is open, long-only, quote freshness.
2. **Approval** requires step-up re-authentication and binds to `sha256` of the canonical payload; it expires
   after 5 minutes. A material edit invalidates it.
3. **Idempotent submit:** a unique client order ID is assigned at ticket creation; a repeat submit returns the
   existing order. A resubmission after a confirmed `NOT_FOUND` is a new explicit action with a new ID.
4. **Never filled on submit.** Fills come only from broker events or reconciliation.
5. **Uncertain outcomes:** a timeout or disconnect after send sets `uncertain`; no retry until reconciliation
   resolves it. Reconciliation runs every 30 s and on demand; mismatches raise alerts.
6. **Stop** blocks new submissions and agent runs instantly (audited). It does not reverse fills or cancel orders
   the broker already accepted; **cancel open orders** is a separate tracked step.

## Mock scenarios

`success`, `rejection`, `partial_fill`, `timeout` (broker received it; reconciliation finds it),
`disconnect_after_send` (broker never received it; reconciliation: not found), `duplicate_request`,
`fill_after_cancel`, `stale_quote` (blocked by the backend before submission). All are exercised by integration
tests; J7 and J8 cover the UI path.

## Configuring IBKR Paper (future, owner decision)

Requires an eligible, opened IBKR account (paper accounts hang off a live account), IB Gateway installed and logged
in manually with 2FA, and possibly market-data subscriptions. None of this is authorized or assumed. Steps and the
verification procedure: Help → *IBKR setup*. Until that procedure is run against a real Paper account, the status
stays **Implemented but externally unverified**.
