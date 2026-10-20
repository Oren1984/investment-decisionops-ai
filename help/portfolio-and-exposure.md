---
title: Portfolio and exposure
category: Portfolio
summary: How values, FX conversion and manual holdings work.
routes: /portfolio
---
Values are converted to your home currency (ILS by default) with the FX rate's as-of time shown.

- **Synthetic** positions come from the Mock broker. Fills from Mock orders update them, because the broker is the source of truth.
- **Manual holdings** are assets outside the broker (for example TASE shares at an Israeli bank). You enter quantity and unit value; they are labelled *Manual* and never treated as live data.
- Exposure is computed by asset class, currency and venue.
