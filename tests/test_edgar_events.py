import json, pathlib
from radar.monitors.edgar_events import (EdgarEventsMonitor, parse_hits, ticker_from_display,
                                         active_tickers)

def test_ticker_from_display():
    assert ticker_from_display("Acme Corp  (ACME)  (CIK 0001234567)") == "ACME"
    assert ticker_from_display("No Ticker Holdings  (CIK 0009999999)") == ""
    assert ticker_from_display("") == ""

def test_ticker_from_display_multi_ticker():
    # Real EDGAR display_names from tests/fixtures/efts_8k.json: dual-class/unit+warrant
    # issuers list multiple tickers before "(CIK ...)" — the FIRST one is the primary.
    assert ticker_from_display(
        "AMERICAN REBEL HOLDINGS INC  (AREB, AREBW)  (CIK 0001648087)") == "AREB"
    assert ticker_from_display(
        "Liberty Global Ltd.  (LBTYA, LBTYB, LBTYK)  (CIK 0001570585)") == "LBTYA"

def test_parse_hits_from_fixture():
    raw = json.loads(pathlib.Path("tests/fixtures/efts_8k.json").read_text())
    rows = parse_hits(raw)
    assert isinstance(rows, list) and rows
    r = rows[0]
    assert set(r) >= {"id", "ticker", "display", "file_date", "url"}

def test_parse_hits_never_raises():
    for raw in (None, {}, {"hits": None}, {"hits": {"hits": [{"_id": "x"}]}}):
        assert isinstance(parse_hits(raw), list)

def test_active_tickers(tmp_path):
    hist = tmp_path / "history.json"
    hist.write_text(json.dumps({
        "AAA": {"2026-08-06": {"weighted": 1, "raw": 5, "authors": 0, "pct_bull": 0,
                                "score": 1.0, "state": "new"}},
        "OLD": {"2026-01-01": {"weighted": 1, "raw": 5, "authors": 0, "pct_bull": 0,
                                "score": 1.0, "state": "new"}}}))
    act = active_tickers(str(hist), days=7, today="2026-08-07")
    assert "AAA" in act and "OLD" not in act
    assert active_tickers(str(tmp_path / "missing.json"), days=7, today="2026-08-07") == set()

def test_active_tickers_malformed_shapes_never_raise(tmp_path):
    # A malformed-but-valid-JSON history.json (list / null / number) must not crash the
    # fleet — run_fleet has no try/except around fetch_new, so one bad file kills all 5.
    for payload in ("[]", "null", "123"):
        hist = tmp_path / "history.json"
        hist.write_text(payload)
        assert active_tickers(str(hist), days=7, today="2026-08-07") == set()

def test_seen_cap_matches_edgar_monitor():
    # Three phrases over the rolling window can exceed base.py's default seen_cap of
    # 200 (one phrase alone returned 72 in-window ids) -> evicted ids re-evaluate every
    # tick (cursor churn + duplicate alerts). Must match EdgarMonitor's 5000.
    m = EdgarEventsMonitor(phrases=["x"], user_agent="t", watch=lambda: set())
    assert m.seen_cap == 5000

def test_monitor_filters_to_watchset_and_advances_cursor(monkeypatch):
    import radar.monitors.edgar_events as ee
    fixture = {"hits": {"hits": [
        {"_id": "acc1:doc.htm", "_source": {"display_names": ["Watched Co  (WTCH)  (CIK 1)"],
                                             "file_date": "2026-08-07"}},
        {"_id": "acc2:doc.htm", "_source": {"display_names": ["Ignored Co  (IGNR)  (CIK 2)"],
                                             "file_date": "2026-08-07"}},
    ]}}
    monkeypatch.setattr(ee, "_fetch_json", lambda url, ua: fixture)
    m = EdgarEventsMonitor(phrases=["material definitive agreement"], user_agent="t",
                            watch=lambda: {"WTCH"}, max_age_h=24)
    signals, evaluated = m.fetch_new(set())
    assert len(signals) == 1 and signals[0].tickers == ["WTCH"]
    assert set(evaluated) == {"acc1:doc.htm", "acc2:doc.htm"}   # non-hits advance the cursor too
    signals2, _ = m.fetch_new({"acc1:doc.htm", "acc2:doc.htm"})
    assert signals2 == []                                       # dedup works
