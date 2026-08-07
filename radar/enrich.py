from __future__ import annotations
from radar.degrade import warn

def _yf_quote(symbol: str):
    """(price, pct_change) from yfinance's fast_info, or None when Yahoo has no quote.

    fast_info's keys are camelCase (`lastPrice`, `previousClose`); the snake_case
    spellings are not aliases — FastInfo.get() just returns its default for them
    (measured on both 0.2.51 and 1.5.2), so there is no fallback worth keeping.
    A price of 0.0 is a real quote (halted/delisted names), not a miss.
    """
    try:
        import yfinance as yf
        fi = yf.Ticker(symbol).fast_info
        price = fi.get("lastPrice")
        prev = fi.get("previousClose")
        if price is None:
            return None
        chg = ((price - prev) / prev * 100) if prev else None
        return (round(float(price), 2), round(float(chg), 2) if chg is not None else None)
    except Exception as e:
        warn(f"price {symbol}", e)
        return None

def enrich_one(symbol: str):
    q = _yf_quote(symbol)
    return q if q else (None, None)

def enrich(signals):
    """Attach price + pct_change to every signal. Reports the miss rate: a board that
    silently renders every price as an em dash is the failure this line exists to expose."""
    signals = list(signals)   # iterated twice (attach, then miss rate) and returned
    for s in signals:
        s.price, s.pct_change = enrich_one(s.ticker)
    missing = [s.ticker for s in signals if s.price is None]
    if missing:
        warn(f"prices {len(missing)}/{len(signals)} missing", ", ".join(missing))
    return signals
