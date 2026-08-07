# tests/test_monitors_registry.py
from radar.config import load_config
from radar.monitors import build_registry
from radar.monitors.prose import ProseMonitor
from radar.monitors.edgar import EdgarMonitor
from radar.monitors.events import RssEventMonitor
from radar.monitors.congress import CongressMonitor
from radar.monitors.edgar_events import EdgarEventsMonitor


def test_registry_has_all_five_monitors():
    reg = build_registry(load_config("config.yaml"))
    keys = [m.key for m in reg]
    assert keys == ["trump", "edgar", "fed", "congress", "edgar8k"]
    trump_m = next(m for m in reg if m.key == "trump")
    edgar_m = next(m for m in reg if m.key == "edgar")
    fed_m = next(m for m in reg if m.key == "fed")
    cong_m = next(m for m in reg if m.key == "congress")
    ev_m = next(m for m in reg if m.key == "edgar8k")
    assert isinstance(trump_m, ProseMonitor) and isinstance(edgar_m, EdgarMonitor)
    assert isinstance(fed_m, RssEventMonitor) and isinstance(cong_m, CongressMonitor)
    assert isinstance(ev_m, EdgarEventsMonitor)
    assert edgar_m.min_usd == 1_000_000 and edgar_m.codes == {"P"}
    assert trump_m.card_style == "trump" and edgar_m.card_style == "insider"
    assert fed_m.card_style == "fed" and fed_m.tickers == ["SPY", "TLT", "IWM", "GLD"]
    assert "federalreserve.gov" in fed_m.feed_url
    assert cong_m.card_style == "congress" and cong_m.min_usd == 250000
    assert "pelosi" in cong_m.watch        # surname loaded from data/congress_watch.yaml
    assert ev_m.card_style == "insider" and ev_m.label == "📢 8-K Event"
    assert "material definitive agreement" in ev_m.phrases
