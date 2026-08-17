# tests/test_monitors_registry.py
from radar.config import load_config
from radar.monitors import build_registry
from radar.monitors.prose import ProseMonitor
from radar.monitors.edgar import EdgarMonitor
from radar.monitors.events import RssEventMonitor
from radar.monitors.congress import CongressMonitor
from radar.monitors.edgar_events import EdgarEventsMonitor


def test_registry_has_all_nine_monitors():
    reg = build_registry(load_config("config.yaml"))
    keys = [m.key for m in reg]
    # Task 5 appends the four catalyst classes after edgar8k; see
    # test_registry_includes_the_four_catalyst_classes below for their own coverage.
    assert keys == ["trump", "edgar", "fed", "congress", "edgar8k",
                    "dilution", "shelf", "activist", "delisting"]
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


def test_every_registered_monitor_declares_a_valid_direction():
    from radar.config import load_config
    from radar.monitors import build_registry
    cfg = load_config("config.yaml")
    for m in build_registry(cfg):
        d = getattr(m, "direction", None)
        assert d in {"bullish", "bearish", "neutral"}, f"{m.key} has direction={d!r}"


def test_insider_buy_is_bullish_and_the_rest_are_neutral():
    from radar.config import load_config
    from radar.monitors import build_registry
    cfg = load_config("config.yaml")
    by_key = {m.key: m.direction for m in build_registry(cfg)}
    assert by_key["edgar"] == "bullish"          # open-market insider purchase
    # congress lags the trade by up to 45 days -> not fresh bullish news
    for key in ("trump", "fed", "congress", "edgar8k"):
        assert by_key[key] == "neutral"


def test_write_alert_persists_direction(tmp_path):
    from radar.monitors.base import write_alert, Signal
    import json, types
    mon = types.SimpleNamespace(key="k", label="L", card_style="insider",
                                max_age_h=24, direction="bearish")
    sig = Signal(tickers=["AAA"], summary="s", url="u",
                 published="2026-08-17T00:00:00Z", monitor_key="k")
    write_alert(mon, sig, "2026-08-17T01:00:00Z", data_dir=str(tmp_path))
    written = json.loads((tmp_path / "k_alert.json").read_text())
    assert written["direction"] == "bearish"


def test_write_alert_defaults_direction_to_neutral(tmp_path):
    from radar.monitors.base import write_alert, Signal
    import json, types
    mon = types.SimpleNamespace(key="k", label="L", card_style="trump", max_age_h=24)
    sig = Signal(tickers=["AAA"], summary="s", url="u",
                 published="2026-08-17T00:00:00Z", monitor_key="k")
    write_alert(mon, sig, "2026-08-17T01:00:00Z", data_dir=str(tmp_path))
    assert json.loads((tmp_path / "k_alert.json").read_text())["direction"] == "neutral"


def test_registry_includes_the_four_catalyst_classes():
    from radar.config import load_config
    from radar.monitors import build_registry
    by_key = {m.key: m for m in build_registry(load_config("config.yaml"))}
    assert {"dilution", "shelf", "activist", "delisting"} <= set(by_key)
    assert len(by_key) == 9                       # 5 existing + 4 new, all keys distinct


def test_catalyst_classes_carry_the_measured_form_codes_and_phrases():
    from radar.config import load_config
    from radar.monitors import build_registry
    by_key = {m.key: m for m in build_registry(load_config("config.yaml"))}
    # The q phrase is the debt/equity discriminator: with q="offering", 424B5 hits are
    # dominated by investment-grade BOND takedowns (AMD, IBM, UPS). Measured 2026-08-17.
    assert by_key["dilution"].forms == "424B5"
    assert by_key["dilution"].phrases == ["at the market offering"]
    assert by_key["dilution"].direction == "bearish"
    assert by_key["shelf"].forms == "S-3,S-3ASR"
    assert by_key["shelf"].direction == "neutral"
    # "SCHEDULE 13D", NOT "SC 13D" -- the latter returns zero hits.
    assert by_key["activist"].forms == "SCHEDULE 13D"
    assert by_key["activist"].direction == "bullish"
    # Only activist names the filer in its summary -- display_names[1] means something
    # different per form (13D activist filer vs. 8-K co-filer), so this is never inferred.
    assert by_key["activist"].filer_in_summary is True
    for key in ("dilution", "shelf", "delisting", "edgar8k"):
        assert by_key[key].filer_in_summary is False, key
    assert by_key["delisting"].forms == "25-NSE"
    assert by_key["delisting"].direction == "bearish"


def test_catalyst_classes_watch_90_days_and_edgar8k_still_watches_7():
    from radar.config import load_config
    from radar.monitors import build_registry
    by_key = {m.key: m for m in build_registry(load_config("config.yaml"))}
    for key in ("dilution", "shelf", "activist", "delisting"):
        assert by_key[key].watch_days == 90, key
    assert by_key["edgar8k"].watch_days == 7      # unchanged: widening it is a separate call
