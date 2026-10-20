"""Scenario engine (Computed). Agents may choose and explain scenarios; they never produce these numbers."""

from decimal import Decimal

DEFAULT_SHOCKS = [
    ("Severe downside", -20.0, 0.0),
    ("Downside", -10.0, 0.0),
    ("Base case", 0.0, 0.0),
    ("Upside", 10.0, 0.0),
    ("Home-currency strengthens 5%", 0.0, -5.0),
]


def run_scenarios(valuation: dict, instrument_rows: list[dict], proposed: dict | None,
                  shocks: list[tuple[str, float, float]] | None = None) -> dict:
    """instrument_rows: [{symbol, currency, value_home}] currently held for the question's instruments.
    proposed: optional {symbol, currency, side, value_home} simulated trade added before shocks are applied.
    Each shock moves the question's instruments by shock_pct and non-home FX by fx_pct."""
    shocks = shocks or DEFAULT_SHOCKS
    home = valuation.get("home_currency", "ILS")
    total = Decimal(str(valuation.get("total_home") or 0))
    exposure = {r["symbol"]: Decimal(str(r["value_home"])) for r in instrument_rows}
    if proposed:
        sign = Decimal(1 if proposed["side"] == "buy" else -1)
        exposure[proposed["symbol"]] = exposure.get(proposed["symbol"], Decimal(0)) + sign * Decimal(str(proposed["value_home"]))
    foreign = sum((Decimal(str(r["value_home"])) for r in valuation.get("positions", []) + valuation.get("manual_holdings", [])
                   if r.get("currency") != home), Decimal(0))
    rows = []
    for name, shock_pct, fx_pct in shocks:
        inst_change = sum(exposure.values(), Decimal(0)) * Decimal(str(shock_pct)) / 100
        fx_change = foreign * Decimal(str(fx_pct)) / 100
        change = inst_change + fx_change
        rows.append({
            "name": name, "shock_pct": shock_pct, "fx_pct": fx_pct,
            "portfolio_change_home": float(round(change, 2)),
            "portfolio_change_pct": float(round(change / total * 100, 3)) if total else 0.0,
            "portfolio_after_home": float(round(total + change, 2)),
        })
    return {"label": "Computed", "home_currency": home, "includes_proposed_trade": bool(proposed),
            "exposure_home": {k: float(round(v, 2)) for k, v in exposure.items()}, "rows": rows,
            "method": "Linear shock of the question's instruments plus a home-currency move on foreign holdings. "
                      "No correlations or volatility model; a simple, explainable stress view."}
