from __future__ import annotations
import math
from datetime import date

BREAKOUT_STATES = {"new", "hot"}     # what counts as "it popped"
ALIVE_STATES = {"sustained", "hot"}  # still elevated today (not new, not cooling)


def _breakout_days(history, ticker, run_day, lookback_days):
    """Ordinals of prior days (within the lookback window, excluding run_day) on
    which this ticker's recorded state was new/hot."""
    hist = history.days_for(ticker)
    run_ord = date.fromisoformat(run_day).toordinal()
    cutoff = run_ord - lookback_days
    return [o for d, rec in hist.items()
            for o in (date.fromisoformat(d).toordinal(),)
            if cutoff <= o < run_ord and rec.get("state") in BREAKOUT_STATES]


def _rank_key(s, velocity_cap):
    return min(s.velocity, velocity_cap) * math.log10(max(s.mentions, 10))


def still_running(signals, history, run_day, board, cfg):
    """Names that broke out (new/hot) within the lookback window, are still alive
    today (sustained/hot), and have fallen off the top-N board. Ranked by
    min(velocity, cap) * log10(mentions), truncated to max_items. Each returned
    Signal gets `days_running` = run_day minus its most recent breakout day."""
    sr = getattr(cfg, "still_running", None)
    lookback_days = int(getattr(sr, "lookback_days", 3))
    max_items = int(getattr(sr, "max_items", 5))
    velocity_cap = float(getattr(sr, "velocity_cap", 10))
    run_ord = date.fromisoformat(run_day).toordinal()
    on_board = {s.ticker for s in board}

    out = []
    for s in signals:
        if s.ticker in on_board or s.state not in ALIVE_STATES:
            continue
        days = _breakout_days(history, s.ticker, run_day, lookback_days)
        if not days:
            continue
        s.days_running = run_ord - max(days)   # since the MOST RECENT breakout
        out.append(s)
    out.sort(key=lambda s: _rank_key(s, velocity_cap), reverse=True)
    return out[:max_items]
