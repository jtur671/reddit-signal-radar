import json, pathlib
from radar.tradestie import parse_feed, fetch_wsb, to_aggregates, bull_pct, TsRow
from radar.history import History

def test_parse_feed_from_live_fixture():
    raw = json.loads(pathlib.Path("tests/fixtures/tradestie.json").read_text())
    rows = parse_feed(raw)
    assert len(rows) >= 10                                  # top-50 feed
    r = rows[0]
    assert r.ticker and r.sentiment in ("Bullish", "Bearish")
    assert isinstance(r.score, float) and isinstance(r.comments, int)

def test_parse_feed_never_raises_on_garbage():
    for raw in [None, {}, [], "x", [{"ticker": None}], [{"no_of_comments": "x"}], ["garbage"]]:
        assert isinstance(parse_feed(raw), list)

def test_bull_pct_maps_and_clamps():
    assert bull_pct(0.0) == 50.0
    assert bull_pct(1.0) == 100.0 and bull_pct(-1.0) == 0.0
    assert bull_pct(9.9) == 100.0 and bull_pct(-9.9) == 0.0  # out-of-range clamps

def test_to_aggregates_fallback_shape():
    rows = [TsRow(ticker="GME", sentiment="Bullish", score=0.2, comments=150)]
    aggs = to_aggregates(rows)
    assert aggs[0].ticker == "GME" and aggs[0].mentions == 150
    assert aggs[0].subreddit == "wallstreetbets" and aggs[0].mentions_24h_ago == 0

def test_fetch_wsb_fail_soft(monkeypatch):
    import radar.tradestie as ts
    monkeypatch.setattr(ts, "_get", lambda *a, **k: None)
    from types import SimpleNamespace
    cfg = SimpleNamespace(tradestie=SimpleNamespace(url="http://x", user_agent="t", max_retries=1, sleep_seconds=0))
    assert ts.fetch_wsb(cfg) == []                          # never raises

def test_history_annotate_merges_existing_only(tmp_path):
    h = History.load(tmp_path / "h.json")
    h.record("2026-08-08", "GME", 5.0, 5, 0, 0.0, 30.0, "hot")
    assert h.annotate("2026-08-08", "GME", ts_bull=61.0, ts_comments=150) is True
    assert h.data["GME"]["2026-08-08"]["ts_bull"] == 61.0
    assert h.data["GME"]["2026-08-08"]["weighted"] == 5.0    # core fields intact
    assert h.annotate("2026-08-08", "ZZZ", ts_bull=1.0) is False   # no record -> no create
    assert "ZZZ" not in h.data                               # baseline() safety: never a
                                                             # day-record without 'weighted'
