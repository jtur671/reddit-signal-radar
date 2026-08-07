from __future__ import annotations
from radar.degrade import warn

def _yf_quote(symbol: str):
    """(price, pct_change) from yfinance's fast_info, or None when Yahoo has no quote.

    fast_info's keys are camelCase (`lastPrice`, `previousClose`). The snake_case spellings
    are not aliases — they return None on current yfinance and raise inside older versions —
    so ask for the camelCase name first and keep the old one only as a fallback.
    """
    try:
        import yfinance as yf
        fi = yf.Ticker(symbol).fast_info
        price = fi.get("lastPrice") or fi.get("last_price")
        prev = fi.get("previousClose") or fi.get("previous_close")
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
    for s in signals:
        s.price, s.pct_change = enrich_one(s.ticker)
    missing = [s.ticker for s in signals if s.price is None]
    if missing:
        warn(f"prices {len(missing)}/{len(signals)} missing", ", ".join(missing))
    return signals
