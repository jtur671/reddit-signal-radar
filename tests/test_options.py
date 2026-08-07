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

def test_get_json_404_returns_missing_sentinel(monkeypatch):
    import radar.options as op
    class Resp:
        status_code = 404
    monkeypatch.setattr(op.requests, "get", lambda *a, **k: Resp())
    assert op._get_json("http://x", "ua", retries=1, sleep_s=0, timeout=5) == "missing"

def test_get_json_other_non_retryable_status_returns_none(monkeypatch):
    import radar.options as op
    class Resp:
        status_code = 400
    monkeypatch.setattr(op.requests, "get", lambda *a, **k: Resp())
    assert op._get_json("http://x", "ua", retries=1, sleep_s=0, timeout=5) is None

def test_get_json_retries_retryable_statuses_then_gives_up(monkeypatch):
    import radar.options as op
    calls = []
    class Resp:
        status_code = 503
    def fake_get(*a, **k):
        calls.append(1)
        return Resp()
    monkeypatch.setattr(op.requests, "get", fake_get)
    monkeypatch.setattr(op.time, "sleep", lambda s: None)
    assert op._get_json("http://x", "ua", retries=3, sleep_s=0, timeout=5) is None
    assert len(calls) == 3

def test_get_json_passes_timeout_through_to_requests(monkeypatch):
    import radar.options as op
    captured = {}
    class Resp:
        status_code = 200
        def json(self):
            return {"ok": True}
    def fake_get(url, headers=None, timeout=None):
        captured["timeout"] = timeout
        return Resp()
    monkeypatch.setattr(op.requests, "get", fake_get)
    assert op._get_json("http://x", "ua", retries=1, sleep_s=0, timeout=7) == {"ok": True}
    assert captured["timeout"] == 7

def test_option_stats_returns_missing_on_404_and_annotates_nothing(monkeypatch):
    import radar.options as op
    monkeypatch.setattr(op, "_get_json", lambda *a, **k: "missing")
    from types import SimpleNamespace
    assert option_stats("NOSUCH", SimpleNamespace(cboe=SimpleNamespace())) == "missing"

def test_option_stats_reads_cboe_config_and_passes_through(monkeypatch):
    import radar.options as op
    captured = {}
    def fake_get_json(url, ua, **k):
        captured.update(k)
        return None
    monkeypatch.setattr(op, "_get_json", fake_get_json)
    from types import SimpleNamespace
    cfg = SimpleNamespace(cboe=SimpleNamespace(timeout=3, max_retries=5, sleep_seconds=0.25))
    option_stats("AAPL", cfg)
    assert captured == {"retries": 5, "sleep_s": 0.25, "timeout": 3}

def test_option_stats_defaults_when_cboe_fields_absent(monkeypatch):
    import radar.options as op
    captured = {}
    def fake_get_json(url, ua, **k):
        captured.update(k)
        return None
    monkeypatch.setattr(op, "_get_json", fake_get_json)
    from types import SimpleNamespace
    option_stats("AAPL", SimpleNamespace(cboe=SimpleNamespace()))
    assert captured == {"retries": 1, "sleep_s": 1.0, "timeout": 10}
