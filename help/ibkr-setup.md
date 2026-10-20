---
title: Interactive Brokers (Paper) setup
category: Setup
summary: What is needed before Paper mode can work.
routes: /settings
---
IBKR is the proposed first real broker, subject to your eligibility. The adapter is implemented and tested against a fake client only — its status is **Implemented but externally unverified**.

To try Paper mode in the future you would need, at your own decision and cost:

1. An eligible, open IBKR account (paper accounts attach to a live account).
2. IB Gateway installed on the host and logged in with your 2FA (never automated).
3. Possibly market-data subscriptions.
4. `IBKR_HOST` (and `IBKR_PAPER_PORT`, commonly 4002) in `.env`.

Paper verification does not verify Live. Live stays disabled.
