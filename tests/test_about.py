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
    about.save_cache(p, {"AAPL": {"name": "Apple", "desc": "tech company", "extract": ""}})
    assert about.load_cache(p)["AAPL"]["desc"] == "tech company"


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
