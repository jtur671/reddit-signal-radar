from radar.composite import blend, components_for, percentile_rank, CRAMER_INVERSE
from radar.models import Signal

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
    s = Signal(ticker="AAA", score=50.0, pct_bull=40.0, short_ratio=0.5,
               pc_ratio=1.2, uoa=True, cramer="sell_avoid")
    peer = Signal(ticker="BBB", score=10.0, short_ratio=0.1)
    comps = components_for(s, [s, peer], ts_bull=61.0, alert_tickers={"AAA"})
    assert comps["velocity"] == 100.0 and comps["direction"] == 61.0
    assert comps["engagement"] == 40.0 and comps["short_pressure"] == 100.0
    assert comps["options"] == 100.0 and comps["events"] == 100.0
    assert comps["cramer_inverse"] == CRAMER_INVERSE["sell_avoid"] == 100.0

def test_components_none_when_uncovered():
    s = Signal(ticker="AAA", score=50.0)
    comps = components_for(s, [s], ts_bull=None, alert_tickers=set())
    assert comps["direction"] is None and comps["short_pressure"] is None
    assert comps["options"] is None and comps["cramer_inverse"] is None
    assert comps["events"] == 0.0

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
