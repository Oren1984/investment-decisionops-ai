---
title: Order approvals and the stop control
category: Orders
summary: Preview, payload-bound approval, submission and stop.
routes: /orders
---
## From ticket to broker

1. **Ticket** — gets a unique client order ID (used for idempotency). Nothing is sent.
2. **Preview** — mode, account, instrument and venue, currency, side, quantity, type, prices, time in force, estimated commission (or **Unknown**), notional in instrument and home currency with the FX time, quote freshness, session state and every limit check.
3. **Approve** — requires a fresh password confirmation (step-up). The approval is bound to the **exact payload hash** and **expires after 5 minutes**. Any material edit invalidates it.
4. **Submit** — re-checks the hash, expiry, stop, limits, data freshness and session at that moment. A repeated submit returns the existing order and sends nothing.

Orders are **never marked filled on submission**; fills come only from broker execution reports or reconciliation.

## Limits (enforced by the backend)

Per-order value, position size as % of portfolio, orders per day, instrument allowlist per mode, price collar for limit orders, no market orders while the venue is closed, and long-only selling.

## Stop

**Stop blocks new orders and agent actions. It does not reverse fills and does not cancel orders the broker has already accepted.** Use **Cancel open orders** on the Orders page for that; each cancel is tracked until the broker confirms (an order may still fill first).
