from pathlib import Path

import pytest
import requests


class _NoNetRequests:
    """Stand-in for `radar.pageviews`'s module-global `requests`, so the guard sits one
    layer BELOW `_get_series` rather than replacing it.

    Stubbing `_get_series` itself was the obvious move and is wrong twice over:
    tests/test_pageviews.py::test_get_series_uses_all_access_user_and_a_real_user_agent
    calls the real transport (it is the only test that inspects the URL and UA, and it
    is what catches an all-access/user -> all-agents swap), and
    test_get_series_rejects_a_stale_tail asserts `_get_series(...) is None` — which a
    None-returning stub would satisfy for entirely the wrong reason: a green test
    asserting nothing. Rebinding the module global keeps both running their real logic
    while the socket stays shut, and a test that sets `pv.requests.get` itself just
    mutates this object and wins.

    Only `get` and `RequestException` are ever touched in pageviews.py; RequestException
    is the real class so the module's own `except` clause catches what this raises and
    takes the documented fail-soft path."""

    RequestException = requests.RequestException

    @staticmethod
    def get(*a, **k):
        raise requests.RequestException("hermeticity guard: no live Wikimedia in tests")


@pytest.fixture(autouse=True)
def _no_real_dotenv(monkeypatch):
    """Hermeticity guard: neutralize the .env loader in both entrypoints so a developer's
    local .env (real API keys) can never leak into tests and trigger live network calls."""
    import radar.run
    import radar.monitor
    monkeypatch.setattr(radar.run, "load_env", lambda *a, **k: None)
    monkeypatch.setattr(radar.monitor, "load_env", lambda *a, **k: None)


@pytest.fixture(autouse=True)
def _no_production_state(monkeypatch):
    """Isolation guard: tests never read the repo's `data/` directory, which in CI holds
    PRODUCTION state.

    `run.py` loads the relative path `data/about.json`, and `.github/workflows/daily.yml`
    restores `data/` from the orphan data branch (`:26`) BEFORE the pytest gate (`:35`),
    then pushes an updated cache back afterwards. So a test that calls `run.main()` is
    reading whatever yesterday's run wrote. That is not a stale-fixture annoyance, it is
    a live tripwire on the publish: a run-smoke test asserting a ticker gets fetched goes
    red the first day that ticker lands in the cache, and a red gate means no board, no
    email and no data-branch commit until someone hand-edits the data branch.

    Scoped to the `data/` directory rather than stubbed wholesale, deliberately: three
    tests in tests/test_about.py assert on load_cache's real schema-migration behaviour
    against tmp_path files, and a blanket `lambda p: {}` would leave all three green
    while asserting nothing. tmp_path loads keep running the real function."""
    import radar.about
    real_load_cache = radar.about.load_cache
    monkeypatch.setattr(radar.about, "load_cache",
                        lambda path: {} if Path(path).parent.name == "data"
                        else real_load_cache(path))


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
    documented outage path, which is itself worth exercising.

    E2's two new sources are the fourth and fifth, and both now run on every `main()`.
    pageviews is one live REST call PER BOARD TICKER (15 of them, each with a sleep
    behind it) — guarded at its `requests` global, see _NoNetRequests for why not at
    `_get_series`. short_interest fronts FINRA with two transports: `_get_json` is the
    settlement-discovery GET (and the only network call inside `_latest_settlement`, so
    stubbing the transport shuts the socket while the discovery logic still runs), and
    `_post_json` is the paging data POST. `_post_json` returns a TUPLE — (rows,
    record_total) — so its stub must be `(None, None)`; a bare None would unpack-error
    instead of taking the documented outage path. No test calls either FINRA transport
    for real, so stubbing them by name breaks nothing."""
    import radar.enrich
    import radar.about
    import radar.tickermap
    import radar.pageviews
    import radar.short_interest
    monkeypatch.setattr(radar.enrich, "_yf_quote", lambda symbol: None)
    monkeypatch.setattr(radar.about, "fetch_summary", lambda *a, **k: None)
    monkeypatch.setattr(radar.tickermap, "_get_json", lambda *a, **k: None)
    monkeypatch.setattr(radar.pageviews, "requests", _NoNetRequests())
    monkeypatch.setattr(radar.short_interest, "_get_json", lambda *a, **k: None)
    monkeypatch.setattr(radar.short_interest, "_post_json", lambda *a, **k: (None, None))
