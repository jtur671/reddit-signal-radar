import pathlib
from radar import trump
from radar.monitors.events import RssEventMonitor

FEED = pathlib.Path("tests/fixtures/fed_monetary.xml").read_text()


def _fed():
    return RssEventMonitor(key="fed", label="🏛 Fed / FOMC", feed_url="http://f",
                           tickers=["SPY", "TLT", "IWM", "GLD"], card_style="fed",
                           link_text="Fed release ↗", max_age_h=72)


def test_fetch_new_emits_event_signals_with_fixed_tickers(monkeypatch):
    monkeypatch.setattr(trump, "fetch_rss", lambda *a, **k: trump.parse_rss(FEED))
    signals, evaluated = _fed().fetch_new(set())
    assert len(evaluated) == 2 and len(signals) == 2          # every new item is a signal
    assert signals[0].tickers == ["SPY", "TLT", "IWM", "GLD"]  # fixed macro tag set
    assert "FOMC statement" in signals[0].summary             # item title is the headline
    assert signals[0].monitor_key == "fed"
    assert signals[0].link_text == "Fed release ↗"


def test_fetch_new_dedups_against_seen(monkeypatch):
    monkeypatch.setattr(trump, "fetch_rss", lambda *a, **k: trump.parse_rss(FEED))
    m = _fed()
    _, evaluated = m.fetch_new(set())
    signals2, _ = m.fetch_new(set(evaluated))
    assert signals2 == []                                     # all seen -> no re-alert


def test_validate_is_identity():
    from radar.monitors.base import Signal
    m = _fed()
    sigs = [Signal(tickers=["SPY"], summary="x", url="", published="", monitor_key="fed")]
    assert m.validate(sigs) is sigs                           # no LLM gate for event feeds


def test_parse_rss_tolerates_utf8_bom():
    # the live Fed monetary-policy feed ships a leading UTF-8 BOM that would otherwise
    # break ElementTree; parse_rss must strip it.
    bom_feed = "﻿" + FEED
    posts = trump.parse_rss(bom_feed)
    assert len(posts) == 2 and "FOMC statement" in posts[0].text
