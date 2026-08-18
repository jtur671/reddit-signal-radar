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
    # Must match the fixture rows' own settlementDate: the fetcher now refuses to vendor
    # a walk whose rows are dated anything other than the settlement it asked for (see
    # test_rows_dated_off_the_requested_settlement_are_not_vendored). The date here was
    # arbitrary before and disagreed with the rows it was serving.
    monkeypatch.setattr(si, "_latest_settlement", lambda ua: "2026-07-31")
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


def test_fetch_all_pages_reports_whether_the_walk_completed(monkeypatch):
    """The walk knows more than it used to report. The caller previously INFERRED
    completeness from `total is not None`, and that inference is exactly what produced
    the bug below: when FINRA omits the `record-total` header there is nothing to infer
    from, and the guard silently switched itself off."""
    monkeypatch.setattr(si, "_post_json", lambda *a, **k: ([{}, {}], None))
    assert si._fetch_all_pages("ua", 5000, "2026-07-31")[2] is True, \
        "a short page is the endpoint's promise that there is no more — that is complete"

    calls = []

    def flaky(url, payload, ua, **k):
        calls.append(1)
        return ([{} for _ in range(3)], None) if len(calls) == 1 else (None, None)

    monkeypatch.setattr(si, "_post_json", flaky)
    rows, _total, complete = si._fetch_all_pages("ua", 3, "2026-07-31")
    assert rows is not None and complete is False, "a page that failed mid-walk is partial"

    monkeypatch.setattr(si, "_post_json", lambda *a, **k: (None, None))
    assert si._fetch_all_pages("ua", 3, "2026-07-31") == (None, None, False)


def test_a_missing_record_total_on_a_partial_walk_refuses_to_vendor(monkeypatch, tmp_path):
    """`total is not None and len(raw) != total` skipped the guard ENTIRELY whenever
    FINRA omitted the `record-total` header — so a page that failed mid-walk vendored a
    partial universe stamped with the CORRECT settlement date, which then matches the
    refresh gate and is served for up to two weeks. Same failure class this branch has
    already fixed twice; the header is a courtesy, not a contract, so completeness has
    to be established by the walk itself."""
    snap = tmp_path / "short_interest.json"
    snap.write_text(json.dumps({"schema": 1, "settlement": "2026-07-15",
                                "rows": {"NVDA": {"days_to_cover": 3.0, "shares": 1}}}))
    pages = [[dict(RAW[0], symbolCode=f"T{i}") for i in range(5000)]]

    def fake_post(url, payload, ua, **kw):
        if pages:
            return pages.pop(0), None       # a full page, and NO record-total header
        return None, None                   # page 2 dies: the walk is partial

    monkeypatch.setattr(si, "_post_json", fake_post)
    monkeypatch.setattr(si, "_latest_settlement", lambda ua: "2026-07-31")
    rows, settlement = si.fetch_short_interest(_cfg(tmp_path), "2026-08-17")

    assert rows == {"NVDA": {"days_to_cover": 3.0, "shares": 1}}, \
        "must serve the old snapshot, not vendor 5,000 rows of a 22,341-row universe"
    assert settlement == "2026-07-15"
    assert json.loads(snap.read_text())["settlement"] == "2026-07-15", "snapshot unchanged"
    assert any("did not complete" in e["reason"] for e in degrade.events()), \
        "refusing to vendor is a decision — it must leave a breadcrumb like every other"


def test_a_missing_record_total_on_a_clean_walk_still_vendors(monkeypatch, tmp_path):
    """The other half, and the over-correction to avoid: FINRA omitting the header is
    not itself a failure. A walk that reached a SHORT page has the endpoint's own word
    that there is nothing more to fetch, and must vendor exactly as before."""
    snap = tmp_path / "short_interest.json"
    monkeypatch.setattr(si, "_post_json",
                        lambda url, payload, ua, **k: ([dict(RAW[0])], None))
    monkeypatch.setattr(si, "_latest_settlement", lambda ua: "2026-07-31")
    rows, settlement = si.fetch_short_interest(_cfg(tmp_path), "2026-08-17")

    assert rows["NVDA"]["days_to_cover"] == 2.47 and settlement == "2026-07-31"
    assert json.loads(snap.read_text())["settlement"] == "2026-07-31", "and it vendors"
    assert not any("did not complete" in e["reason"] for e in degrade.events())


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
    rows, total, complete = si._fetch_all_pages("ua", 3, "2026-07-31")

    assert complete is False, "a capped walk is by definition partial and must say so"
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


def test_a_snapshot_with_rows_but_no_settlement_is_unusable(monkeypatch, tmp_path):
    """Rows without their settlement date are not "undated data", they are NO data.

    run.py gates the entire board-assignment loop on `if si_as_of`, so a snapshot
    carrying rows and an empty settlement ships zero days-to-cover anywhere — while
    `si_rows` stays non-empty and lights `finra_si` green. That is the same "LED cannot
    tell the truth" failure as the tickermap LED that could never go down. A partial
    write or a hand-edit of the vendored file is the realistic path, and the file rides
    the data branch, which is exactly why this module re-validates it on every read.

    Refusing it here makes the fallback honest: no usable snapshot, so the source warns
    and reports the outage it is actually having."""
    snap = tmp_path / "short_interest.json"
    rows = {"rows": {"NVDA": {"days_to_cover": 2.47, "shares": 1}}}
    monkeypatch.setattr(si, "_latest_settlement", lambda ua: None)

    for doc in ({"schema": 1, **rows},                       # key absent entirely
                {"schema": 1, "settlement": "", **rows},     # present and empty
                {"schema": 1, "settlement": "   ", **rows},  # present and blank
                {"schema": 1, "settlement": None, **rows}):  # present and null
        snap.write_text(json.dumps(doc))
        assert si._read_snapshot(snap) is None, f"accepted a dateless snapshot: {doc}"

        got_rows, got_settlement = si.fetch_short_interest(_cfg(tmp_path), "2026-08-17")
        assert (got_rows, got_settlement) == ({}, ""), \
            "an unusable snapshot must not be served as if it were data"
        # `finra_si` is `"ok" if si_rows else "down"` — empty rows is what makes it red.
        assert not got_rows, "the LED keys on this, so it must be empty"

    assert any("snapshot both unavailable" in e["reason"] for e in degrade.events()), \
        "refusing the snapshot must leave the outage breadcrumb, not go quiet"


def test_a_snapshot_that_has_its_settlement_is_still_served(monkeypatch, tmp_path):
    """The other half, or the guard above is just a way to throw away good data: the
    documented outage fallback must still fire for a well-formed snapshot."""
    snap = tmp_path / "short_interest.json"
    snap.write_text(json.dumps({"schema": 1, "settlement": "2026-07-31",
                                "rows": {"NVDA": {"days_to_cover": 2.47, "shares": 1}}}))
    monkeypatch.setattr(si, "_latest_settlement", lambda ua: None)
    rows, settlement = si.fetch_short_interest(_cfg(tmp_path), "2026-08-17")
    assert rows["NVDA"]["days_to_cover"] == 2.47 and settlement == "2026-07-31"


def _strict(obj):
    """Round-trip `obj` through STRICT JSON — the dialect every consumer outside Python
    speaks. `json.dumps` emits bare `NaN`/`Infinity` happily and `json.loads` reads them
    back, so a Python round-trip proves nothing about what the trading bot or the
    browser will accept."""
    def boom(token):
        raise ValueError(f"not strict JSON: {token}")
    return json.loads(json.dumps(obj), parse_constant=boom)


# --- non-finite numbers: json.loads accepts Infinity/NaN/1e309 ---------------

def test_parse_rows_survives_a_non_finite_share_count():
    """`json.loads` accepts `Infinity`, `NaN` and `1e309` by DEFAULT (simplejson is not
    installed, so `requests.json()` is the stdlib parser), and `int(inf)` raises
    OverflowError — an ArithmeticError that `(TypeError, ValueError)` does not catch.
    Out of a function documented "Pure, never raises", it escaped to `main()`."""
    raw = json.loads('[{"symbolCode": "X", "daysToCoverQuantity": 2.0,'
                     ' "currentShortPositionQuantity": 1e309,'
                     ' "settlementDate": "2026-07-31"}]')
    assert raw[0]["currentShortPositionQuantity"] == float("inf"), "the stdlib parses this"
    assert si.parse_rows(raw) == ({}, "")


def test_non_finite_days_to_cover_is_rejected_at_the_parse_boundary():
    """A single NaN days-to-cover is a board-wide outage with every LED green.

    `json.dumps` writes it as a bare `NaN`, so: the vendored snapshot stops being valid
    strict JSON, `out/data.json` becomes unparseable for the consuming trading bot, and
    the dashboard's `|tojson` emits `NaN` inside a `<script type="application/json">`
    whose reader is `try{JSON.parse(...)}catch{return}` — killing the ENTIRE click-modal
    system, on every row, silently.

    The string forms matter as much as the float ones: `float("NaN")` and
    `float("Infinity")` both succeed, and a Java/Jackson producer serialises them exactly
    that way."""
    for bad in (float("nan"), float("inf"), float("-inf"), "NaN", "Infinity", "-Infinity"):
        rows, _ = si.parse_rows([{"symbolCode": "N", "daysToCoverQuantity": bad,
                                  "currentShortPositionQuantity": 5,
                                  "settlementDate": "2026-07-31"}])
        assert rows == {}, f"{bad!r} shipped a non-finite days-to-cover"

    mixed, settlement = si.parse_rows([{"symbolCode": "N", "daysToCoverQuantity": float("nan"),
                                        "currentShortPositionQuantity": 5,
                                        "settlementDate": "2026-07-31"}, dict(RAW[0])])
    assert set(mixed) == {"NVDA"}, "one poisoned row must not cost the good ones"
    assert settlement == "2026-07-31"
    assert _strict(mixed), "and what survives has to be JSON every consumer can read"


def test_snapshot_sentinel_refilter_coerces_before_comparing(tmp_path):
    """The snapshot re-filter compared with `!=` against a float, so a STRING
    `"999.99"` — the same clamp, serialised differently by a hand-edit or an older
    writer — slipped straight past and rendered as a real 999-day cover, topping every
    ranking. The file rides the data branch; re-validating it is the whole point of
    this read."""
    snap = tmp_path / "short_interest.json"
    snap.write_text(json.dumps({"schema": 1, "settlement": "2026-07-31",
                                "rows": {"NVDA": {"days_to_cover": 2.47, "shares": 1},
                                         "STR": {"days_to_cover": "999.99", "shares": 1},
                                         "NAN": {"days_to_cover": float("nan"), "shares": 1}}}))
    rows, settlement = si._read_snapshot(snap)
    assert set(rows) == {"NVDA"} and settlement == "2026-07-31"
    assert _strict(rows), "a snapshot NaN is the same board-wide modal outage"


# --- present-but-empty config keys -------------------------------------------

def test_present_but_empty_config_keys_do_not_crash_the_fetch(tmp_path):
    """A key present but EMPTY in config.yaml yields None through the real loader, and
    None is a value a `getattr(sc, k, <default>)` default never covers — getattr only
    fires when the ATTRIBUTE is absent. `Path(None)` and `int(None)` both raise
    TypeError, out of a fetcher that gates the daily publish."""
    from radar.config import load_config
    p = tmp_path / "config.yaml"
    p.write_text("short_interest:\n  snapshot_path:\n  page_size:\n")
    cfg = load_config(p)
    assert cfg.short_interest.snapshot_path is None, "the shape this pins must be real"
    assert cfg.short_interest.page_size is None

    # Both transports are stubbed dead by conftest and the defaulted snapshot path is
    # production state (walled off there too), so this is the documented both-gone path.
    assert si.fetch_short_interest(cfg, "2026-08-17", dry_run=True) == ({}, "")
    assert any("both unavailable" in e["reason"] for e in degrade.events()), \
        "an empty config key must degrade to the default, not take the publish down"


# --- the write path, which no --dry-run test can reach -----------------------

def test_a_non_utf8_snapshot_does_not_crash_the_write(monkeypatch, tmp_path):
    """Game day D1, and the one finding the pytest gate can NEVER catch: no test runs
    `main()` without `--dry-run`, so the snapshot WRITE is never exercised.

    The write was wrapped in `except OSError`, but the read-modify-write inside it
    (`snap.read_text() != text`) raises UnicodeDecodeError on a non-UTF-8 file — a
    ValueError, not an OSError. The file rides the data branch and is restored before
    every run, so this is not a one-off: it crashes the publish every single morning,
    indefinitely, with no board and no email. `_read_snapshot` twenty lines above
    catches `(OSError, ValueError)` on the SAME file and the SAME call.

    Writing unconditionally through the atomic writer removes the read entirely, which
    is the better half of the fix — the broadened except is the backstop."""
    snap = tmp_path / "short_interest.json"
    snap.write_bytes(b"\xff\xfe\x00 not utf-8 at all")
    monkeypatch.setattr(si, "_latest_settlement", lambda ua: "2026-07-31")
    monkeypatch.setattr(si, "_post_json", lambda url, payload, ua, **k: ([dict(RAW[0])], None))

    rows, settlement = si.fetch_short_interest(_cfg(tmp_path), "2026-08-17")
    assert rows["NVDA"]["days_to_cover"] == 2.47 and settlement == "2026-07-31"
    assert json.loads(snap.read_text())["settlement"] == "2026-07-31", \
        "and the unreadable file is replaced with a good one"


# --- the settlement date the live rows actually carry ------------------------

def test_undated_live_rows_are_not_vendored(monkeypatch, tmp_path):
    """The "green LED, no data" state, created on the LIVE PARSE path where
    `_read_snapshot` already refuses it on the READ path.

    `parse_rows` returns `(rows, "")` for rows with no settlementDate, and the fetcher
    vendored `{"settlement": "", ...}` and returned it: run.py gates its board loop on
    `if si_as_of`, so ZERO days-to-cover render while `si_rows` is non-empty and the
    finra_si LED reads green. Worse, `_read_snapshot` correctly rejects an undated
    snapshot — so the file just written is dead on arrival and the fallback stays
    unavailable until a good fetch lands. The guard has to live where the bad state is
    created."""
    snap = tmp_path / "short_interest.json"
    snap.write_text(json.dumps({"schema": 1, "settlement": "2026-07-15",
                                "rows": {"NVDA": {"days_to_cover": 3.0, "shares": 1}}}))
    undated = {k: v for k, v in RAW[0].items() if k != "settlementDate"}
    monkeypatch.setattr(si, "_latest_settlement", lambda ua: "2026-07-31")
    monkeypatch.setattr(si, "_post_json", lambda url, payload, ua, **k: ([undated], None))

    rows, settlement = si.fetch_short_interest(_cfg(tmp_path), "2026-08-17")
    assert (rows, settlement) == ({"NVDA": {"days_to_cover": 3.0, "shares": 1}}, "2026-07-15"), \
        "must keep the dated snapshot, not vendor rows that carry no date"
    assert json.loads(snap.read_text())["settlement"] == "2026-07-15", "snapshot unchanged"
    assert any("settlementDate" in e["reason"] for e in degrade.events())


def test_rows_dated_off_the_requested_settlement_are_not_vendored(monkeypatch, tmp_path):
    """FINRA's archive is unordered by date and >3M rows deep — measured offset 0 ->
    settlement 2020-04-15. If the EQUAL compareFilter is ever dropped, mishandled or
    ignored during an incident, the walk returns real, well-formed rows from six years
    ago, and they were vendored under their OWN date: a stale position published as
    current, then served by the settlement short-circuit until FINRA moves on.

    The discovered `latest` is what this run asked for. What comes back has to be it."""
    snap = tmp_path / "short_interest.json"
    snap.write_text(json.dumps({"schema": 1, "settlement": "2026-07-15",
                                "rows": {"NVDA": {"days_to_cover": 3.0, "shares": 1}}}))
    stale = dict(RAW[0], settlementDate="2020-04-15")
    monkeypatch.setattr(si, "_latest_settlement", lambda ua: "2026-07-31")
    monkeypatch.setattr(si, "_post_json", lambda url, payload, ua, **k: ([stale], None))

    rows, settlement = si.fetch_short_interest(_cfg(tmp_path), "2026-08-17")
    assert (rows, settlement) == ({"NVDA": {"days_to_cover": 3.0, "shares": 1}}, "2026-07-15")
    assert json.loads(snap.read_text())["settlement"] == "2026-07-15", "snapshot unchanged"
    assert any("2020-04-15" in e["reason"] and "2026-07-31" in e["reason"]
               for e in degrade.events()), "the breadcrumb must name both dates"


def test_fetch_short_interest_never_raises(monkeypatch, tmp_path):
    """The contractual backstop. This fetcher gates the daily publish and is documented
    as fail-soft throughout; no config typo, upstream novelty or unforeseen value should
    ever be able to take the board down again. The specific handlers above still do the
    real work — this only catches what none of them anticipated."""
    def boom(*a, **k):
        raise RuntimeError("upstream novelty")

    monkeypatch.setattr(si, "_latest_settlement", boom)
    assert si.fetch_short_interest(_cfg(tmp_path), "2026-08-17") == ({}, "")
    assert any("upstream novelty" in e["reason"] for e in degrade.events())
