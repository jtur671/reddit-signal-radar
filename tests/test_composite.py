from radar.composite import (blend, components_for, percentile_rank, CRAMER_INVERSE,
                             EVENT_DIRECTION, DEFAULT_WEIGHTS)
from radar.run import alert_direction_map
from radar.models import Signal

def _sig(**k):
    base = dict(ticker="AAA")
    base.update(k)
    return Signal(**base)

def test_percentile_rank():
    assert percentile_rank(30.0, [10.0, 20.0, 30.0, 40.0]) == 75.0   # 3 of 4 <= value
    assert percentile_rank(5.0, [10.0]) == 0.0
    assert percentile_rank(1.0, []) is None

def test_blend_renormalizes_nulls():
    weights = {"a": 0.5, "b": 0.3, "c": 0.2}
    score, used = blend({"a": 100.0, "b": None, "c": 50.0}, weights)
    # a,c renormalized: 0.5/0.7 * 100 + 0.2/0.7 * 50 = 85.71 -> 86
    assert score == 86
    assert abs(sum(used.values()) - 1.0) < 1e-9 and "b" not in used

def test_blend_all_null():
    assert blend({"a": None}, {"a": 1.0}) == (None, {})

def test_components_for_shapes():
    s = Signal(ticker="AAA", score=50.0, mentions=100, pct_bull=40.0, short_ratio=0.5,
               pc_ratio=1.2, uoa=True, cramer="sell_avoid")
    peer = Signal(ticker="BBB", score=10.0, short_ratio=0.1)
    comps = components_for(s, [s, peer], ts_bull=61.0, alert_direction={"AAA": "bullish"})
    assert comps["velocity"] == 100.0 and comps["direction"] == 61.0
    assert comps["engagement"] == 40.0 and comps["short_pressure"] == 100.0
    assert comps["options"] == 100.0 and comps["events"] == 100.0
    assert comps["cramer_inverse"] == CRAMER_INVERSE["sell_avoid"] == 100.0

def test_components_none_when_uncovered():
    s = Signal(ticker="AAA", score=50.0)
    comps = components_for(s, [s], ts_bull=None, alert_direction={})
    assert comps["direction"] is None and comps["short_pressure"] is None
    assert comps["options"] is None and comps["cramer_inverse"] is None
    assert comps["engagement"] is None                   # mentions=0 -> no engagement data
    assert comps["events"] is None

def test_engagement_zero_is_not_none():
    # A ticker with real mentions and zero bullish upvotes is a legitimate 0.0,
    # not "no data" -- must not be nulled out and renormalized away. This is also
    # the Tradestie-fallback board path's shape: to_aggregates hardcodes upvotes=0,
    # so every ticker's pct_bull is 0.0 while mentions is real.
    s = Signal(ticker="AAA", score=50.0, mentions=42, pct_bull=0.0)
    comps = components_for(s, [s], ts_bull=None, alert_direction={})
    assert comps["engagement"] == 0.0

    no_mentions = Signal(ticker="BBB", score=50.0, mentions=0, pct_bull=0.0)
    comps2 = components_for(no_mentions, [no_mentions], ts_bull=None, alert_direction={})
    assert comps2["engagement"] is None

def test_data_json_signals_block(tmp_path):
    # the payload contract the downstream bot reads
    from radar.render import write_outputs
    payload = {"board": ["AAA"], "health": {"status": "ok"},
               "signals": [{"ticker": "AAA", "composite": 61,
                            "components": {"velocity": 100.0}}],
               "weights": {"velocity": 1.0}}
    write_outputs("<html></html>", payload, out_dir=str(tmp_path))
    import json as j
    d = j.loads((tmp_path / "data.json").read_text())
    assert d["signals"][0]["composite"] == 61 and d["weights"]["velocity"] == 1.0
    assert d["board"] == ["AAA"]                      # legacy contract untouched


def test_event_direction_mapping():
    assert EVENT_DIRECTION == {"bearish": 0.0, "neutral": 50.0, "bullish": 100.0}


def test_events_is_signed_by_direction():
    from radar.models import Signal
    s = Signal(ticker="AAA", score=50.0, mentions=10)
    for direction, expected in (("bullish", 100.0), ("neutral", 50.0), ("bearish", 0.0)):
        comps = components_for(s, [s], ts_bull=None, alert_direction={"AAA": direction})
        assert comps["events"] == expected, direction


def test_events_is_none_when_no_fresh_alert():
    # The bug this fixes: a real 0.0 punished every quiet ticker. On the live
    # 2026-08-17 board this component was 0.0 for all 15 rows -- zero variance
    # across 10% of the composite weight.
    from radar.models import Signal
    s = Signal(ticker="AAA", score=50.0, mentions=10)
    assert components_for(s, [s], ts_bull=None, alert_direction={})["events"] is None
    assert components_for(s, [s], ts_bull=None,
                          alert_direction={"OTHER": "bullish"})["events"] is None


def test_events_none_is_dropped_and_weight_renormalized():
    from radar.models import Signal
    s = Signal(ticker="AAA", score=50.0, mentions=10)
    comps = components_for(s, [s], ts_bull=None, alert_direction={})
    _score, used = blend(comps, {"velocity": 0.30, "direction": 0.15, "engagement": 0.10,
                                 "short_pressure": 0.15, "options": 0.10, "events": 0.10,
                                 "cramer_inverse": 0.10})
    assert "events" not in used
    assert abs(sum(used.values()) - 1.0) < 1e-9


def test_alert_direction_map_bearish_beats_bullish_beats_neutral():
    # REPL drew a 424B5, an S-3ASR and a SCHEDULE 13D inside one week (2026-08-10..14).
    alerts = [
        {"tickers": "$REPL", "direction": "bullish"},
        {"tickers": "$REPL", "direction": "neutral"},
        {"tickers": "$REPL", "direction": "bearish"},
    ]
    assert alert_direction_map(alerts) == {"REPL": "bearish"}
    assert alert_direction_map(alerts[:2]) == {"REPL": "bullish"}
    assert alert_direction_map(alerts[1:2]) == {"REPL": "neutral"}


def test_alert_direction_map_splits_multi_ticker_and_strips_cashtags():
    alerts = [{"tickers": "$SPY · $TLT · $IWM", "direction": "neutral"}]
    assert alert_direction_map(alerts) == {"SPY": "neutral", "TLT": "neutral", "IWM": "neutral"}
    assert alert_direction_map([{"tickers": "", "direction": "bearish"}]) == {}


def test_attention_is_published_in_components():
    s = _sig(attention=88.0)
    assert components_for(s, [s], None, {})["attention"] == 88.0


def test_attention_is_none_when_unscored():
    assert components_for(_sig(attention=None), [_sig()], None, {})["attention"] is None


def test_attention_does_not_change_the_composite():
    """The central claim of spec 2.3. attention ships with no weight, so the blended
    number must be byte-identical with and without it. If someone adds a weight for
    it, this test fails and the regime-boundary conversation happens BEFORE the
    backtest series is silently broken."""
    weights = dict(DEFAULT_WEIGHTS)
    without = {"velocity": 70.0, "direction": 60.0}
    with_att = dict(without, attention=100.0)
    assert blend(with_att, weights) == blend(without, weights)


def test_default_weights_has_exactly_seven_keys():
    """attention must NOT be here. Its absence is the mechanism."""
    assert len(DEFAULT_WEIGHTS) == 7
    assert "attention" not in DEFAULT_WEIGHTS
