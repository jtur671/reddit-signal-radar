"""Regression tests for bug-bounty findings (Phase 15 QA)."""
from radar.models import Mention, Item
from radar.score import score_signals
from radar.history import History
from radar.universe import Universe
from radar.extract import extract_mentions

NOW = 3_000_000.0


def men(t, age_h, a):
    return Mention(t, f"{t}{a}{age_h}", "wsb", a, NOW - age_h * 3600, "x")


def cfg():
    c = type("C", (), {})()
    c.half_life_hours = 24
    c.lookback_hours = 48
    c.top_n = 15
    c.ema_alpha = 0.3
    c.history_days = 90
    c.noise_floor = type("N", (), {"min_mentions": 3, "min_distinct_authors": 2,
                                   "max_author_weight": 1.5})
    return c


def test_bounty1_silent_then_comeback_reads_fresh(tmp_path):
    # A one-time spike, then 40 silent days (which record nothing), then a genuine
    # comeback. The comeback must NOT be buried as 'cooling' against the stale peak:
    # silent-day zero-fill must have decayed the baseline away.
    p = tmp_path / "h.json"; p.write_text("{}")
    h = History.load(p)
    spike = [men("SPCE", 1, f"u{i}") for i in range(60)]
    s0 = next(x for x in score_signals(spike, h, cfg(), NOW, "2026-06-01") if x.ticker == "SPCE")
    h.record("2026-06-01", "SPCE", s0.weighted_today, s0.mentions, s0.distinct_authors,
             70, s0.score, s0.state)
    later = NOW + 40 * 86400
    # comeback mentions must be fresh relative to `later`, not the original NOW
    comeback = [Mention("SPCE", f"c{i}", "wsb", f"c{i}", later - 3600, "x") for i in range(6)]
    s2 = next(x for x in score_signals(comeback, h, cfg(), later, "2026-07-11") if x.ticker == "SPCE")
    assert s2.baseline_mean < 1.0                      # stale peak decayed away
    assert s2.state in ("new", "hot", "sustained")     # NOT suppressed as cooling
    assert s2.velocity > 1.0


def test_bounty2_common_prose_words_do_not_trend():
    # Real universe + expanded stoplist: ordinary emphatic prose ("SO", "GO", "ON")
    # must not mint signals just because those words are also listed tickers.
    uni = Universe.load("data/universe.txt", "data/stoplist.txt")
    items = [Item(f"i{i}", "comment", "wsb", f"u{i}", NOW - 3600,
                  "SO bullish, GO GO GO, ON to the moon", 1, "/p") for i in range(6)]
    ms = extract_mentions(items, uni)
    assert {m.ticker for m in ms} == set()


def test_bounty2_fake_cashtag_rejected_real_accepted():
    # Cashtags must be real symbols: $FAKE/$ZZZZZ are rejected, but $AI is accepted
    # even though AI is a stopword (cashtags bypass the stoplist, not the universe).
    uni = Universe(symbols={"IREN", "AI"}, stopwords={"AI"})
    it = Item("i", "comment", "wsb", "u", NOW - 3600, "$IREN $FAKE $AI $ZZZZZ", 1, "/p")
    got = {m.ticker for m in extract_mentions([it], uni)}
    assert "IREN" in got and "AI" in got
    assert "FAKE" not in got and "ZZZZZ" not in got
