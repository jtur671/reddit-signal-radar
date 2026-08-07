"""Transparent composite score — every component published beside the blend.

The consuming trading bot should trust the COMPONENTS more than the single number:
weights start as documented heuristics (config.yaml `composite.weights`) and get
recalibrated from measured ICs once backtest.json's power block turns sufficient
(a config change, not a code change). None components (source down / name uncovered)
are excluded with weight renormalization, and the weights actually used are published.

Component semantics: velocity = board-relative score percentile; direction = Tradestie
bullish share; engagement = upvotes-per-mention proxy; short_pressure = board-relative
short-ratio percentile; options = UOA flag (100) vs covered-but-quiet (50); events =
fresh monitor-alert involvement (any monitor, 0/100); cramer_inverse = inverted Mad
Money call (fade-the-call mapping)."""
from __future__ import annotations

CRAMER_INVERSE = {"sell_avoid": 100.0, "caution_concern": 80.0,
                  "wait_hold_neutral": 50.0, "buy_on_pullback": 40.0,
                  "mild_buy": 30.0, "buy": 20.0, "strong_buy": 0.0}

DEFAULT_WEIGHTS = {"velocity": 0.30, "direction": 0.15, "engagement": 0.10,
                   "short_pressure": 0.15, "options": 0.10, "events": 0.10,
                   "cramer_inverse": 0.10}


def percentile_rank(value, population) -> float | None:
    """Share of population <= value, 0-100. None on empty population."""
    pop = [p for p in population if p is not None]
    if not pop or value is None:
        return None
    return round(100.0 * sum(1 for p in pop if p <= value) / len(pop), 1)


def components_for(s, board, ts_bull, alert_tickers) -> dict:
    scores = [b.score for b in board]
    shorts = [b.short_ratio for b in board if b.short_ratio is not None]
    return {
        "velocity": percentile_rank(s.score, scores),
        "direction": (float(ts_bull) if ts_bull is not None else None),
        "engagement": (float(s.pct_bull) if s.pct_bull else None),
        "short_pressure": (percentile_rank(s.short_ratio, shorts)
                           if s.short_ratio is not None else None),
        "options": (100.0 if s.uoa else 50.0) if (s.uoa or s.pc_ratio is not None) else None,
        "events": 100.0 if s.ticker in alert_tickers else 0.0,
        "cramer_inverse": CRAMER_INVERSE.get(s.cramer) if s.cramer else None,
    }


def blend(components: dict, weights: dict) -> tuple[int | None, dict]:
    """Weighted mean over non-None components with renormalized weights.
    Returns (0-100 int or None, weights actually used summing to 1.0)."""
    live = {k: v for k, v in components.items()
            if v is not None and weights.get(k, 0) > 0}
    total_w = sum(weights[k] for k in live)
    if not live or total_w <= 0:
        return None, {}
    used = {k: weights[k] / total_w for k in live}
    score = sum(live[k] * used[k] for k in live)
    return int(round(max(0.0, min(100.0, score)))), used
