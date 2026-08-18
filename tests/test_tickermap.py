import json
import types
from pathlib import Path

import pytest

import radar.tickermap as tm
from radar import degrade

RAW = json.loads(Path("tests/fixtures/wikidata_rows.json").read_text())


def _cfg(tmp_path, overrides=None):
    # Default to a path that is guaranteed not to exist, rather than the repo's real
    # radar/ticker_overrides.yml -- once Task 3 populates that file, every test here
    # that asserts an exact dict (not just DOW/overrides-specific ones) would start
    # picking up real entries via _finish's unconditional merge and break.
    if overrides is None:
        overrides = str(tmp_path / "no_such_overrides.yml")
    return types.SimpleNamespace(tickermap=types.SimpleNamespace(
        snapshot_path=str(tmp_path / "ticker_articles.json"),
        overrides_path=overrides, max_age_days=30))


@pytest.fixture(autouse=True)
def _clear_degrade():
    # House pattern (see tests/test_health.py, tests/test_backtest.py): degrade has no
    # clear() -- reset() is the established reset mechanism.
    degrade.reset()
    yield


def test_plain_row_maps_ticker_to_title():
    assert tm.parse_rows(RAW)["AAPL"] == "Apple Inc."


def test_deprecated_rank_is_dropped():
    """AAL has a DeprecatedRank row for Anglo American; the live row must win."""
    assert tm.parse_rows(RAW)["AAL"] == "American Airlines Group"


def test_past_end_date_dropped_when_a_live_alternative_exists():
    """Google's listing ended 2016-01-01 and Alphabet's has no end date."""
    assert tm.parse_rows(RAW)["GOOG"] == "Alphabet Inc."


def test_sole_statement_is_kept_even_when_ended():
    """The proviso: an ended statement survives when it is the ONLY one for that
    ticker. Without this, every historical-only listing silently vanishes."""
    assert tm.parse_rows(RAW)["BBBY"] == "Bed Bath & Beyond"


def test_unresolved_same_family_ambiguity_is_omitted_not_guessed():
    """DOW has two live, same-rank candidates. parse_rows must NOT pick one at
    random -- the override file is what resolves these."""
    assert "DOW" not in tm.parse_rows(RAW)


def test_parse_rows_never_raises_on_junk():
    for junk in (None, {}, {"results": {}}, {"results": {"bindings": "nope"}},
                 {"results": {"bindings": [{"ticker": {}}]}}):
        assert tm.parse_rows(junk) == {}


def test_parse_rows_coerces_non_string_ticker_and_title():
    """'Never raises' is the whole contract, and dict[str, str] is the whole return
    type -- a non-string binding value used to break both: ticker.upper() raised
    AttributeError, and a passed-through non-string title broke the type contract."""
    raw = {"results": {"bindings": [
        {"ticker": {"value": 5}, "enwiki": {"value": 7},
         "rank": {"value": "http://wikiba.se/ontology#NormalRank"}}]}}
    got = tm.parse_rows(raw)
    assert got == {"5": "7"}
    assert isinstance(next(iter(got)), str) and isinstance(got["5"], str)


def test_query_uses_the_qualifier_path_and_shares_a_where_with_count():
    """Nothing else pins the SPARQL text. Swapping in wdt:P249 (the 38-statement direct
    path, vs. the 17,204-statement qualifier path this module depends on) left every
    other test passing -- only this one would catch it."""
    assert "pq:P249" in tm.QUERY and "wdt:P249" not in tm.QUERY
    assert "p:P414" in tm.QUERY and "pq:P582" in tm.QUERY
    assert tm._WHERE in tm.QUERY and tm._WHERE in tm.COUNT_QUERY


def test_exchanges_are_the_four_us_venues():
    """Hardcoded on purpose. Deriving these from tm.EXCHANGES would make the
    assertion tautological -- QUERY is built from EXCHANGES, so a dropped entry
    would mutate both sides together and pass. Spec 2.2: scoping is a correctness
    requirement; unscoped, ambiguity goes 3.6% -> 15.2% (BA -> Bangkok Airways)."""
    assert tm.EXCHANGES == ("wd:Q13677", "wd:Q82059", "wd:Q1930860", "wd:Q846626")
    for q in ("wd:Q13677", "wd:Q82059", "wd:Q1930860", "wd:Q846626"):
        assert q in tm.QUERY


# --- fetch_ticker_map -------------------------------------------------------

def _resp(n_rows, count=None):
    """A WDQS response with n_rows bindings, and a COUNT that may disagree."""
    rows = [{"ticker": {"value": f"T{i}"}, "enwiki": {"value": f"Title {i}"},
             "rank": {"value": "http://wikiba.se/ontology#NormalRank"}}
            for i in range(n_rows)]
    return rows, {"results": {"bindings": [
        {"n": {"value": str(count if count is not None else n_rows)}}]}}


def test_row_count_mismatch_refuses_to_overwrite_snapshot(monkeypatch, tmp_path):
    """The whole point of this task. A truncated 200 must not be vendored."""
    snap = tmp_path / "ticker_articles.json"
    # `fetched` must be older than max_age_days (30) so fetch_ticker_map actually
    # attempts a refresh instead of short-circuiting on the freshness check -- the
    # thing this test exists to exercise.
    snap.write_text(json.dumps({"schema": 1, "fetched": "2026-06-01", "rows_fetched": 3,
                                "rows_expected": 3, "map": {"OLD": "Old Title"}}))
    rows, count = _resp(2, count=4015)          # truncated: 2 returned, 4015 expected

    def fake_get(query, ua, **kw):
        return count if "COUNT" in query else {"results": {"bindings": rows}}

    monkeypatch.setattr(tm, "_get_json", fake_get)
    cfg = _cfg(tmp_path)
    got = tm.fetch_ticker_map(cfg, "2026-08-17")

    assert got == {"OLD": "Old Title"}, "must serve the old snapshot, not the truncated fetch"
    assert json.loads(snap.read_text())["map"] == {"OLD": "Old Title"}, "snapshot unchanged"
    assert any("row count" in str(e).lower() for e in degrade.events())


def test_matching_count_vendors_the_snapshot(monkeypatch, tmp_path):
    snap = tmp_path / "ticker_articles.json"
    rows, count = _resp(3)
    monkeypatch.setattr(tm, "_get_json",
                        lambda q, ua, **kw: count if "COUNT" in q else {"results": {"bindings": rows}})
    monkeypatch.setattr(tm, "MIN_ROWS", 0)  # isolate from the floor guard -- not under test here
    got = tm.fetch_ticker_map(_cfg(tmp_path), "2026-08-17")
    assert got["T0"] == "Title 0"
    written = json.loads(snap.read_text())
    assert written["rows_fetched"] == written["rows_expected"] == 3
    assert written["fetched"] == "2026-08-17"


def test_upstream_down_serves_snapshot_and_warns(monkeypatch, tmp_path):
    snap = tmp_path / "ticker_articles.json"
    snap.write_text(json.dumps({"schema": 1, "map": {"AAPL": "Apple Inc."}}))
    monkeypatch.setattr(tm, "_get_json", lambda *a, **k: None)
    assert tm.fetch_ticker_map(_cfg(tmp_path), "2026-08-17") == {"AAPL": "Apple Inc."}
    assert any("snapshot" in str(e).lower() for e in degrade.events())


def test_both_gone_returns_empty_and_warns(monkeypatch, tmp_path):
    monkeypatch.setattr(tm, "_get_json", lambda *a, **k: None)
    assert tm.fetch_ticker_map(_cfg(tmp_path), "2026-08-17") == {}
    assert degrade.events()


def test_fresh_snapshot_skips_the_fetch_entirely(monkeypatch, tmp_path):
    """Spec 2.7: refresh only when the snapshot is older than max_age_days. Listing
    churn is <1%/yr, and the live query costs ~22s -- paying that daily is waste."""
    snap = tmp_path / "ticker_articles.json"
    snap.write_text(json.dumps({"schema": 1, "fetched": "2026-08-10",
                                "map": {"AAPL": "Apple Inc."}}))
    calls = []
    monkeypatch.setattr(tm, "_get_json", lambda *a, **k: calls.append(1))
    got = tm.fetch_ticker_map(_cfg(tmp_path), "2026-08-17")   # 7 days old, max_age 30
    assert calls == [], "a fresh snapshot must not trigger a network call"
    assert got["AAPL"] == "Apple Inc."


def test_stale_snapshot_triggers_a_refresh(monkeypatch, tmp_path):
    snap = tmp_path / "ticker_articles.json"
    snap.write_text(json.dumps({"schema": 1, "fetched": "2026-06-01",
                                "map": {"AAPL": "Stale Title"}}))
    rows, count = _resp(1)
    rows[0] = {"ticker": {"value": "AAPL"}, "enwiki": {"value": "Apple Inc."},
               "rank": {"value": "http://wikiba.se/ontology#NormalRank"}}
    monkeypatch.setattr(tm, "_get_json",
                        lambda q, ua, **kw: count if "COUNT" in q else {"results": {"bindings": rows}})
    monkeypatch.setattr(tm, "MIN_ROWS", 0)  # isolate from the floor guard -- not under test here
    got = tm.fetch_ticker_map(_cfg(tmp_path), "2026-08-17")   # 77 days old
    assert got["AAPL"] == "Apple Inc."


def test_unparseable_fetched_date_forces_a_refresh(monkeypatch, tmp_path):
    """Fail toward doing the work, not toward silently serving a snapshot forever."""
    snap = tmp_path / "ticker_articles.json"
    snap.write_text(json.dumps({"schema": 1, "fetched": "garbage", "map": {"A": "B"}}))
    calls = []
    monkeypatch.setattr(tm, "_get_json", lambda *a, **k: calls.append(1) or None)
    tm.fetch_ticker_map(_cfg(tmp_path), "2026-08-17")
    assert calls, "an unreadable date must not be treated as fresh"


def test_overrides_beat_the_snapshot(monkeypatch, tmp_path):
    ov = tmp_path / "ov.yml"
    ov.write_text('overrides:\n  DOW: {title: "Dow Inc.", why: "same-family"}\n')
    rows, count = _resp(1)
    rows[0] = {"ticker": {"value": "DOW"}, "enwiki": {"value": "Dow Chemical Company"},
               "rank": {"value": "http://wikiba.se/ontology#NormalRank"}}
    monkeypatch.setattr(tm, "_get_json",
                        lambda q, ua, **kw: count if "COUNT" in q else {"results": {"bindings": rows}})
    monkeypatch.setattr(tm, "MIN_ROWS", 0)  # isolate from the floor guard -- not under test here
    cfg = _cfg(tmp_path, overrides=str(ov))
    assert tm.fetch_ticker_map(cfg, "2026-08-17")["DOW"] == "Dow Inc."


# --- MIN_ROWS floor / regression guards -------------------------------------

def test_zero_rows_both_queries_agree_refuses_via_the_floor(monkeypatch, tmp_path):
    """The whole point: COUNT(*) equality alone cannot catch this. 0 returned / COUNT=0
    is an equality MATCH, so only an independent floor stops an empty map from being
    vendored over a healthy one and then served for up to max_age_days."""
    snap = tmp_path / "ticker_articles.json"
    snap.write_text(json.dumps({"schema": 1, "fetched": "2026-06-01", "rows_fetched": 4015,
                                "rows_expected": 4015, "map": {"AAPL": "Apple Inc."}}))
    rows, count = _resp(0, count=0)
    monkeypatch.setattr(tm, "_get_json",
                        lambda q, ua, **kw: count if "COUNT" in q else {"results": {"bindings": rows}})
    got = tm.fetch_ticker_map(_cfg(tmp_path), "2026-08-17")   # 77 days old -> refresh attempted
    assert got == {"AAPL": "Apple Inc."}, "must keep the healthy snapshot, not vendor an empty map"
    assert json.loads(snap.read_text())["map"] == {"AAPL": "Apple Inc."}, "snapshot unchanged"
    assert any("floor" in str(e).lower() for e in degrade.events())


def test_regression_against_previous_row_count_refuses(monkeypatch, tmp_path):
    """A merged/redirected EXCHANGES Q-id (or a regressed triple pattern) can shrink
    the live query AND the count query together, so they still agree -- guard against
    a big drop from the last known-good fetch even when equality holds."""
    snap = tmp_path / "ticker_articles.json"
    snap.write_text(json.dumps({"schema": 1, "fetched": "2026-06-01", "rows_fetched": 10,
                                "rows_expected": 10, "map": {"AAPL": "Apple Inc."}}))
    monkeypatch.setattr(tm, "MIN_ROWS", 0)  # isolate from the floor guard -- testing regression only
    rows, count = _resp(4, count=4)         # agrees with COUNT, but < half of the prior 10
    monkeypatch.setattr(tm, "_get_json",
                        lambda q, ua, **kw: count if "COUNT" in q else {"results": {"bindings": rows}})
    got = tm.fetch_ticker_map(_cfg(tmp_path), "2026-08-17")
    assert got == {"AAPL": "Apple Inc."}, "must keep the healthy snapshot, not vendor the shrunken one"
    assert json.loads(snap.read_text())["rows_fetched"] == 10, "snapshot unchanged"
    assert any("half of previous" in str(e).lower() for e in degrade.events())
