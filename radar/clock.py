"""DST-safe time, windowing, and recency-decay math. Implements INV-4 and INV-5."""
from __future__ import annotations
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

def now_utc() -> float:
    return datetime.now(timezone.utc).timestamp()

def age_hours(created_utc: float, now: float | None = None) -> float:
    now = now_utc() if now is None else now
    return (now - created_utc) / 3600.0

def decay_weight(age_h: float, half_life_hours: float) -> float:
    """Exponential recency weight; 1.0 at age 0, halves every half_life_hours."""
    if age_h <= 0:
        return 1.0
    return 0.5 ** (age_h / half_life_hours)

def within_window(age_h: float, lookback_hours: float) -> bool:
    return 0 <= age_h <= lookback_hours

def run_date(tz_name: str) -> str:
    """The calendar date in the target timezone (handles DST automatically)."""
    return datetime.now(ZoneInfo(tz_name)).strftime("%Y-%m-%d")
