import json
import types
from pathlib import Path

import pytest
import yaml

import radar.tickermap as tm
from radar import degrade

RAW = json.loads(Path("tests/fixtures/wikidata_rows.json").read_text())
# The day the end-date rule is evaluated against. GOOG's 2016 end-date and BBBY's
# 2023 one are both in the past relative to it; FUTURE_END below is not.
RUN_DAY = "2026-08-17"
FUTURE_END = "2027-06-30T00:00:00Z"
_NORMAL = "http://wikiba.se/ontology#NormalRank"


def _rows(*rows):
    """SPARQL-shaped bindings from (ticker, title, end) triples; end may be None."""
    return {"results": {"bindings": [
        {"ticker": {"value": tk}, "enwiki": {"value": title},
         "rank": {"value": _NORMAL},
         **({"end": {"value": end}} if end is not None else {})}
        for tk, title, end in rows]}}


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
    assert tm.parse_rows(RAW, RUN_DAY)["AAPL"] == "Apple Inc."


def test_deprecated_rank_is_dropped():
    """AAL has a DeprecatedRank row for Anglo American; the live row must win."""
    assert tm.parse_rows(RAW, RUN_DAY)["AAL"] == "American Airlines Group"


def test_past_end_date_dropped_when_a_live_alternative_exists():
    """Google's listing ended 2016-01-01 and Alphabet's has no end date."""
    assert tm.parse_rows(RAW, RUN_DAY)["GOOG"] == "Alphabet Inc."


def test_sole_statement_is_kept_even_when_ended():
    """The proviso: an ended statement survives when it is the ONLY one for that
    ticker. Without this, every historical-only listing silently vanishes."""
    assert tm.parse_rows(RAW, RUN_DAY)["BBBY"] == "Bed Bath & Beyond"


def test_a_future_end_date_is_not_treated_as_ended():
    """The spec (2.3) and this function's own docstring both say to drop statements whose
    end-date is IN THE PAST; the code tested only that an end-date was PRESENT.

    A planned delisting is recorded on Wikidata as a FUTURE pq:P582 — on the statement
    that is still the current listing. Presence-testing drops it, so this ticker had two
    "ended" statements, no live alternative, and was omitted as ambiguous."""
    raw = _rows(("FUTR", "Futura (delisted 2016)", "2016-01-01T00:00:00Z"),
                ("FUTR", "Futura Inc.", FUTURE_END))
    assert tm.parse_rows(raw, RUN_DAY)["FUTR"] == "Futura Inc."


def test_a_future_end_date_beats_a_stale_undated_statement():
    """The corruption case, and the reason this is not cosmetic. Here the future-dated
    statement is the CORRECT current listing and the undated one is stale. Presence-
    testing drops the correct one and leaves exactly one survivor — so the ticker
    resolves cleanly, confidently, to the WRONG article, which for a pageviews ingest is
    a plausible, well-formed, entirely fictitious signal (see the module docstring)."""
    raw = _rows(("PLAN", "Stale Holdings", None),
                ("PLAN", "Planned Delisting Corp", FUTURE_END))
    got = tm.parse_rows(raw, RUN_DAY)
    assert got.get("PLAN") != "Stale Holdings", "a future end-date is not an ended listing"
    assert "PLAN" not in got, "two live candidates are OMITTED, never guessed between"


def test_an_end_date_of_today_is_not_yet_past():
    """A listing that ends today is still listed today. `<`, not `<=`."""
    raw = _rows(("EOD", "Ends Today Inc.", RUN_DAY + "T00:00:00Z"),
                ("EOD", "Some Other Article", None))
    assert "EOD" not in tm.parse_rows(raw, RUN_DAY), "still live, so still ambiguous"


def test_a_malformed_end_date_does_not_raise_and_keeps_the_statement_in_play():
    """'Pure, never raises' is this module's contract and a date string is the one field
    that invites a parse. An unparseable date (and an unparseable run day) is treated as
    NOT ended, deliberately: keeping a statement in play can only ADD a candidate, and an
    ambiguous ticker is omitted. Treating it as ended would DROP it and let the survivor
    win — which is how you get a silently wrong title. A missing title is a non-event."""
    raw = _rows(("JUNK", "Malformed Corp", "not-a-date"),
                ("JUNK", "Other Corp", None))
    assert "JUNK" not in tm.parse_rows(raw, RUN_DAY), "unjudgeable, so it still competes"

    for bad in (None, "", "nope", 5, {"value": "x"}):
        raw = _rows(("SOLO", "Sole Statement Inc.", bad))
        assert tm.parse_rows(raw, RUN_DAY)["SOLO"] == "Sole Statement Inc."
        assert tm.parse_rows(raw, bad) == {"SOLO": "Sole Statement Inc."}, \
            "a malformed run day must not raise either"


def test_unresolved_same_family_ambiguity_is_omitted_not_guessed():
    """DOW has two live, same-rank candidates. parse_rows must NOT pick one at
    random -- the override file is what resolves these."""
    assert "DOW" not in tm.parse_rows(RAW, RUN_DAY)


def test_parse_rows_never_raises_on_junk():
    for junk in (None, {}, {"results": {}}, {"results": {"bindings": "nope"}},
                 {"results": {"bindings": [{"ticker": {}}]}}):
        assert tm.parse_rows(junk, RUN_DAY) == {}


def test_parse_rows_coerces_non_string_ticker_and_title():
    """'Never raises' is the whole contract, and dict[str, str] is the whole return
    type -- a non-string binding value used to break both: ticker.upper() raised
    AttributeError, and a passed-through non-string title broke the type contract."""
    raw = {"results": {"bindings": [
        {"ticker": {"value": 5}, "enwiki": {"value": 7},
         "rank": {"value": "http://wikiba.se/ontology#NormalRank"}}]}}
    got = tm.parse_rows(raw, RUN_DAY)
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


# --- curated override file --------------------------------------------------

def test_every_override_title_is_verified():
    """A typo'd override is a wrong-entity bug of exactly the kind this subsystem
    exists to eliminate, so pin every title against the verified fixture rather than
    trusting the YAML. Regenerate the fixture only alongside a fresh API check."""
    verified = json.loads(Path("tests/fixtures/override_titles.json").read_text())
    got = tm.load_overrides("radar/ticker_overrides.yml")
    assert got, "override file must not be empty"
    for ticker, title in got.items():
        assert ticker in verified, f"{ticker} is not in the verified fixture"
        assert title == verified[ticker], f"{ticker}: {title!r} != verified {verified[ticker]!r}"


def test_every_override_has_a_reason():
    """`why` is what makes the file reviewable a year from now."""
    doc = yaml.safe_load(Path("radar/ticker_overrides.yml").read_text())
    for ticker, entry in doc["overrides"].items():
        assert entry.get("why"), f"{ticker} has no `why`"


def test_a_null_overrides_path_still_applies_the_curated_overrides(tmp_path):
    """A present-but-EMPTY `overrides_path:` in config.yaml yields None, and None is a
    value a `getattr(tc, "overrides_path", <default>)` default never covers — getattr
    only fires when the ATTRIBUTE is absent. load_overrides(None) then returns {} rather
    than raising (Path(None) TypeError, caught), so the failure is silent: every curated
    fix — DOW, HTZ, SNOW, QQQ, the entire reason this file exists — stops applying while
    run.py's health floor, which resolves the same key with `or`, still counts 30 of them
    and lights the tickermap LED green. Measured before the fix: 30 resolved for the
    floor, 0 applied by fetch_ticker_map. The two sites must resolve identically.

    Both shapes are pinned: the key present-but-null, and the key absent entirely."""
    curated = tm.load_overrides("radar/ticker_overrides.yml")
    assert curated, "the curated file must not be empty or this test asserts nothing"

    null_key = types.SimpleNamespace(
        snapshot_path=str(tmp_path / "ticker_articles.json"),
        overrides_path=None, max_age_days=30)
    no_key = types.SimpleNamespace(
        snapshot_path=str(tmp_path / "ticker_articles.json"), max_age_days=30)
    for tc in (null_key, no_key):
        # Transports are stubbed dead by conftest and the snapshot does not exist, so
        # the map is overrides-only — which is exactly the surface under test.
        got = tm.fetch_ticker_map(types.SimpleNamespace(tickermap=tc), "2026-08-17")
        assert got == curated, f"{tc!r} dropped the curated overrides"


def test_load_overrides_of_a_null_path_is_empty_rather_than_a_crash():
    """The property the call sites rely on, pinned directly: it is BECAUSE this returns
    {} instead of raising that a null path fails silently, and silence is what made the
    bug above survive review."""
    assert tm.load_overrides(None) == {}
    assert tm.load_overrides("") == {}


def test_tests_never_read_the_production_ticker_snapshot(tmp_path):
    """conftest's isolation guard, asserted directly — the tickermap half.

    `fetch_ticker_map` resolves its snapshot from the REAL config.yaml on every
    `run.main()`, `.github/workflows/daily.yml:39` restores `data/` from the orphan data
    branch before the pytest gate at `:44`, and ticker_articles.json is on the copy
    whitelist at `:80` — so the first successful production run vendors it and the NEXT
    day's gate reads it. Measured with a realistic snapshot in place:

        tests/test_run_smoke.py:409  assert calls == []
        E   assert [('IREN Limited', '20260712', '20260816')] == []

    A red gate means no board, no email, no Pages deploy and no data commit, every day
    thereafter. The guard must NOT touch tmp_path snapshots — every fetch_ticker_map
    test above drives the real snapshot/freshness/regression logic through one, and a
    blanket stub would leave them green while asserting nothing."""
    from radar.config import load_config
    declared = load_config("config.yaml").tickermap.snapshot_path
    prod_dir = Path(declared).parent.name
    assert prod_dir == "data", "config moved its state dir; conftest tracks it, this test says so"

    doc = {"schema": 1, "fetched": "2026-08-16", "rows_fetched": 4015,
           "rows_expected": 4015, "map": {"IREN": "Iris Energy"}}
    d = tmp_path / prod_dir; d.mkdir()
    prod = d / Path(declared).name
    prod.write_text(json.dumps(doc))
    assert tm._snapshot_map(prod) is None, "anything under a declared state dir is production"
    assert tm._snapshot_age_days(prod, "2026-08-17") is None
    assert tm._snapshot_rows(prod) is None

    ordinary = tmp_path / Path(declared).name
    ordinary.write_text(json.dumps(doc))
    assert tm._snapshot_map(ordinary) == {"IREN": "Iris Energy"}
    assert tm._snapshot_age_days(ordinary, "2026-08-17") == 1
    assert tm._snapshot_rows(ordinary) == 4015
