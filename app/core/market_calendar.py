"""
NSE/BSE equity cash session helpers (IST).

Typical NSE/BSE equity timings (cash / normal market):
- Pre-open: 9:00 – 9:15 — order placement and price discovery
- Normal (continuous trading): 9:15 – 15:30 — regular buy/sell
- Between normal and closing: ~15:30 – 15:40 — not continuous trading
- Closing (call auction): 15:40 – 16:00 — closing price calculation
- After-market orders (AMO): commonly from ~15:45 until next morning — queued for next day;
  not treated as live intraday execution here (verify broker).

Weekdays: Monday–Friday; weekends closed. Holidays per official NSE circular (see NSE_BSE_HOLIDAYS).
"""
from __future__ import annotations

from datetime import date, datetime, time
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

# --- Boundaries (IST) ---
PRE_OPEN_START = time(9, 0)
PRE_OPEN_END = time(9, 15)
REGULAR_START = time(9, 15)
REGULAR_END = time(15, 30)
CLOSING_START = time(15, 40)
CLOSING_END = time(16, 0)

# Update yearly from official NSE "Market Holidays" PDF.
NSE_BSE_HOLIDAYS: set[date] = {
    date(2026, 1, 26),   # Republic Day
    date(2026, 3, 26),   # Ram Navami
    date(2026, 3, 31),   # Mahavir Jayanti
    date(2026, 4, 3),    # Good Friday
    date(2026, 4, 14),   # Dr. Ambedkar Jayanti
    date(2026, 5, 1),    # Maharashtra Day
    date(2026, 5, 28),   # Bakri Id
    date(2026, 8, 15),   # Independence Day
    date(2026, 10, 2),   # Gandhi Jayanti
    date(2026, 11, 9),   # Diwali — verify on NSE circular for exact date
    date(2026, 12, 25), # Christmas
}


def ist_now() -> datetime:
    return datetime.now(IST)


def is_nse_bse_trading_day(d: Optional[date] = None) -> bool:
    d = d or ist_now().date()
    if d.weekday() >= 5:
        return False
    return d not in NSE_BSE_HOLIDAYS


def equity_cash_session_phase(now: Optional[datetime] = None) -> str:
    """
    Return a coarse phase for the equity cash calendar day (IST).

    One of: pre_open | regular | between_regular_and_closing | closing | closed
    """
    now = now or ist_now()
    t = now.time()
    if PRE_OPEN_START <= t < PRE_OPEN_END:
        return "pre_open"
    if REGULAR_START <= t < REGULAR_END:
        return "regular"
    if REGULAR_END <= t < CLOSING_START:
        return "between_regular_and_closing"
    if CLOSING_START <= t < CLOSING_END:
        return "closing"
    return "closed"


def nse_regular_session_has_started(now: Optional[datetime] = None) -> bool:
    t = (now or ist_now()).time()
    return REGULAR_START <= t < REGULAR_END


def can_place_nse_bse_equity_trade(now: Optional[datetime] = None) -> Tuple[bool, str]:
    """
    True only on a trading day during **normal / continuous** cash session (9:15–15:30 IST).
    Pre-open, post-15:30 transition, closing call, and overnight AMO are **not** allowed here —
    intraday-style live orders should use the continuous window; verify broker for MIS/CNC/AMO.
    """
    now = now or ist_now()
    d = now.date()
    if not is_nse_bse_trading_day(d):
        return False, "NSE/BSE equity market is closed today (weekend or holiday)."
    t = now.time()
    if t < PRE_OPEN_START:
        return (
            False,
            f"Before pre-open — pre-open {PRE_OPEN_START.strftime('%H:%M')}–{PRE_OPEN_END.strftime('%H:%M')} IST; "
            f"normal {REGULAR_START.strftime('%H:%M')}–{REGULAR_END.strftime('%H:%M')} IST.",
        )
    if t < REGULAR_START:
        return (
            False,
            f"Pre-open session ({PRE_OPEN_START.strftime('%H:%M')}–{PRE_OPEN_END.strftime('%H:%M')} IST) — "
            f"continuous trading from {REGULAR_START.strftime('%H:%M')}.",
        )
    if t < REGULAR_END:
        return (
            True,
            f"Normal session ({REGULAR_START.strftime('%H:%M')}–{REGULAR_END.strftime('%H:%M')} IST).",
        )
    if t < CLOSING_START:
        return (
            False,
            f"Regular session ended at {REGULAR_END.strftime('%H:%M')} IST — "
            f"closing call {CLOSING_START.strftime('%H:%M')}–{CLOSING_END.strftime('%H:%M')} IST.",
        )
    if t < CLOSING_END:
        return (
            False,
            f"Closing price session ({CLOSING_START.strftime('%H:%M')}–{CLOSING_END.strftime('%H:%M')} IST) — "
            "not continuous trading.",
        )
    return (
        False,
        "Cash market closed for the day (AMO may be available until next open; verify broker).",
    )


def market_status_line(now: Optional[datetime] = None) -> str:
    ok, msg = can_place_nse_bse_equity_trade(now)
    phase = equity_cash_session_phase(now)
    if ok:
        return f"🟢 LIVE: {msg}"
    phase_hint = {
        "pre_open": "Pre-open",
        "regular": "Regular",
        "between_regular_and_closing": "Between sessions",
        "closing": "Closing call",
        "closed": "Closed",
    }.get(phase, phase)
    return f"🔴 CLOSED ({phase_hint}): {msg}"
