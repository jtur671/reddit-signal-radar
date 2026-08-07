import sys
import types

from radar.enrich import enrich_one, enrich


def _fake_yfinance(fast_info):
    """A stand-in yfinance whose fast_info behaves like the real one: `.get` on a key it
    does not carry returns None rather than aliasing to another spelling."""
    mod = types.SimpleNamespace()
    mod.Ticker = lambda symbol: types.SimpleNamespace(fast_info=fast_info)
    return mod


def test_enrich_unknown_symbol_returns_none(monkeypatch):
    import radar.enrich as e
    monkeypatch.setattr(e, "_yf_quote", lambda s: None)
    price, chg = enrich_one("ZZZZNOPE")
    assert price is None and chg is None


def test_quote_reads_camelcase_fast_info_keys(monkeypatch):
    """Regression: yfinance's fast_info exposes `lastPrice`/`previousClose`, not the
    snake_case spellings. Reading the wrong names silently priced the whole board at None."""
    monkeypatch.setitem(sys.modules, "yfinance",
                        _fake_yfinance({"lastPrice": 12.5, "previousClose": 10.0}))
    assert enrich_one("TTD") == (12.5, 25.0)


def test_quote_falls_back_to_snake_case_keys(monkeypatch):
    monkeypatch.setitem(sys.modules, "yfinance",
                        _fake_yfinance({"last_price": 12.5, "previous_close": 10.0}))
    assert enrich_one("TTD") == (12.5, 25.0)


def test_missing_prices_are_reported_to_stderr(monkeypatch, capsys):
    """A board that quietly renders every price as an em dash must say so in the log."""
    import radar.enrich as e
    monkeypatch.setattr(e, "_yf_quote", lambda s: None)
    signals = [types.SimpleNamespace(ticker=t, price=0, pct_change=0) for t in ("AAA", "BBB")]
    enrich(signals)
    err = capsys.readouterr().err
    assert "DEGRADED: prices 2/2 missing" in err and "AAA, BBB" in err


def test_priced_board_stays_quiet(monkeypatch, capsys):
    import radar.enrich as e
    monkeypatch.setattr(e, "_yf_quote", lambda s: (1.0, 2.0))
    enrich([types.SimpleNamespace(ticker="AAA", price=0, pct_change=0)])
    assert "DEGRADED" not in capsys.readouterr().err
