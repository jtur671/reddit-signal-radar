from radar.models import Mention
from radar.score import score_signals, classify_state
from radar import clock

NOW = 1_000_000.0
def men(ticker, age_h, author):
    return Mention(ticker=ticker, item_id=f"{ticker}{author}{age_h}", subreddit="wsb",
                   author=author, created_utc=NOW - age_h*3600, text="x")

class FakeHist:
    def __init__(self, table): self.table = table
    def baseline(self, t, before, days, alpha): return self.table.get(t, (0.0, 0.0))

def cfg():
    class C: pass
    c = C(); c.half_life_hours=24; c.lookback_hours=48; c.top_n=15
    c.ema_alpha=0.3; c.history_days=90
    c.noise_floor = type("N",(),{"min_mentions":3,"min_distinct_authors":2})
    return c

def test_noise_floor_filters_low_author_spam():
    ms = [men("PUMP", 1, "spammer") for _ in range(10)]
    sigs = score_signals(ms, FakeHist({}), cfg(), now=NOW, run_day="2026-06-01")
    assert all(s.ticker != "PUMP" for s in sigs)

def test_recency_weighting_prefers_fresh():
    fresh = [men("AAA", 1, f"u{i}") for i in range(5)]
    old   = [men("BBB", 40, f"v{i}") for i in range(5)]
    sigs = {s.ticker: s for s in score_signals(fresh+old, FakeHist({}), cfg(), NOW, "2026-06-01")}
    assert sigs["AAA"].weighted_today > sigs["BBB"].weighted_today

def test_zero_baseline_no_divide_by_zero_and_marks_new():
    ms = [men("NEW", 1, f"u{i}") for i in range(5)]
    sigs = score_signals(ms, FakeHist({"NEW": (0.0, 0.0)}), cfg(), NOW, "2026-06-01")
    s = next(x for x in sigs if x.ticker == "NEW")
    assert s.surprise == s.surprise  # not NaN
    assert s.state == "new"

def test_constant_level_decays_to_sustained():
    # Constant level: baseline mean == today's actual decay-weighted total, so
    # velocity ~1, surprise ~0 -> sustained (INV-3). Compute the baseline with the
    # same decay the engine uses (age 1h -> ~0.9715 each, not a naive 1.0) so the
    # "today == baseline" condition holds honestly.
    ms = [men("OLDIE", 1, f"u{i}") for i in range(5)]
    weighted = sum(clock.decay_weight(1.0, 24) for _ in ms)  # honest constant level
    sigs = score_signals(ms, FakeHist({"OLDIE": (weighted, 0.5)}), cfg(), NOW, "2026-06-01")
    s = next(x for x in sigs if x.ticker == "OLDIE")
    assert abs(s.velocity - 1.0) < 0.2 and s.state in ("sustained","hot")

from radar.score import top_signals
def test_top_n_caps_board():
    sigs = [type("S",(),{"score":i})() for i in range(40)]
    assert len(top_signals(sigs, 15)) == 15


from radar.score import score_aggregates
from radar.apewisdom import Aggregate

def _agg(t, m, sub="all-stocks"):
    return Aggregate(ticker=t, name=t, mentions=m, mentions_24h_ago=0, upvotes=m * 10, subreddit=sub)

def test_aggregates_noise_floor_and_new_state():
    rows = [_agg("NEW", 100), _agg("TINY", 2)]
    sigs = {s.ticker: s for s in score_aggregates(rows, FakeHist({"NEW": (0.0, 0.0)}), cfg(), "2026-06-01")}
    assert "TINY" not in sigs                  # below min_mentions
    assert sigs["NEW"].state == "new" and sigs["NEW"].weighted_today == 100.0
    assert sigs["NEW"].surprise == sigs["NEW"].surprise   # not NaN

def test_aggregates_velocity_vs_baseline():
    s = score_aggregates([_agg("AAA", 50)], FakeHist({"AAA": (25.0, 5.0)}), cfg(), "2026-06-01")[0]
    assert abs(s.velocity - 2.0) < 1e-6        # 50 / 25
