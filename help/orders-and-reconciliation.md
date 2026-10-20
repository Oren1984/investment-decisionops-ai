---
title: Uncertain orders and reconciliation
category: Orders
summary: What happens when the broker does not confirm.
routes: /orders
---
If the connection times out or drops after sending, the outcome is **Uncertain**. The app does **not** retry. Reconciliation looks the order up at the broker by its order reference:

- found → *Acknowledged*, then fills as reported;
- not found after the grace period (60 s) → **Not found**; you may prepare a resubmission (it gets a new order ID).

Reconciliation runs every 30 seconds and on demand. Mismatches between local and broker state raise an alert and an audit event.

## Mock scenarios

Mock orders can simulate: success, rejection, partial fill, timeout before acknowledgement, disconnect after send, duplicate request, fill after a cancel request, and a stale quote. They exercise the real controls but never count as broker verification.
