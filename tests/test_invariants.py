"""Anti-staleness invariants. See spec §10.1."""
from radar.models import Mention
from radar.score import score_signals
from radar.history import History
from radar import clock
import pathlib

NOW = 2_000_000.0
def men(t, age_h, a): return Mention(t, f"{t}{a}{age_h}", "wsb", a, NOW-age_h*3600, "x")
def cfg():
    c = type("C",(),{})(); c.half_life_hours=24; c.lookback_hours=48; c.top_n=15
    c.ema_alpha=0.3; c.history_days=90
    c.noise_floor=type("N",(),{"min_mentions":3,"min_distinct_authors":2}); return c

def test_INV1_silent_ticker_decays_off_board(tmp_path):
    """A ticker that spikes once then goes quiet must DECAY, not freeze at its peak.
    (1) While silent it is off the board entirely; (2) silent days record nothing
    (as the real pipeline does), so its baseline decays toward zero day by day rather
    than staying frozen at the spike for the whole window."""
    p = tmp_path/"h.json"; p.write_text("{}"); h = History.load(p)
    ms = [men("SPCE", 1, f"u{i}") for i in range(60)]
    s0 = next(x for x in score_signals(ms, h, cfg(), NOW, "2026-06-01") if x.ticker=="SPCE")
    h.record("2026-06-01","SPCE",s0.weighted_today,s0.mentions,s0.distinct_authors,70,s0.score,s0.state)
    assert s0.state == "new"
    # (1) Silent days -> not on the board at all (no carry-forward).
    for i, day in enumerate(["2026-06-02","2026-06-03","2026-06-04"], 1):
        sigs = score_signals([], h, cfg(), NOW + i*86400, day)
        assert all(x.ticker != "SPCE" for x in sigs)
    # (2) After 10 silent days the baseline has decayed well below the spike (zero-fill),
    #     so any later flare-up is judged against a fresh baseline, not the stale peak.
    mean, _ = h.baseline("SPCE", before="2026-06-11", days=90, alpha=cfg().ema_alpha)
    assert 0.0 < mean < s0.weighted_today * 0.5

def test_INV4_old_content_zero_weight():
    ms = [men("OLD", 60, f"u{i}") for i in range(10)]   # all > 48h
    assert score_signals(ms, History("x",{}), cfg(), NOW, "2026-06-01") == []

def test_INV7_empty_corpus_empty_board():
    assert score_signals([], History("x",{}), cfg(), NOW, "2026-06-01") == []

def test_INV8_single_sample_history_no_crash(tmp_path):
    p=tmp_path/"h.json"; p.write_text("{}"); h=History.load(p)
    h.record("2026-05-31","AAA",5,5,5,50,1,"hot")       # one prior day -> std=0
    ms=[men("AAA",1,f"u{i}") for i in range(5)]
    sigs=score_signals(ms,h,cfg(),NOW,"2026-06-01")
    s=next(x for x in sigs if x.ticker=="AAA")
    assert s.surprise==s.surprise and s.score==s.score   # no NaN
