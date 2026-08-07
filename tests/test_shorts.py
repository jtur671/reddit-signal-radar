import pathlib
from radar.shorts import parse_shvol, fetch_short_ratios

def test_parse_shvol_from_fixture():
    text = pathlib.Path("tests/fixtures/finra_shvol.txt").read_text()
    ratios = parse_shvol(text)
    assert ratios, "fixture parsed to empty dict"
    for sym, r in ratios.items():
        assert 0.0 <= r <= 1.0, (sym, r)
    assert "A" in ratios and abs(ratios["A"] - 176779.078848 / 323438.701002) < 1e-9

def test_parse_shvol_never_raises_on_garbage():
    for text in (None, "", "not|a|real|file", "Date|Symbol\nx",
                 "Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market\nBAD|ROW\n20260806|Z|0|0|0|Q\n"):
        out = parse_shvol(text)
        assert isinstance(out, dict)
        assert "Z" not in out                     # TotalVolume 0 -> dropped, not div/0

def test_fetch_walks_back_and_fails_soft(monkeypatch):
    import radar.shorts as sh
    calls = []
    def fake_get(url, ua, retries=2, sleep_s=1.0):
        calls.append(url)
        return None if len(calls) < 3 else "Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market\n20260804|GME|60|0|100|Q\n"
    monkeypatch.setattr(sh, "_get_text", fake_get)
    from types import SimpleNamespace
    cfg = SimpleNamespace(finra=SimpleNamespace(max_lookback_days=5))
    ratios, src = fetch_short_ratios(cfg, "2026-08-07")
    assert ratios == {"GME": 0.6} and src == "20260804"
    assert "20260806" in calls[0]                  # starts at run_day - 1

def test_fetch_total_failure_returns_empty(monkeypatch):
    import radar.shorts as sh
    monkeypatch.setattr(sh, "_get_text", lambda *a, **k: None)
    from types import SimpleNamespace
    cfg = SimpleNamespace(finra=SimpleNamespace(max_lookback_days=2))
    assert fetch_short_ratios(cfg, "2026-08-07") == ({}, "")
