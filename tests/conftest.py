from pathlib import Path

import pytest
import requests
import yaml

_REPO = Path(__file__).resolve().parent.parent


def _production_state_dirs() -> frozenset[str]:
    """Directory names that hold PRODUCTION state, derived from config.yaml's own
    `snapshot_path` declarations rather than from a hardcoded "data".

    Every vendoring source declares where its snapshot lives, and
    `.github/workflows/daily.yml` restores exactly those files from the orphan data
    branch before the pytest gate. Reading the declaration means the guard tracks
    config instead of convention: move `short_interest.snapshot_path` to `state/` and
    the guard follows it, where a literal "data" would silently stop covering it and
    the failure would surface as a red publish gate two days after the merge.

    A NAME rather than a resolved absolute path, deliberately, and this is the one
    concession to convention: tests must be able to construct a production-shaped path
    under tmp_path to assert the guard actually fires (tests/test_about.py's
    test_tests_never_read_the_production_about_cache is the pattern), and an
    absolute-path match could only be tested by writing into the repo's real data/ —
    which in CI holds restored production state this suite must never clobber.
    `data/about.json` is seeded literally because run.py hardcodes it; config never
    declares it."""
    names = {"data"}
    try:
        doc = yaml.safe_load((_REPO / "config.yaml").read_text())
    except (OSError, ValueError, yaml.YAMLError):
        return frozenset(names)       # cold checkout: fall back to the convention
    stack = [doc]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            declared = node.get("snapshot_path")
            if isinstance(declared, str) and Path(declared).parent.name:
                names.add(Path(declared).parent.name)
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return frozenset(names)


PRODUCTION_STATE_DIRS = _production_state_dirs()


def _is_production_state(path) -> bool:
    """True when `path` points into a directory config declares as vendored state."""
    return Path(path).parent.name in PRODUCTION_STATE_DIRS


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


class _NoSleepTime:
    """Stand-in for `radar.pageviews`'s module-global `time`, so `_get_series`'s
    retry-backoff sleeps (429/500/502/503 and on-exception, both `sleep_s * 2**attempt`)
    don't burn real wall clock in the suite that gates the 6:17 AM daily publish.

    Rebinds the module global rather than the house-style `monkeypatch.setattr(pv.time,
    "sleep", ...)`, deliberately: `pv.time` IS the shared stdlib `time` module object, so
    that form would patch `time.sleep` process-wide for the rest of the suite, not just
    pageviews.py's tests. This scoped rebind only replaces what `radar.pageviews` sees,
    leaving every other module's `time.sleep` real.

    Only `sleep` is ever called on `time` in pageviews.py (retry backoff in
    `_get_series`, politeness pacing in `fetch_attention`)."""

    @staticmethod
    def sleep(*a, **k):
        pass


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
    restores `data/` from the orphan data branch (`:39`) BEFORE the pytest gate (`:44`),
    then pushes an updated cache back afterwards. So a test that calls `run.main()` is
    reading whatever yesterday's run wrote. That is not a stale-fixture annoyance, it is
    a live tripwire on the publish: a run-smoke test asserting a ticker gets fetched goes
    red the first day that ticker lands in the cache, and a red gate means no board, no
    email and no data-branch commit until someone hand-edits the data branch.

    Scoped to the state directories rather than stubbed wholesale, deliberately: three
    tests in tests/test_about.py assert on load_cache's real schema-migration behaviour
    against tmp_path files, and a blanket `lambda p: {}` would leave all three green
    while asserting nothing. tmp_path loads keep running the real function.

    about.json was the only reader covered until E2 shipped two more that `main()`
    exercises on EVERY smoke test, both resolving their path from the real config.yaml
    and both on daily.yml's copy whitelist — so the first successful production run
    vendors them to the data branch and the NEXT day's restore feeds them back to the
    gate. Measured with realistic snapshots in place: test_run_smoke.py's
    `assert calls == []` sees `[('IREN Limited', ...)]` once ticker_articles.json exists,
    and finra_si's LED reads "ok" where the test requires "down" once
    short_interest.json does — the FINRA half unconditionally, because `_read_snapshot`
    succeeding sends fetch_short_interest down its documented snapshot-fallback path
    with the transports stubbed. Three readers each, at the file-reading helper rather
    than at the public function, so every fallback/refusal path above them still runs
    for real:

      short_interest._read_snapshot   — the snapshot-fallback source
      tickermap._snapshot_map         — the fallback map
      tickermap._snapshot_age_days    — the monthly-refresh freshness gate
      tickermap._snapshot_rows        — the shrink-regression baseline; unreachable in
                                        today's suite (`_get_json` is stubbed to None
                                        below, so the live branch never runs) but the
                                        same class of read, and one line to close."""
    import radar.about
    import radar.short_interest
    import radar.tickermap
    real_load_cache = radar.about.load_cache
    real_read_snapshot = radar.short_interest._read_snapshot
    real_snapshot_map = radar.tickermap._snapshot_map
    real_snapshot_age = radar.tickermap._snapshot_age_days
    real_snapshot_rows = radar.tickermap._snapshot_rows
    monkeypatch.setattr(radar.about, "load_cache",
                        lambda path: {} if _is_production_state(path)
                        else real_load_cache(path))
    monkeypatch.setattr(radar.short_interest, "_read_snapshot",
                        lambda snap: None if _is_production_state(snap)
                        else real_read_snapshot(snap))
    monkeypatch.setattr(radar.tickermap, "_snapshot_map",
                        lambda snap: None if _is_production_state(snap)
                        else real_snapshot_map(snap))
    monkeypatch.setattr(radar.tickermap, "_snapshot_age_days",
                        lambda snap, run_day: None if _is_production_state(snap)
                        else real_snapshot_age(snap, run_day))
    monkeypatch.setattr(radar.tickermap, "_snapshot_rows",
                        lambda snap: None if _is_production_state(snap)
                        else real_snapshot_rows(snap))


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
    `_get_series`. `_get_series`'s retry-backoff loop still runs against that raising
    stub, though, and sleeps for real unless `time` is also rebound — see _NoSleepTime.
    short_interest fronts FINRA with two transports: `_get_json` is the
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
    monkeypatch.setattr(radar.pageviews, "time", _NoSleepTime())
    monkeypatch.setattr(radar.short_interest, "_get_json", lambda *a, **k: None)
    monkeypatch.setattr(radar.short_interest, "_post_json", lambda *a, **k: (None, None))
