from __future__ import annotations
import math
from collections import defaultdict
from radar.models import Mention, Signal
from radar import clock

def _accel_points(vel_24h) -> float:
    """Day-1-valid freshness driver for the composite: reward mention growth vs yesterday so
    breakouts outrank big-but-flat names even before a 90-day baseline exists. Capped so a
    tiny-base blip can't run away; None (no prior-day data — new to the tracker) gets a
    moderate fresh-arrival credit, with the volume tiebreaker separating new names."""
    if vel_24h is None:
        return 10.0
    return min(max(vel_24h, 0.0), 10.0) * 3.0          # 1× -> 3, 5× -> 15, capped at 30

def classify_state(velocity: float, surprise: float, baseline_mean: float) -> str:
    if baseline_mean <= 1e-9 and surprise >= 0:
        return "new"
    if surprise < -0.25 or velocity < 0.85:
        return "cooling"
    if velocity >= 1.5 and surprise > 0.5:
        return "hot"
    return "sustained"

def _finalize(ticker, weighted, mentions, distinct_authors, bonus_basis,
              subreddits, history, cfg, run_day, accel_pts=0.0) -> Signal:
    """Shared scoring core: given today's `weighted` magnitude for a ticker, measure
    it against the 90-day EMA baseline to produce velocity / surprise / composite /
    lifecycle state. Used by BOTH the raw-mention path (score_signals) and the
    ApeWisdom aggregate path (score_aggregates) so the anti-staleness math — and the
    INV-1..INV-8 invariants that pin it — are identical for either data source."""
    mean, std = history.baseline(ticker, before=run_day, days=cfg.history_days, alpha=cfg.ema_alpha)
    velocity = weighted / mean if mean > 1e-9 else float("inf") if weighted > 0 else 0.0
    if std > 1e-9:
        surprise = (weighted - mean) / std
    elif mean <= 1e-9:
        surprise = 1.0 if weighted > 0 else 0.0              # brand new (INV-8)
    else:
        surprise = 1.0 if weighted > mean else (-1.0 if weighted < mean else 0.0)
    # composite: 90-day surprise (bounded) once it exists + 24h acceleration (the day-1
    # freshness driver, via accel_pts) + a gentle, log-scaled volume tiebreaker. During
    # baseline burn-in surprise is a constant, so acceleration is what actually ranks names.
    bounded_surprise = max(-3.0, min(6.0, surprise))
    volume_pts = min(math.log10(max(bonus_basis, 1.0)), 4.0) * 1.5
    composite = bounded_surprise * 10 + accel_pts + volume_pts
    s = Signal(ticker=ticker, mentions=mentions, distinct_authors=distinct_authors,
               weighted_today=weighted, baseline_mean=mean, baseline_std=std,
               velocity=(0.0 if velocity == float("inf") else round(velocity, 2)),
               surprise=round(surprise, 2), score=round(composite, 2),
               subreddits=subreddits)
    s.velocity = velocity if velocity != float("inf") else 999.0
    s.state = classify_state(s.velocity, surprise, mean)
    return s

def score_aggregates(aggregates, history, cfg, run_day: str) -> list[Signal]:
    """Score ApeWisdom daily per-ticker mention aggregates against the 90-day EMA
    baseline. Today's magnitude is the raw mention count (no intraday decay or
    author data available from the aggregator); velocity, surprise, and lifecycle
    come from the same engine as the raw-mention path via _finalize."""
    min_mentions = cfg.noise_floor.min_mentions
    signals: list[Signal] = []
    for a in aggregates:
        if a.mentions < min_mentions:
            continue                                         # noise floor (aggregator pre-filters)
        vel24 = _compute_vel_24h(a.mentions, a.mentions_24h_ago)
        s = _finalize(a.ticker, float(a.mentions), mentions=a.mentions, distinct_authors=0,
                      bonus_basis=a.mentions, subreddits=[a.subreddit],
                      history=history, cfg=cfg, run_day=run_day, accel_pts=_accel_points(vel24))
        s.mentions_24h_ago = a.mentions_24h_ago
        s.vel_24h = vel24
        signals.append(s)
    signals.sort(key=lambda x: x.score, reverse=True)
    return signals

def _compute_vel_24h(mentions: int, prior: int) -> float | None:
    """Display velocity from ApeWisdom: mentions vs 24h ago. Meaningful on day 1
    (unlike the 90-day-baseline engine velocity, which is undefined on cold start).
    None means 'no prior-day data' -> the UI shows NEW."""
    if prior <= 0:
        return None
    return round(mentions / prior, 1)

def score_signals(mentions, history, cfg, now: float, run_day: str) -> list[Signal]:
    by: dict[str, list[Mention]] = defaultdict(list)
    for m in mentions:
        age = clock.age_hours(m.created_utc, now)
        if clock.within_window(age, cfg.lookback_hours):     # INV-4 cutoff
            by[m.ticker].append(m)

    # Per-author cap on the decay-weighted contribution. Defeats whale brigading:
    # one account spamming N posts can inflate `weighted` (and the volume bonus)
    # well past the distinct-author floor, landing a 2-person pump on the board.
    # Capping each author's summed weight to `max_author_weight` means a single
    # account counts like a bounded few, while broad signals (~1 post/author each
    # under the cap) are unaffected. Config-free default keeps cfg()-based tests
    # working (noise_floor may not carry the attribute).
    max_author_weight = float(getattr(cfg.noise_floor, "max_author_weight", 1.5))

    signals: list[Signal] = []
    for ticker, ms in by.items():
        authors = {m.author for m in ms if m.author and m.author != "[deleted]"}
        if len(ms) < cfg.noise_floor.min_mentions or len(authors) < cfg.noise_floor.min_distinct_authors:
            continue                                         # noise floor
        per_author: dict[str, float] = defaultdict(float)
        for m in ms:
            per_author[m.author] += clock.decay_weight(
                clock.age_hours(m.created_utc, now), cfg.half_life_hours)
        weighted = sum(min(w, max_author_weight) for w in per_author.values())
        # Volume bonus is keyed on DISTINCT AUTHORS, not raw mentions, so a whale
        # spamming duplicates cannot buy tiebreaker points (brigade defense).
        s = _finalize(ticker, weighted, mentions=len(ms), distinct_authors=len(authors),
                      bonus_basis=len(authors), subreddits=sorted({m.subreddit for m in ms}),
                      history=history, cfg=cfg, run_day=run_day)
        signals.append(s)

    signals.sort(key=lambda x: x.score, reverse=True)
    return signals

def top_signals(signals, n: int):
    return sorted(signals, key=lambda x: x.score, reverse=True)[:n]
