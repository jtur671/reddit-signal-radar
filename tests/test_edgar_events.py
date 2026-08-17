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
    assert set(evaluated) == {"acc1", "acc2"}       # non-hits advance the cursor too
    signals2, _ = m.fetch_new({"acc1", "acc2"})
    assert signals2 == []                            # dedup works


def test_parse_hits_id_is_the_accession_number():
    # EFTS indexes every FILE in a submission separately -- the primary document AND
    # each exhibit. Measured 2026-08-10..14: S-3,S-3ASR returned 100 hits for only 35
    # filings, one filing yielding SIX. Keying on "<accession>:<filename>" would alert
    # once per exhibit. The live 8-K monitor is accidentally immune (ratio exactly 1.0)
    # because "material definitive agreement" appears only in the primary document.
    raw = {"hits": {"hits": [
        {"_id": "0001213900-26-087891:form-s3.htm",
         "_source": {"ciks": ["0000012345"], "display_names": ["Acme  (ACME)  (CIK 1)"],
                     "file_date": "2026-08-12"}},
        {"_id": "0001213900-26-087891:ex-5_1.htm",
         "_source": {"ciks": ["0000012345"], "display_names": ["Acme  (ACME)  (CIK 1)"],
                     "file_date": "2026-08-12"}},
    ]}}
    rows = parse_hits(raw)
    assert [r["id"] for r in rows] == ["0001213900-26-087891"] * 2
    assert rows[0]["url"].endswith("form-s3.htm")     # url still needs the filename


def test_fetch_new_emits_one_signal_per_filing(monkeypatch):
    import radar.monitors.edgar_events as ee
    six_files = {"hits": {"hits": [
        {"_id": f"acc1:ex-{i}.htm",
         "_source": {"ciks": ["1"], "display_names": ["Watched Co  (WTCH)  (CIK 1)"],
                     "file_date": "2026-08-12"}} for i in range(6)]}}
    monkeypatch.setattr(ee, "_fetch_json", lambda url, ua: six_files)
    m = EdgarEventsMonitor(phrases=["offering"], user_agent="t", watch=lambda: {"WTCH"})
    signals, evaluated = m.fetch_new(set())
    assert len(signals) == 1                      # six files, one filing, one alert
    assert evaluated == ["acc1"]


def test_fetch_new_honours_a_legacy_accession_colon_filename_cursor(monkeypatch):
    # data/edgar8k_seen.json holds "<accession>:<filename>" entries written before this
    # change. Without normalisation the first tick after deploy re-alerts on filings
    # already seen.
    import radar.monitors.edgar_events as ee
    fixture = {"hits": {"hits": [
        {"_id": "acc1:doc.htm",
         "_source": {"ciks": ["1"], "display_names": ["Watched Co  (WTCH)  (CIK 1)"],
                     "file_date": "2026-08-12"}}]}}
    monkeypatch.setattr(ee, "_fetch_json", lambda url, ua: fixture)
    m = EdgarEventsMonitor(phrases=["x"], user_agent="t", watch=lambda: {"WTCH"})
    signals, _ = m.fetch_new({"acc1:some-other-file.htm"})
    assert signals == []


def test_efts_url_carries_configured_forms_and_phrase(monkeypatch):
    import radar.monitors.edgar_events as ee
    seen_urls = []
    def fake(url, ua):
        seen_urls.append(url)
        return {"hits": {"hits": []}}
    monkeypatch.setattr(ee, "_fetch_json", fake)
    m = EdgarEventsMonitor(phrases=["at the market offering"], user_agent="t",
                           watch=lambda: set(), key="dilution", forms="424B5")
    m.fetch_new(set())
    assert "forms=424B5" in seen_urls[0]
    assert "at%20the%20market%20offering" in seen_urls[0]


def test_comma_separated_forms_are_url_encoded(monkeypatch):
    # forms= accepts several codes; S-3,S-3ASR is additive (verified 2026-08-17).
    import radar.monitors.edgar_events as ee
    seen_urls = []
    monkeypatch.setattr(ee, "_fetch_json",
                        lambda url, ua: (seen_urls.append(url), {"hits": {"hits": []}})[1])
    m = EdgarEventsMonitor(phrases=["offering"], user_agent="t", watch=lambda: set(),
                           key="shelf", forms="S-3,S-3ASR")
    m.fetch_new(set())
    assert "forms=S-3%2CS-3ASR" in seen_urls[0] or "forms=S-3,S-3ASR" in seen_urls[0]


def test_defaults_reproduce_todays_8k_monitor(monkeypatch):
    import radar.monitors.edgar_events as ee
    seen_urls = []
    monkeypatch.setattr(ee, "_fetch_json",
                        lambda url, ua: (seen_urls.append(url), {"hits": {"hits": []}})[1])
    m = EdgarEventsMonitor(phrases=["material definitive agreement"], user_agent="t",
                           watch=lambda: set())
    m.fetch_new(set())
    assert m.key == "edgar8k" and m.label == "📢 8-K Event"
    assert m.card_style == "insider" and m.direction == "neutral"
    assert m.watch_days == 7 and "forms=8-K" in seen_urls[0]


def test_identity_fields_are_configurable():
    m = EdgarEventsMonitor(phrases=["x"], user_agent="t", watch=lambda: set(),
                           key="dilution", label="💧 Dilution", card_style="trump",
                           direction="bearish", forms="424B5", watch_days=90)
    assert (m.key, m.label, m.card_style, m.direction) == (
        "dilution", "💧 Dilution", "trump", "bearish")


def test_watch_days_is_passed_to_the_default_watch(tmp_path, monkeypatch):
    import json
    import radar.monitors.edgar_events as ee
    hist = tmp_path / "history.json"
    hist.write_text(json.dumps({
        "RECENT": {"2026-08-16": {"raw": 5}},
        "OLD":    {"2026-06-20": {"raw": 5}}}))
    narrow = ee.active_tickers(str(hist), days=7,  today="2026-08-17")
    wide   = ee.active_tickers(str(hist), days=90, today="2026-08-17")
    assert narrow == {"RECENT"}
    assert wide == {"RECENT", "OLD"}       # the 90-day gate is what catches pre-discovery names
