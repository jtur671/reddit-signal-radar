import json

import pytest

from radar import about, degrade

# Captured at import time, BEFORE conftest's autouse hermeticity fixture stubs
# about.fetch_summary out. The two canonical-title tests below need the real
# function body (with requests.get stubbed) to prove it reads the response field.
_REAL_FETCH_SUMMARY = about.fetch_summary


@pytest.fixture(autouse=True)
def _clear_degrade():
    # House pattern (tests/test_tickermap.py, tests/test_health.py): degrade has no
    # clear() -- reset() is the established reset mechanism.
    degrade.reset()
    yield


def test_describe_uses_cache_without_network(monkeypatch):
    # cached ticker -> no fetch
    called = {"n": 0}
    monkeypatch.setattr(about, "fetch_summary", lambda *a, **k: called.__setitem__("n", called["n"] + 1))
    cache = {"HPE": {"name": "Hewlett Packard Enterprise", "desc": "IT company", "extract": "...",
                     "title": "Hewlett Packard Enterprise"}}
    got = about.describe("HPE", "Hewlett Packard Enterprise", "Hewlett Packard Enterprise", cache)
    assert got["desc"] == "IT company" and called["n"] == 0


def test_describe_fetches_and_caches_miss(monkeypatch):
    monkeypatch.setattr(about, "fetch_summary",
                        lambda title, ua="x": {"desc": "Space tourism company",
                                               "extract": "Virgin Galactic...",
                                               "title": "Virgin Galactic"})
    cache = {}
    got = about.describe("SPCE", "Virgin Galactic", "Virgin Galactic", cache)
    assert got["name"] == "Virgin Galactic" and got["desc"] == "Space tourism company"
    assert cache["SPCE"]["extract"].startswith("Virgin Galactic")   # persisted to cache


def test_describe_graceful_when_lookup_fails(monkeypatch):
    monkeypatch.setattr(about, "fetch_summary", lambda *a, **k: None)
    got = about.describe("ZZZZ", "Nonexistent Co", "Nonexistent Co", {})
    assert got["name"] == "Nonexistent Co" and got["desc"] == "" and got["extract"] == ""


def test_load_cache_bad_file(tmp_path):
    p = tmp_path / "about.json"; p.write_text("not json")
    assert about.load_cache(p) == {}


def test_unmapped_ticker_makes_no_request(monkeypatch):
    """The anti-fuzzy guarantee. A ticker with no title must not fall back to a
    name-based lookup -- that is what resolved AAPL to the fruit. Assert on the CALL
    COUNT, not just the return value: a None return could also mean 'fetched and
    missed', which is a different and much worse behavior."""
    calls = []
    monkeypatch.setattr(about, "fetch_summary", lambda *a, **k: calls.append(a) or None)
    cache = {}
    entry = about.describe("MVIS", "MicroVision", None, cache)
    assert calls == [], "no title must mean no request"
    # Exact shape on purpose: it pins that an unmapped ticker invents NOTHING. `mapped`
    # is "" for the same reason every other field is — there was no title to ask for.
    assert entry == {"name": "MicroVision", "desc": "", "extract": "", "title": "",
                     "mapped": ""}


def test_exact_title_is_what_gets_fetched(monkeypatch):
    seen = {}
    def fake(title, ua="x"):
        seen["title"] = title
        return {"desc": "American multinational technology company", "extract": "...",
                "title": "Apple Inc."}
    monkeypatch.setattr(about, "fetch_summary", fake)
    about.describe("AAPL", "Apple", "Apple Inc.", {})
    assert seen["title"] == "Apple Inc.", "must fetch the mapped title, not the company name"


def test_cache_with_stale_schema_is_discarded(tmp_path):
    p = tmp_path / "about.json"
    p.write_text(json.dumps({"schema": 0, "entries": {"AAPL": {"name": "Apple",
                                                               "desc": "Edible fruit"}}}))
    assert about.load_cache(p) == {}, "a poisoned cache must not survive the fix"


def test_cache_without_schema_is_discarded(tmp_path):
    """The live data-branch cache predates schema versioning and holds 34 wrong-entity
    entries. They are cache HITS, so they never self-heal -- they must be dropped."""
    p = tmp_path / "about.json"
    p.write_text(json.dumps({"AAPL": {"name": "Apple", "desc": "Edible fruit"}}))
    assert about.load_cache(p) == {}


def test_current_schema_round_trips(tmp_path):
    p = tmp_path / "about.json"
    about.save_cache(p, {"AAPL": {"name": "Apple", "desc": "tech company", "extract": "",
                                  "title": "Apple Inc."}})
    loaded = about.load_cache(p)
    assert loaded["AAPL"]["desc"] == "tech company"
    # The canonical title is what the pageviews ingest consumes — pin that it survives
    # the round trip, or the redirect fix silently stops reaching its only consumer.
    assert loaded["AAPL"]["title"] == "Apple Inc."


def test_a_blank_cached_title_is_refetched_once_a_title_arrives(monkeypatch):
    """A blank entry must NOT be a permanent hit, or the ticker map can never grow.

    An unmapped ticker still gets cached as {'desc':'','extract':'','title':''}, and a
    plain `if cached is not None` makes that a hit forever. That would render the whole
    of radar/ticker_overrides.yml inert for any ticker that reached the board before its
    override existed, along with the monthly Wikidata refresh and the canonical title the
    pageviews ingest depends on. Measured on the live data branch: IREN's entry is
    exactly this — {'name': 'Iris Energy', 'desc': '', 'extract': ''}."""
    calls = []
    def fake(title, ua="x"):
        calls.append(title)
        return {"desc": "Bitcoin miner", "extract": "IREN Limited is...", "title": "IREN Limited"}
    monkeypatch.setattr(about, "fetch_summary", fake)

    cache = {}
    about.describe("IREN", "Iris Energy", None, cache)          # day 1: unmapped
    assert calls == [] and cache["IREN"]["title"] == ""

    got = about.describe("IREN", "Iris Energy", "IREN Limited", cache)   # day 2: mapped
    assert calls == ["IREN Limited"], "a blank entry must re-fetch once a title exists"
    assert got["title"] == "IREN Limited" and got["desc"] == "Bitcoin miner"
    assert cache["IREN"]["title"] == "IREN Limited", "and the cache must be updated"


def test_a_resolved_entry_is_still_a_permanent_hit(monkeypatch):
    """The other half: re-fetching blanks must not turn the cache into a no-op. An entry
    that already carries a title is never fetched again — that is the whole point of it."""
    calls = []
    monkeypatch.setattr(about, "fetch_summary", lambda *a, **k: calls.append(a) or None)
    cache = {"AAPL": {"name": "Apple", "desc": "tech company", "extract": "...",
                      "title": "Apple Inc."}}
    got = about.describe("AAPL", "Apple", "Apple Inc.", cache)
    assert calls == [] and got["desc"] == "tech company"


def test_an_unmapped_blank_stays_a_hit_while_it_is_still_unmapped(monkeypatch):
    """And a blank entry with still no title makes no request either — there is nothing
    better to ask for, so this must not become a daily retry of nothing."""
    calls = []
    monkeypatch.setattr(about, "fetch_summary", lambda *a, **k: calls.append(a) or None)
    cache = {"MVIS": {"name": "MicroVision", "desc": "", "extract": "", "title": ""}}
    about.describe("MVIS", "MicroVision", None, cache)
    assert calls == []


def test_tests_never_read_the_production_about_cache(tmp_path):
    """conftest's isolation guard, asserted directly.

    `run.py` loads the RELATIVE production path `data/about.json`, and
    `.github/workflows/daily.yml:39` restores `data/` from the orphan data branch BEFORE
    the pytest gate at `:44`. So without this guard the suite reads production cache
    state: one negative-cached board ticker (IREN is one today) turns the gate red, and
    a red gate means no board, no email and no data-branch commit until someone
    hand-edits the data branch. The guard must NOT touch ordinary tmp_path loads — the
    schema-migration and round-trip tests above run the real loader, and a blanket stub
    would leave them green while asserting nothing."""
    d = tmp_path / "data"; d.mkdir()
    prod = d / "about.json"
    about.save_cache(prod, {"IREN": {"name": "Iris Energy", "desc": "", "extract": "",
                                     "title": ""}})
    assert about.load_cache(prod) == {}, "anything under a data/ dir is production state"

    ordinary = tmp_path / "about.json"
    about.save_cache(ordinary, {"AAPL": {"name": "Apple", "desc": "d", "extract": "",
                                         "title": "Apple Inc."}})
    assert about.load_cache(ordinary)["AAPL"]["title"] == "Apple Inc."


def test_canonical_title_is_cached_not_the_requested_one(monkeypatch):
    """Measured: the pageviews API does NOT follow redirects -- it returns HTTP 200 with
    the REDIRECT page's own traffic. `Dow Inc.` is a redirect and yields 12 views/day
    against the canonical `Dow Chemical Company`'s 468, a 39x silent understatement.
    Wikidata's own sitelink for Q62739842 IS `Dow Inc.`, so the vendored snapshot emits
    redirect titles too. The REST summary DOES follow the redirect, so its response
    already carries the canonical title -- cache it, no extra call needed."""
    monkeypatch.setattr(about, "fetch_summary",
                        lambda title, ua="x": {"desc": "American chemical company",
                                               "extract": "Dow Inc. is...",
                                               "title": "Dow Chemical Company"})
    cache = {}
    entry = about.describe("DOW", "Dow", "Dow Inc.", cache)
    assert entry["title"] == "Dow Chemical Company"
    assert cache["DOW"]["title"] == "Dow Chemical Company"


def test_fetch_summary_reads_the_canonical_title_off_the_response(monkeypatch):
    """The REST summary response's `title` is post-redirect. Verified live against
    en.wikipedia.org: GET .../summary/Dow_Inc. returns title 'Dow Chemical Company'."""
    class Resp:
        status_code = 200
        def json(self):
            return {"type": "standard", "title": "Dow Chemical Company",
                    "description": "American chemical company", "extract": "Dow Inc. is..."}
    monkeypatch.setattr(about.requests, "get", lambda *a, **k: Resp())
    got = _REAL_FETCH_SUMMARY("Dow Inc.", "ua")
    assert got["title"] == "Dow Chemical Company"
    assert got["desc"] == "American chemical company"


def test_fetch_summary_returns_none_without_a_title(monkeypatch):
    """The anti-fuzzy guarantee at the transport layer too: no title, no request."""
    calls = []
    monkeypatch.setattr(about.requests, "get", lambda *a, **k: calls.append(a))
    assert _REAL_FETCH_SUMMARY(None, "ua") is None
    assert _REAL_FETCH_SUMMARY("", "ua") is None
    assert calls == []


def test_a_changed_mapped_title_re_fetches_and_updates(monkeypatch):
    """The third variant of the never-heals bug: a CHANGED mapping.

    A cached entry that is a permanent hit for ANY truthy title makes two live inputs
    inert. radar/ticker_overrides.yml is a CURATED file whose whole purpose is being
    corrected over time, and the Wikidata snapshot refreshes monthly — so a fix landing
    in either one is silently ignored for every ticker already in the cache. Worse than
    a stale blurb: run.py:178 PREFERS the cached title when it builds pv_titles, and a
    stale title can itself be a redirect, which reintroduces the 39x pageviews
    understatement this subsystem exists to eliminate."""
    calls = []

    def fake(title, ua="x"):
        calls.append(title)
        return {"desc": "Bitcoin miner", "extract": "IREN Limited is...",
                "title": "IREN Limited"}
    monkeypatch.setattr(about, "fetch_summary", fake)
    cache = {"IREN": {"name": "Iris Energy", "desc": "Australian data-centre operator",
                      "extract": "...", "title": "Iris Energy", "mapped": "Iris Energy"}}

    got = about.describe("IREN", "Iris Energy", "IREN Limited", cache)
    assert calls == ["IREN Limited"], "a corrected mapping must re-fetch"
    assert got["desc"] == "Bitcoin miner" and got["title"] == "IREN Limited"
    assert cache["IREN"]["title"] == "IREN Limited", "and the cache must be updated"
    assert cache["IREN"]["mapped"] == "IREN Limited", "stamped with what produced it"


def test_an_unchanged_mapped_title_never_re_fetches_even_for_a_redirect(monkeypatch):
    """The regression guard on the fix above, and the reason it cannot be a naive
    `cached["title"] != title`.

    The two titles are DIFFERENT KINDS. The cached one is CANONICAL (post-redirect, off
    the REST summary response); the incoming one is MAPPED (from tickermap, whose
    Wikidata sitelinks include redirect titles). For any redirect-mapped ticker they
    legitimately differ on every single run — `Dow Inc.` in, `Dow Chemical Company`
    cached — so comparing them would re-fetch that ticker forever: a daily live request
    per redirect ticker, in the job that gates the 6:17 AM publish.

    Building the entry through describe() rather than hand-writing it is the point: it
    proves the stamp survives the same round trip production takes."""
    calls = []
    monkeypatch.setattr(about, "fetch_summary",
                        lambda title, ua="x": calls.append(title) or
                        {"desc": "American chemical company", "extract": "Dow Inc. is...",
                         "title": "Dow Chemical Company"})
    cache = {}

    about.describe("DOW", "Dow", "Dow Inc.", cache)                  # day 1: a real miss
    assert calls == ["Dow Inc."]
    assert cache["DOW"]["title"] == "Dow Chemical Company", "canonical, not what we asked"

    for _ in range(3):                                               # days 2-4: unchanged map
        got = about.describe("DOW", "Dow", "Dow Inc.", cache)
    assert calls == ["Dow Inc."], "an unchanged mapping must never re-fetch"
    assert got["title"] == "Dow Chemical Company"


def test_an_entry_written_before_the_stamp_existed_heals_without_a_cache_wipe(monkeypatch):
    """The migration, chosen over a SCHEMA bump precisely so the live cache survives.

    Entries already on the data branch carry no `mapped` key. Falling back to the
    canonical title for those is exact for the common case (map title == canonical
    title, so nothing re-fetches) and costs at most ONE re-fetch for a redirect-mapped
    ticker, after which the entry carries its stamp and is stable forever."""
    calls = []
    monkeypatch.setattr(about, "fetch_summary",
                        lambda title, ua="x": calls.append(title) or
                        {"desc": "American chemical company", "extract": "...",
                         "title": "Dow Chemical Company"})
    legacy_plain = {"AAPL": {"name": "Apple", "desc": "tech company", "extract": "...",
                             "title": "Apple Inc."}}
    about.describe("AAPL", "Apple", "Apple Inc.", legacy_plain)
    assert calls == [], "an unstamped entry whose map title still matches stays a hit"

    legacy_redirect = {"DOW": {"name": "Dow", "desc": "American chemical company",
                               "extract": "...", "title": "Dow Chemical Company"}}
    for _ in range(3):
        about.describe("DOW", "Dow", "Dow Inc.", legacy_redirect)
    assert calls == ["Dow Inc."], "exactly one healing fetch, then the stamp holds"
    assert legacy_redirect["DOW"]["mapped"] == "Dow Inc."


# --- hostile responses: a 200 body that is not a dict, or fields that are not strings ---

@pytest.mark.parametrize("body", [None, [], "Apple Inc.", 5])
def test_a_non_dict_200_body_returns_none_instead_of_killing_the_run(monkeypatch, body):
    """`fetch_summary` is documented "Never raises", and that has to hold against what
    actually arrives on the wire, not against what the REST docs promise: a proxy error
    page, an empty array, a bare literal. The type read sat OUTSIDE the try, so
    `AttributeError: 'NoneType' object has no attribute 'get'` walked all the way up
    through describe() -> _enrich_ticker() -> main() and killed the run BEFORE it
    rendered — no board, no email, no publish, for a malformed body on one ticker."""
    class Resp:
        status_code = 200
        def json(self):
            return body
    monkeypatch.setattr(about.requests, "get", lambda *a, **k: Resp())
    assert _REAL_FETCH_SUMMARY("Apple Inc.", "ua") is None


def test_non_string_fields_are_coerced_rather_than_crashing(monkeypatch):
    """`(d.get("title") or "").strip()` is an AttributeError the moment the field is a
    number. The crash is only half of it: a non-string `title` that survived into the
    cache is what run.py:178 hands to pageviews.fetch_attention, so a bad field here
    detonates in a different module a hundred lines later. Coerce at the boundary."""
    class Resp:
        status_code = 200
        def json(self):
            return {"type": "standard", "title": 5, "description": ["a", "b"],
                    "extract": {"x": 1}}
    monkeypatch.setattr(about.requests, "get", lambda *a, **k: Resp())
    got = _REAL_FETCH_SUMMARY("Apple Inc.", "ua")
    assert got["title"] == "5"
    assert all(isinstance(v, str) for v in got.values()), got


# --- hostile cache entries ------------------------------------------------------

def test_a_non_dict_cached_entry_is_dropped_by_the_loader(tmp_path):
    """`data/about.json` rides the orphan data branch and is hand-editable. load_cache
    validated only that `entries` was a dict and passed every VALUE through untouched,
    so `{"AAPL": 5}` reached describe() and `cached.get("title")` raised. Drop the bad
    value, keep the rest — one poisoned entry must not cost the whole cache."""
    p = tmp_path / "about.json"
    p.write_text(json.dumps({"schema": about.SCHEMA, "entries": {
        "AAPL": 5,
        "DOW": {"name": "Dow", "desc": "American chemical company", "extract": "...",
                "title": "Dow Chemical Company", "mapped": "Dow Inc."}}}))
    loaded = about.load_cache(p)
    assert list(loaded) == ["DOW"], "the non-dict entry must not survive the load"


def test_describe_survives_a_non_dict_cached_entry(monkeypatch):
    """And describe() guards it too, because the cache dict is a caller-supplied
    argument — the loader is not the only way a value gets in there."""
    monkeypatch.setattr(about, "fetch_summary",
                        lambda title, ua="x": {"desc": "tech company", "extract": "...",
                                               "title": "Apple Inc."})
    cache = {"AAPL": 5}
    got = about.describe("AAPL", "Apple", "Apple Inc.", cache)
    assert got["desc"] == "tech company"
    assert cache["AAPL"]["title"] == "Apple Inc.", "the junk entry is replaced, not read"


# --- save_cache is fail-soft, and refuses to clobber a cache it could not read ---

def test_save_cache_warns_instead_of_raising(tmp_path):
    """save_cache was the only I/O in the module with no degrade.warn wrapper, and
    run.py:113 calls it unguarded AFTER every enrichment and BEFORE the render. A full
    disk or an unwritable path therefore threw away a completed run at the last step.
    Both failure shapes are covered: the write itself (parent is a FILE, so the atomic
    writer's mkdir raises OSError) and the serialize (a value json cannot encode)."""
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file, not a directory")
    about.save_cache(blocker / "about.json", {"AAPL": {"name": "Apple"}})
    about.save_cache(tmp_path / "unserializable.json", {"AAPL": object()})
    assert [e["what"] for e in degrade.events()] == ["about cache write"] * 2


def test_a_corrupt_cache_is_not_overwritten_by_a_board_only_subset(tmp_path):
    """The silent data-loss path, and the reason load_cache cannot just return {}.

    run.py enriches only the ~15-30 tickers on TODAY's board into whatever dict
    load_cache handed it, then saves. So a failed read of a 3,000-entry cache does not
    degrade the run — it REPLACES the accumulated cache with today's board and commits
    that to the data branch. A file that exists and is non-empty but will not parse is
    damage, not an empty cache, and the only safe response is to leave it alone."""
    p = tmp_path / "about.json"
    blob = '{"schema": 1, "entries": {"AAPL": {"name": "App'      # truncated by a hand-edit
    p.write_text(blob)
    assert about.load_cache(p) == {}
    assert any("about cache" in e["what"] for e in degrade.events()), "and it says so"

    about.save_cache(p, {"IREN": {"name": "IREN", "desc": "Bitcoin miner", "extract": "",
                                  "title": "IREN Limited", "mapped": "IREN Limited"}})
    assert p.read_text() == blob, "a corrupt read must veto the rewrite, not lose 3,000 entries"


def test_a_missing_or_empty_cache_file_is_an_empty_cache_not_a_corrupt_one(tmp_path):
    """The other half of the distinction, and the one that keeps the system bootable: a
    first-ever run has no file at all, and a zero-length file is what an interrupted
    pre-atomic write left behind. Neither is damage — refusing to write for those would
    mean the cache could never be created in the first place."""
    missing = tmp_path / "about.json"
    assert about.load_cache(missing) == {}
    about.save_cache(missing, {"AAPL": {"name": "Apple", "desc": "tech company",
                                        "extract": "", "title": "Apple Inc."}})
    assert about.load_cache(missing)["AAPL"]["title"] == "Apple Inc."

    empty = tmp_path / "empty.json"
    empty.write_text("")
    assert about.load_cache(empty) == {}
    about.save_cache(empty, {"AAPL": {"name": "Apple", "desc": "tech company",
                                      "extract": "", "title": "Apple Inc."}})
    assert about.load_cache(empty)["AAPL"]["title"] == "Apple Inc."


def test_a_stale_schema_cache_is_still_discarded_and_still_rewritten(tmp_path):
    """The deliberate discard must NOT be mistaken for corruption. The pre-SCHEMA-1 file
    holds wrong-entity entries that are cache HITS, so they never re-fetch and never
    heal; throwing the whole file away and rebuilding it from the board is the intended
    outcome, and the corrupt-read veto must stay out of its way."""
    p = tmp_path / "about.json"
    p.write_text(json.dumps({"schema": 0, "entries": {"AAPL": {"name": "Apple",
                                                               "desc": "Edible fruit"}}}))
    assert about.load_cache(p) == {}
    about.save_cache(p, {"IREN": {"name": "IREN", "desc": "Bitcoin miner", "extract": "",
                                  "title": "IREN Limited", "mapped": "IREN Limited"}})
    reloaded = about.load_cache(p)
    assert list(reloaded) == ["IREN"], "the poisoned cache must be gone, replaced"
    assert reloaded["IREN"]["desc"] == "Bitcoin miner"


def test_a_bool_schema_is_not_schema_1(tmp_path):
    """`True == 1` in Python, so `doc.get("schema") != SCHEMA` accepted `"schema": true`
    and resurrected exactly the wrong-entity cache the schema check exists to discard.
    Compare types, not just values — and treat it as a stale schema (discard + rewrite),
    since a value that is not the current schema is by definition not readable by it."""
    p = tmp_path / "about.json"
    p.write_text(json.dumps({"schema": True, "entries": {"AAPL": {"name": "Apple",
                                                                  "desc": "Edible fruit",
                                                                  "title": "Apple"}}}))
    assert about.load_cache(p) == {}
    about.save_cache(p, {"IREN": {"name": "IREN", "desc": "Bitcoin miner", "extract": "",
                                  "title": "IREN Limited", "mapped": "IREN Limited"}})
    assert list(about.load_cache(p)) == ["IREN"]
