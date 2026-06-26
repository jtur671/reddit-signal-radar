import pathlib
from radar.monitors import congress
from radar.monitors.congress import CongressMonitor

FIX = pathlib.Path("tests/fixtures/congress_trades.json").read_text()
WATCH = "data/congress_watch.yaml"


def _mon(min_usd=250000):
    return CongressMonitor(watch_path=WATCH, min_usd=min_usd)


def test_alerts_notable_and_big_buys_only(monkeypatch):
    monkeypatch.setattr(congress, "_http_get", lambda url, ua: FIX)
    signals, evaluated = _mon().fetch_new(set())
    assert len(evaluated) == 6                       # every disclosure recorded for dedup
    tickers = [s.tickers[0] for s in signals]
    # notable-first then largest $: Pelosi(INTC,$1M+) > Crenshaw(NVDA, notable small) > Smith(AAPL,$250k+)
    # dropped: Doe(small non-notable), Roe(Sale), Poe(no ticker)
    assert tickers == ["INTC", "NVDA", "AAPL"]
    assert "Nancy Pelosi (D-CA)" in signals[0].summary
    assert "$1,000,001" in signals[0].summary and "INTC" in signals[0].summary
    assert signals[0].link_text == "View disclosure ↗"
    assert signals[0].published == "2026-06-23T00:00:00Z"
    assert signals[0].url.endswith("p1.pdf")


def test_notable_small_buy_alerts_but_nonnotable_small_does_not(monkeypatch):
    monkeypatch.setattr(congress, "_http_get", lambda url, ua: FIX)
    signals, _ = _mon().fetch_new(set())
    summaries = " ".join(s.summary for s in signals)
    assert "Crenshaw" in summaries                   # notable, $1k buy -> still alerts
    assert "Jane Doe" not in summaries               # non-notable $1k buy -> filtered


def test_dedups_against_seen(monkeypatch):
    monkeypatch.setattr(congress, "_http_get", lambda url, ua: FIX)
    m = _mon()
    _, evaluated = m.fetch_new(set())
    signals2, _ = m.fetch_new(set(evaluated))
    assert signals2 == []


def test_surname_matching_handles_first_name_variants():
    m = _mon(min_usd=10**12)
    assert m._is_notable("Daniel Crenshaw")          # watchlist says "Dan Crenshaw"
    assert m._is_notable("Nancy Pelosi,")            # trailing comma in the real feed
    assert not m._is_notable("Some Random Member")


def test_validate_is_identity():
    from radar.monitors.base import Signal
    m = _mon(min_usd=1)
    sigs = [Signal(tickers=["AAPL"], summary="x", url="", published="", monitor_key="congress")]
    assert m.validate(sigs) is sigs
