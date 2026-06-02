from __future__ import annotations
from collections import defaultdict
from radar.models import Mention, Signal
from radar import clock

def classify_state(velocity: float, surprise: float, baseline_mean: float) -> str:
    if baseline_mean <= 1e-9 and surprise >= 0:
        return "new"
    if surprise < -0.25 or velocity < 0.85:
        return "cooling"
    if velocity >= 1.5 and surprise > 0.5:
        return "hot"
    return "sustained"

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
        mean, std = history.baseline(ticker, before=run_day, days=cfg.history_days, alpha=cfg.ema_alpha)
        velocity = weighted / mean if mean > 1e-9 else float("inf") if weighted > 0 else 0.0
        if std > 1e-9:
            surprise = (weighted - mean) / std
        elif mean <= 1e-9:
            surprise = 1.0 if weighted > 0 else 0.0          # brand new (INV-8)
        else:
            surprise = 1.0 if weighted > mean else (-1.0 if weighted < mean else 0.0)
        # composite: surprise dominates (bounded), volume is a gentle tiebreaker.
        # The volume bonus is keyed on DISTINCT AUTHORS, not raw mentions, so a
        # whale spamming duplicates cannot buy tiebreaker points (brigade defense).
        bounded_surprise = max(-3.0, min(6.0, surprise))
        composite = bounded_surprise * 10 + min(len(authors), 50) * 0.2
        s = Signal(ticker=ticker, mentions=len(ms), distinct_authors=len(authors),
                   weighted_today=weighted, baseline_mean=mean, baseline_std=std,
                   velocity=(0.0 if velocity == float("inf") else round(velocity, 2)),
                   surprise=round(surprise, 2), score=round(composite, 2),
                   subreddits=sorted({m.subreddit for m in ms}))
        s.velocity = velocity if velocity != float("inf") else 999.0
        s.state = classify_state(s.velocity, surprise, mean)
        signals.append(s)

    signals.sort(key=lambda x: x.score, reverse=True)
    return signals

def top_signals(signals, n: int):
    return sorted(signals, key=lambda x: x.score, reverse=True)[:n]
