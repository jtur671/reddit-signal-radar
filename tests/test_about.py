import json

from radar import about

# Captured at import time, BEFORE conftest's autouse hermeticity fixture stubs
# about.fetch_summary out. The two canonical-title tests below need the real
# function body (with requests.get stubbed) to prove it reads the response field.
_REAL_FETCH_SUMMARY = about.fetch_summary


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
    assert entry == {"name": "MicroVision", "desc": "", "extract": "", "title": ""}


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
    `.github/workflows/daily.yml:26` restores `data/` from the orphan data branch BEFORE
    the pytest gate at `:35`. So without this guard the suite reads production cache
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
