from radar.enrich import enrich_one

def test_enrich_unknown_symbol_returns_none(monkeypatch):
    import radar.enrich as e
    monkeypatch.setattr(e, "_yf_quote", lambda s: None)
    price, chg = enrich_one("ZZZZNOPE")
    assert price is None and chg is None
