import sys
import types

import radar.enrich as _e
from radar.enrich import enrich_one, enrich

# Captured at import (collection) time, before conftest's autouse hermeticity guard
# replaces the attribute. The tests below drive _yf_quote's own internals through a
# fake yfinance, so they need the real implementation back.
_REAL_YF_QUOTE = _e._yf_quote


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
    monkeypatch.setattr(_e, "_yf_quote", _REAL_YF_QUOTE)
    monkeypatch.setitem(sys.modules, "yfinance",
                        _fake_yfinance({"lastPrice": 12.5, "previousClose": 10.0}))
    assert enrich_one("TTD") == (12.5, 25.0)


def test_quote_snake_case_only_fast_info_is_a_miss(monkeypatch):
    """There is no snake_case fallback: real FastInfo.get returns None for those
    spellings on every version we've pinned, so a fast_info without `lastPrice`
    is a genuine miss — not an alias lookup."""
    monkeypatch.setattr(_e, "_yf_quote", _REAL_YF_QUOTE)
    monkeypatch.setitem(sys.modules, "yfinance",
                        _fake_yfinance({"last_price": 12.5, "previous_close": 10.0}))
    assert enrich_one("TTD") == (None, None)


def test_zero_price_is_a_real_quote(monkeypatch):
    """A halted/delisted name can legitimately quote at 0.0 — that's a price, not a miss."""
    monkeypatch.setattr(_e, "_yf_quote", _REAL_YF_QUOTE)
    monkeypatch.setitem(sys.modules, "yfinance",
                        _fake_yfinance({"lastPrice": 0.0, "previousClose": 10.0}))
    assert enrich_one("HALT") == (0.0, -100.0)


def test_zero_previous_close_skips_pct_change(monkeypatch):
    monkeypatch.setattr(_e, "_yf_quote", _REAL_YF_QUOTE)
    monkeypatch.setitem(sys.modules, "yfinance",
                        _fake_yfinance({"lastPrice": 5.0, "previousClose": 0.0}))
    assert enrich_one("IPO") == (5.0, None)


def test_missing_prices_are_reported_to_stderr(monkeypatch, capsys):
    """A board that quietly renders every price as an em dash must say so in the log."""
    import radar.enrich as e
    monkeypatch.setattr(e, "_yf_quote", lambda s: None)
    signals = [types.SimpleNamespace(ticker=t, price=0, pct_change=0) for t in ("AAA", "BBB")]
    enrich(signals)
    err = capsys.readouterr().err
    assert "DEGRADED: prices 2/2 missing" in err and "AAA, BBB" in err


def test_enrich_accepts_a_generator(monkeypatch, capsys):
    """enrich iterates its input twice; a generator argument must still get the
    miss-rate warning and come back as a renderable (non-exhausted) list."""
    import radar.enrich as e
    monkeypatch.setattr(e, "_yf_quote", lambda s: None)
    out = enrich(types.SimpleNamespace(ticker=t, price=0, pct_change=0)
                 for t in ("AAA", "BBB"))
    assert [s.ticker for s in out] == ["AAA", "BBB"]
    assert "DEGRADED: prices 2/2 missing" in capsys.readouterr().err


def test_priced_board_stays_quiet(monkeypatch, capsys):
    import radar.enrich as e
    monkeypatch.setattr(e, "_yf_quote", lambda s: (1.0, 2.0))
    enrich([types.SimpleNamespace(ticker="AAA", price=0, pct_change=0)])
    assert "DEGRADED" not in capsys.readouterr().err
