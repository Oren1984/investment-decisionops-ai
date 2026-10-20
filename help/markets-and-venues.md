---
title: Venues, instruments and tradability
category: Markets
summary: The supported-market matrix and why some instruments are reference-only.
routes: /markets
---
You pick a **venue** (exchange), not a country.

| Venue | Execution through the first broker |
| --- | --- |
| NYSE, Nasdaq | Proposed first verified scope (US stocks/ETFs) once IBKR Paper is configured |
| FX spot | Proposed first verified scope (majors) |
| Tokyo, London, Xetra | Adapter-capable but unverified |
| Shanghai | Reference only |
| Tel Aviv (TASE) | Out of scope for the first broker: reference data, calendar and **manual holdings** |
| Indices (SPX, TA-35, N225) | Reference index – not tradable |

A **Reference** badge explains why an instrument cannot be traded. Quotes in Mock mode are **Synthetic** and labelled with their age; a quote older than 5 minutes is **stale** and blocks order submission.
