import json, pathlib
from radar.cramer import parse_sentiments, fetch_cramer

def _raw(mentions_by_ticker):
    return {"stocks": {t: {"company": t, "mentions": ms}
                       for t, ms in mentions_by_ticker.items()}}

def test_parse_takes_most_recent_within_window():
    raw = _raw({"NVDA": [
        {"date": "2026-07-01", "sentiment": "sell_avoid"},
        {"date": "2026-08-01", "sentiment": "strong_buy"},
    ]})
    out = parse_sentiments(raw, today="2026-08-07", max_age_days=30)
    assert out == {"NVDA": "strong_buy"}

def test_parse_drops_stale_and_garbage():
    raw = _raw({"OLD": [{"date": "2026-01-01", "sentiment": "buy"}],
                "BAD": [{"sentiment": "buy"}, "garbage"],
                "EMPTY": []})
    assert parse_sentiments(raw, today="2026-08-07", max_age_days=30) == {}
    for r in (None, {}, {"stocks": "x"}):
        assert parse_sentiments(r, today="2026-08-07", max_age_days=30) == {}

def test_parse_fixture():
    raw = json.loads(pathlib.Path("tests/fixtures/cramer_sentiments.json").read_text())
    out = parse_sentiments(raw, today="2026-08-07", max_age_days=3650)  # wide window: shape test
    assert out and all(isinstance(v, str) for v in out.values())

def test_fetch_vendors_snapshot_and_falls_back(tmp_path, monkeypatch):
    import radar.cramer as cr
    from types import SimpleNamespace
    snap = tmp_path / "cramer_snapshot.json"
    cfg = SimpleNamespace(cramer=SimpleNamespace(
        url="http://x", max_age_days=30, snapshot_path=str(snap)))
    live = _raw({"NVDA": [{"date": "2026-08-01", "sentiment": "strong_buy"}]})
    monkeypatch.setattr(cr, "_get_json", lambda *a, **k: live)
    assert fetch_cramer(cfg, "2026-08-07") == {"NVDA": "strong_buy"}
    assert snap.exists()                                   # vendored
    monkeypatch.setattr(cr, "_get_json", lambda *a, **k: None)
    assert fetch_cramer(cfg, "2026-08-07") == {"NVDA": "strong_buy"}   # snapshot fallback

def test_fetch_total_failure(tmp_path, monkeypatch):
    import radar.cramer as cr
    from types import SimpleNamespace
    cfg = SimpleNamespace(cramer=SimpleNamespace(
        url="http://x", max_age_days=30, snapshot_path=str(tmp_path / "none.json")))
    monkeypatch.setattr(cr, "_get_json", lambda *a, **k: None)
    assert fetch_cramer(cfg, "2026-08-07") == {}
