import json, pathlib
from radar.options import parse_chain, is_put, option_stats

def test_is_put_classifier():
    assert is_put("AAPL260807C00110000") is False
    assert is_put("AAPL260807P00110000") is True
    assert is_put("GARBAGE") is None
    assert is_put("") is None

def test_parse_chain_from_fixture():
    raw = json.loads(pathlib.Path("tests/fixtures/cboe_options.json").read_text())
    stats = parse_chain(raw)
    assert stats["total_vol"] >= 0 and stats["total_oi"] >= 0
    assert stats["pc_ratio"] is None or stats["pc_ratio"] >= 0

def test_parse_chain_math():
    raw = {"data": {"options": [
        {"option": "X260101C00010000", "volume": 30, "open_interest": 100},
        {"option": "X260101P00010000", "volume": 60, "open_interest": 100},
        {"option": "BAD", "volume": 5, "open_interest": 5},          # unclassifiable -> vol counted, not in P/C
    ]}}
    s = parse_chain(raw)
    assert s["call_vol"] == 30 and s["put_vol"] == 60
    assert abs(s["pc_ratio"] - 2.0) < 1e-9
    assert s["total_vol"] == 95 and s["total_oi"] == 205

def test_parse_chain_never_raises():
    for raw in (None, {}, {"data": {}}, {"data": {"options": ["x", {"volume": "?"}]}}):
        assert isinstance(parse_chain(raw), dict)

def test_option_stats_fail_soft(monkeypatch):
    import radar.options as op
    monkeypatch.setattr(op, "_get_json", lambda *a, **k: None)
    from types import SimpleNamespace
    assert option_stats("AAPL", SimpleNamespace(cboe=SimpleNamespace())) is None
