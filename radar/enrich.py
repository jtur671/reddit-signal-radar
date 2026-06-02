from __future__ import annotations

def _yf_quote(symbol: str):
    try:
        import yfinance as yf
        fi = yf.Ticker(symbol).fast_info
        price = fi.get("last_price"); prev = fi.get("previous_close")
        if price is None:
            return None
        chg = ((price - prev) / prev * 100) if prev else None
        return (round(float(price), 2), round(float(chg), 2) if chg is not None else None)
    except Exception:
        return None

def enrich_one(symbol: str):
    q = _yf_quote(symbol)
    return q if q else (None, None)

def enrich(signals):
    for s in signals:
        s.price, s.pct_change = enrich_one(s.ticker)
    return signals
