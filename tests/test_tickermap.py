import json
import types
from pathlib import Path

import pytest

import radar.tickermap as tm
from radar import degrade

RAW = json.loads(Path("tests/fixtures/wikidata_rows.json").read_text())


def _cfg(tmp_path, overrides="radar/ticker_overrides.yml"):
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
    cfg = _cfg(tmp_path, overrides=str(ov))
    assert tm.fetch_ticker_map(cfg, "2026-08-17")["DOW"] == "Dow Inc."
