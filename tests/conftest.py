import pytest


@pytest.fixture(autouse=True)
def _no_real_dotenv(monkeypatch):
    """Hermeticity guard: neutralize the .env loader in both entrypoints so a developer's
    local .env (real API keys) can never leak into tests and trigger live network calls."""
    import radar.run
    import radar.monitor
    monkeypatch.setattr(radar.run, "load_env", lambda *a, **k: None)
    monkeypatch.setattr(radar.monitor, "load_env", lambda *a, **k: None)


@pytest.fixture(autouse=True)
def _no_live_quotes_or_summaries(monkeypatch):
    """Hermeticity guard: stub the three helpers that would otherwise open a socket during
    a --dry-run test — yfinance quotes (radar/run.py's ungated `enrich(board + still)`),
    the Wikipedia summary lookup (`about.describe`, whose data/about.json cache is
    gitignored and so is always empty locally, guaranteeing a live fetch), and the
    Wikidata ticker-map query.

    All three are private helpers BELOW the public API, so the socket is suppressed while
    the logic worth testing still runs: `enrich`'s miss-rate warn and `describe`'s cache
    write. `_yf_quote` returning None makes `enrich_one` yield (None, None) — a state
    the suite already exercises directly.

    tickermap's `_get_json` is the third: `fetch_ticker_map` runs on every `main()` and
    would otherwise fire a ~22s live SPARQL query at query.wikidata.org whenever the
    vendored snapshot is missing or stale — and the snapshot lives on the orphan `data`
    branch, so in a test checkout it is simply absent. None sends the fetch down the
    documented outage path, which is itself worth exercising."""
    import radar.enrich
    import radar.about
    import radar.tickermap
    monkeypatch.setattr(radar.enrich, "_yf_quote", lambda symbol: None)
    monkeypatch.setattr(radar.about, "fetch_summary", lambda *a, **k: None)
    monkeypatch.setattr(radar.tickermap, "_get_json", lambda *a, **k: None)
