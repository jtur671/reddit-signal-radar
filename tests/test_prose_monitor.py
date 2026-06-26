# tests/test_prose_monitor.py
import pathlib
from radar import trump
from radar.monitors.prose import ProseMonitor

FIX = pathlib.Path("tests/fixtures/trumpstruth.xml").read_text()


def _trump_monitor():
    return ProseMonitor(
        key="trump", label="⚠ Trump Alert", feed_url="http://feed",
        watch_map_path="data/trump_watch.yaml", card_style="trump",
        source_context="A Truth Social post by Donald Trump",
        link_text="Truth Social post ↗", max_age_h=48)


def test_fetch_new_returns_signals_and_all_evaluated_ids(monkeypatch):
    monkeypatch.setattr(trump, "fetch_rss", lambda *a, **k: trump.parse_rss(FIX))
    m = _trump_monitor()
    signals, evaluated = m.fetch_new(set())
    tickers = {t for s in signals for t in s.tickers}
    assert {"TSLA", "BTC", "DJT"} <= tickers
    assert len(evaluated) == 4                       # every post recorded for dedup
    assert all(s.monitor_key == "trump" for s in signals)


def test_fetch_new_dedups_against_seen(monkeypatch):
    monkeypatch.setattr(trump, "fetch_rss", lambda *a, **k: trump.parse_rss(FIX))
    m = _trump_monitor()
    _, evaluated = m.fetch_new(set())
    signals2, _ = m.fetch_new(set(evaluated))
    assert signals2 == []                            # all seen -> nothing new


def test_validate_drops_rejected(monkeypatch):
    import radar.monitors.prose as prose
    from radar.monitors.base import Signal
    monkeypatch.setattr(prose, "validate_prose_tickers", lambda text, cands, ctx: {"TSLA"})
    m = _trump_monitor()
    sigs = [Signal(tickers=["TSLA", "ICE"], summary="$TSLA", url="", published="",
                   monitor_key="trump")]
    kept = m.validate(sigs)
    assert len(kept) == 1 and kept[0].tickers == ["TSLA"]


def test_validate_drops_signal_with_no_survivor(monkeypatch):
    import radar.monitors.prose as prose
    from radar.monitors.base import Signal
    monkeypatch.setattr(prose, "validate_prose_tickers", lambda text, cands, ctx: set())
    m = _trump_monitor()
    sigs = [Signal(tickers=["ICE"], summary="ICE raids", url="", published="",
                   monitor_key="trump")]
    assert m.validate(sigs) == []
