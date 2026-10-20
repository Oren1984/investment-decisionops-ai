"""Supported-market matrix (PROJECT_PLAN §7.2). Venues, not countries."""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Venue:
    mic: str
    name: str
    short: str
    country: str
    timezone: str
    currency: str
    calendar: str  # exchange_calendars code, or FX24x5
    has_lunch_break: bool
    execution_scope: str  # plain-language execution status through the first broker
    execution_status: str  # proposed_first_scope | adapter_capable_unverified | reference_only | out_of_scope


VENUES: dict[str, Venue] = {v.mic: v for v in [
    Venue("XTAE", "Tel Aviv Stock Exchange", "TASE", "Israel", "Asia/Jerusalem", "ILS", "XTAE", False,
          "Out of scope for the first broker. Reference data, calendar and manual holdings only.", "out_of_scope"),
    Venue("XNYS", "New York Stock Exchange", "NYSE", "United States", "America/New_York", "USD", "XNYS", False,
          "Proposed first verified scope (US stocks/ETFs through IBKR Paper, once configured).", "proposed_first_scope"),
    Venue("XNAS", "Nasdaq", "Nasdaq", "United States", "America/New_York", "USD", "XNAS", False,
          "Proposed first verified scope (US stocks/ETFs through IBKR Paper, once configured).", "proposed_first_scope"),
    Venue("XTKS", "Tokyo Stock Exchange", "TSE", "Japan", "Asia/Tokyo", "JPY", "XTKS", True,
          "Adapter-capable; unverified; depends on account permissions.", "adapter_capable_unverified"),
    Venue("XSHG", "Shanghai Stock Exchange", "SSE", "China", "Asia/Shanghai", "CNY", "XSHG", True,
          "Reference only.", "reference_only"),
    Venue("XLON", "London Stock Exchange", "LSE", "United Kingdom", "Europe/London", "GBP", "XLON", False,
          "Adapter-capable; unverified.", "adapter_capable_unverified"),
    Venue("XETR", "Xetra (Deutsche Börse)", "Xetra", "Germany", "Europe/Berlin", "EUR", "XETR", False,
          "Adapter-capable; unverified.", "adapter_capable_unverified"),
    Venue("FXSP", "FX spot (24×5)", "FX", "Global", "America/New_York", "USD", "FX24x5", False,
          "Proposed first verified scope (IBKR IDEALPRO, once configured).", "proposed_first_scope"),
]}
# Indices (SPX, TA-35, N225 …) are instruments on their home venue with kind='index' and tradable=False:
# "Reference index – not tradable".


def venue(mic: str) -> Venue:
    return VENUES[mic]


def venue_dict(mic: str) -> dict:
    return asdict(VENUES[mic])


def all_venues() -> list[dict]:
    return [asdict(v) for v in VENUES.values()]
