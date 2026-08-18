import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import radar.short_interest as si
from radar import degrade

RAW = json.loads(Path("tests/fixtures/finra_short_interest.json").read_text())


def _cfg(tmp_path, page_size=5000):
    return SimpleNamespace(short_interest=SimpleNamespace(
        snapshot_path=str(tmp_path / "short_interest.json"), page_size=page_size))


@pytest.fixture(autouse=True)
def _clear_degrade():
    # House pattern (see tests/test_tickermap.py:19-24) -- degrade has no clear();
    # reset() is the established mechanism. Without this, a warn-text assertion can
    # go permanently green by luck of collection order rather than by correctness.
    degrade.reset()
    yield


# --- parse_rows --------------------------------------------------------------

def test_parses_days_to_cover_and_shares():
    rows, settlement = si.parse_rows(RAW)
    assert rows["NVDA"]["days_to_cover"] == 2.47
    assert rows["NVDA"]["shares"] == 324052767
    assert settlement == "2026-07-31"


def test_sentinel_days_to_cover_is_filtered():
    """999.99 is a clamp at the max representable value (measured: AACAF has a
    non-zero ADV of 1331 and still clamps to 999.99), not a real 999-day cover.
    Unfiltered it tops every ranking."""
    rows, _ = si.parse_rows(RAW)
    assert "AAALF" not in rows


def test_parse_rows_never_raises():
    for junk in (None, {}, "nope", [{"symbolCode": None}], [{"bad": 1}]):
        rows, settlement = si.parse_rows(junk)
        assert rows == {} and settlement == ""


# --- discovery: GET /partitions ----------------------------------------------

def test_latest_settlement_hits_the_partitions_endpoint_with_get(monkeypatch):
    """Pins the discovery contract. The obvious alternative -- POST the data
    endpoint sorted by settlementDate descending, limit 1 -- is REJECTED by FINRA
    (measured HTTP 400: 'Sorting is allowed only if all partition keys are specified
    in an EQUAL CompareFilter'). This must never regress back to that shape."""
    seen = {}

    def fake_get(url, ua, **kw):
        seen["url"] = url
        return {"partitionFields": ["settlementDate"],
                "availablePartitions": [{"partitions": ["2026-07-31"]},
                                        {"partitions": ["2026-07-15"]}]}

    monkeypatch.setattr(si, "_get_json", fake_get)
    assert si._latest_settlement("ua") == "2026-07-31"
    assert seen["url"] == \
        "https://api.finra.org/partitions/group/otcMarket/name/consolidatedShortInterest"


def test_latest_settlement_returns_none_on_malformed_response(monkeypatch):
    monkeypatch.setattr(si, "_get_json", lambda *a, **k: {"availablePartitions": []})
    assert si._latest_settlement("ua") is None
    monkeypatch.setattr(si, "_get_json", lambda *a, **k: None)
    assert si._latest_settlement("ua") is None


# --- pagination: POST /data with an EQUAL compareFilter -----------------------

def test_fetch_all_pages_sends_equal_compare_filter_on_settlement(monkeypatch):
    """Pins the paging contract. An empty/missing compareFilters means FINRA does not
    scope the query to the current settlement -- it walks its full >3M-row archive,
    unordered by date (measured: offset 0 -> settlement 2020-04-15, offset 3,000,000
    -> settlement 2024-10-15)."""
    seen = []

    def fake_post(url, payload, ua, **kw):
        seen.append((url, payload))
        return [], 0

    monkeypatch.setattr(si, "_post_json", fake_post)
    si._fetch_all_pages("ua", 5000, "2026-07-31")
    assert len(seen) == 1
    url, payload = seen[0]
    assert url == "https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest"
    assert payload["compareFilters"] == [{"fieldName": "settlementDate",
                                          "fieldValue": "2026-07-31",
                                          "compareType": "EQUAL"}]
    assert payload["limit"] == 5000
    assert payload["offset"] == 0


def test_pagination_advances_offset_and_walks_until_short_page(monkeypatch, tmp_path):
    """5,000-row cap: a full page means there is more to fetch. Recording the payload
    (rather than a `lambda *a, **k: ...` stub that discards it) catches a
    non-advancing offset -- against real FINRA that replays the same page forever and
    hangs the job until the runner times out."""
    seen_offsets = []
    pages = [[dict(RAW[0], symbolCode=f"T{i}") for i in range(5000)],
             [dict(RAW[0], symbolCode="LAST")]]

    def fake_post(url, payload, ua, **kw):
        seen_offsets.append(payload["offset"])
        page = pages.pop(0) if pages else []
        return page, 5001

    monkeypatch.setattr(si, "_post_json", fake_post)
    monkeypatch.setattr(si, "_latest_settlement", lambda ua: "2026-08-14")
    rows, _ = si.fetch_short_interest(_cfg(tmp_path), "2026-08-17")
    assert "LAST" in rows, "must keep paging past a full 5000-row page"
    assert seen_offsets == [0, 5000]


# --- fetch_short_interest: settlement gate, snapshot, fail-soft ---------------

def test_refreshes_only_when_settlement_advances(monkeypatch, tmp_path):
    """Twice-monthly data. Re-pulling 22k rows daily is waste."""
    snap = tmp_path / "short_interest.json"
    snap.write_text(json.dumps({"schema": 1, "settlement": "2026-07-31",
                                "rows": {"NVDA": {"days_to_cover": 2.47, "shares": 1}}}))
    calls = []
    monkeypatch.setattr(si, "_post_json", lambda *a, **k: calls.append(1))
    monkeypatch.setattr(si, "_latest_settlement", lambda ua: "2026-07-31")
    rows, settlement = si.fetch_short_interest(_cfg(tmp_path), "2026-08-17")
    assert calls == [], "same settlement date must not trigger a full pull"
    assert rows["NVDA"]["days_to_cover"] == 2.47 and settlement == "2026-07-31"


def test_upstream_down_serves_snapshot_and_warns(monkeypatch, tmp_path):
    snap = tmp_path / "short_interest.json"
    snap.write_text(json.dumps({"schema": 1, "settlement": "2026-07-15",
                                "rows": {"NVDA": {"days_to_cover": 3.0, "shares": 1}}}))
    monkeypatch.setattr(si, "_post_json", lambda *a, **k: (None, None))
    monkeypatch.setattr(si, "_latest_settlement", lambda ua: None)
    rows, settlement = si.fetch_short_interest(_cfg(tmp_path), "2026-08-17")
    assert rows["NVDA"]["days_to_cover"] == 3.0
    assert settlement == "2026-07-15"
    assert any("snapshot" in str(e).lower() for e in degrade.events())


def test_both_gone_returns_empty_and_warns(monkeypatch, tmp_path):
    monkeypatch.setattr(si, "_post_json", lambda *a, **k: (None, None))
    monkeypatch.setattr(si, "_latest_settlement", lambda ua: None)
    assert si.fetch_short_interest(_cfg(tmp_path), "2026-08-17") == ({}, "")
    assert degrade.events(), "silent failure reads as an upstream outage no one hears about"


def test_row_count_mismatch_refuses_to_overwrite_snapshot(monkeypatch, tmp_path):
    """The same guard as the sibling tickermap task: a page that fails or comes back
    short mid-walk must not vendor a truncated slice of the universe. FINRA hands us
    the guard for free via the `record-total` response header."""
    snap = tmp_path / "short_interest.json"
    snap.write_text(json.dumps({"schema": 1, "settlement": "2026-07-15",
                                "rows": {"NVDA": {"days_to_cover": 3.0, "shares": 1}}}))
    pages = [[dict(RAW[0], symbolCode=f"T{i}") for i in range(5000)]]  # only 1 of 5

    def fake_post(url, payload, ua, **kw):
        page = pages.pop(0) if pages else []
        return page, 22341           # declared total never matches what we assembled

    monkeypatch.setattr(si, "_post_json", fake_post)
    monkeypatch.setattr(si, "_latest_settlement", lambda ua: "2026-07-31")
    rows, settlement = si.fetch_short_interest(_cfg(tmp_path), "2026-08-17")
    assert rows == {"NVDA": {"days_to_cover": 3.0, "shares": 1}}, \
        "must serve the old snapshot, not the truncated fetch"
    assert settlement == "2026-07-15"
    assert json.loads(snap.read_text())["settlement"] == "2026-07-15", "snapshot unchanged"
    assert any("row count" in str(e).lower() for e in degrade.events())


def test_row_count_mismatch_with_no_snapshot_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(si, "_post_json", lambda *a, **k: ([dict(RAW[0])], 22341))
    monkeypatch.setattr(si, "_latest_settlement", lambda ua: "2026-07-31")
    assert si.fetch_short_interest(_cfg(tmp_path), "2026-08-17") == ({}, "")


def test_snapshot_read_refilters_the_sentinel(monkeypatch, tmp_path):
    """The snapshot rides the data branch and is the one input this module trusts
    unvalidated -- a sentinel that slipped in through an older write path must still
    be dropped on read."""
    snap = tmp_path / "short_interest.json"
    snap.write_text(json.dumps({"schema": 1, "settlement": "2026-07-31",
                                "rows": {"NVDA": {"days_to_cover": 2.47, "shares": 1},
                                        "AAALF": {"days_to_cover": 999.99, "shares": 1000}}}))
    monkeypatch.setattr(si, "_post_json", lambda *a, **k: (None, None))
    monkeypatch.setattr(si, "_latest_settlement", lambda ua: None)
    rows, _ = si.fetch_short_interest(_cfg(tmp_path), "2026-08-17")
    assert "AAALF" not in rows
    assert rows["NVDA"]["days_to_cover"] == 2.47


def test_the_page_walk_has_a_hard_cap(monkeypatch):
    """`while True` with `offset += page_size` in a scheduled job is an unbounded loop:
    it exits only on a SHORT page, so a FINRA endpoint that ignores `offset` (or starts
    echoing full pages during an incident) walks forever and hangs the daily job until
    the runner kills it — no board, no email, no publish.

    The fake here raises rather than looping forever, so a missing cap fails this test in
    milliseconds instead of hanging the suite. 10 pages is 50,000 rows against a measured
    22,341-row settlement, so the cap cannot fire on healthy data."""
    calls = []

    def fake_post(url, payload, ua, **k):
        calls.append(payload["offset"])
        if len(calls) > si.MAX_PAGES + 5:
            raise AssertionError("unbounded page walk — the cap never fired")
        return ([dict(RAW[0]) for _ in range(3)], 999999)      # always a FULL page

    monkeypatch.setattr(si, "_post_json", fake_post)
    rows, total = si._fetch_all_pages("ua", 3, "2026-07-31")

    assert len(calls) == si.MAX_PAGES, f"walked {len(calls)} pages, cap is {si.MAX_PAGES}"
    assert calls == [i * 3 for i in range(si.MAX_PAGES)], "offset must still advance"
    assert rows is not None and len(rows) == si.MAX_PAGES * 3, "the capped rows are returned"
    assert any("page cap" in e["reason"] for e in degrade.events()), \
        "hitting the cap is abnormal — it must leave a breadcrumb"


def test_the_page_cap_is_generous_enough_never_to_fire_on_healthy_data(monkeypatch):
    """The other half: a cap that trips on a normal settlement would silently truncate
    the universe every day. Measured 22,341 rows at page_size 5000 = 5 pages."""
    assert si.MAX_PAGES * si.PAGE >= 50000


def test_tests_never_read_the_production_short_interest_snapshot(tmp_path):
    """conftest's isolation guard, asserted directly — the FINRA half, and the more
    dangerous one because it fires UNCONDITIONALLY.

    `fetch_short_interest` resolves its snapshot from the REAL config.yaml on every
    `run.main()`, `.github/workflows/daily.yml:39` restores `data/` from the orphan data
    branch before the pytest gate at `:44`, and short_interest.json is on the copy
    whitelist at `:80`. Once it exists, `_read_snapshot` succeeds, `_latest_settlement`
    returns None (transports stubbed dead), and the fetch takes its documented
    snapshot-fallback path — so `si_rows` is non-empty and the LED reads healthy where
    the test requires an outage. Measured with the file in place:

        tests/test_run_smoke.py:411  assert health["sources"]["finra_si"] == "down"
        E   assert 'ok' == 'down'

    No board ticker has to appear in the snapshot for this to fire; ANY parseable
    snapshot does it. The guard must NOT touch tmp_path snapshots — the fallback,
    settlement-short-circuit and clamp-refilter tests above all run through one."""
    from radar.config import load_config
    declared = load_config("config.yaml").short_interest.snapshot_path
    prod_dir = Path(declared).parent.name
    assert prod_dir == "data", "config moved its state dir; conftest tracks it, this test says so"

    doc = {"schema": 1, "settlement": "2026-07-31",
           "rows": {"IREN": {"days_to_cover": 6.7, "shares": 12_000_000}}}
    d = tmp_path / prod_dir; d.mkdir()
    prod = d / Path(declared).name
    prod.write_text(json.dumps(doc))
    assert si._read_snapshot(prod) is None, "anything under a declared state dir is production"

    ordinary = tmp_path / Path(declared).name
    ordinary.write_text(json.dumps(doc))
    rows, settlement = si._read_snapshot(ordinary)
    assert settlement == "2026-07-31" and rows["IREN"]["days_to_cover"] == 6.7
