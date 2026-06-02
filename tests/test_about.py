from radar import about


def test_describe_uses_cache_without_network(monkeypatch):
    # cached ticker -> no fetch
    called = {"n": 0}
    monkeypatch.setattr(about, "fetch_summary", lambda *a, **k: called.__setitem__("n", called["n"] + 1))
    cache = {"HPE": {"name": "Hewlett Packard Enterprise", "desc": "IT company", "extract": "..."}}
    got = about.describe("HPE", "Hewlett Packard Enterprise", cache)
    assert got["desc"] == "IT company" and called["n"] == 0


def test_describe_fetches_and_caches_miss(monkeypatch):
    monkeypatch.setattr(about, "fetch_summary",
                        lambda name, ua="x": {"desc": "Space tourism company", "extract": "Virgin Galactic..."})
    cache = {}
    got = about.describe("SPCE", "Virgin Galactic", cache)
    assert got["name"] == "Virgin Galactic" and got["desc"] == "Space tourism company"
    assert cache["SPCE"]["extract"].startswith("Virgin Galactic")   # persisted to cache


def test_describe_graceful_when_lookup_fails(monkeypatch):
    monkeypatch.setattr(about, "fetch_summary", lambda *a, **k: None)
    got = about.describe("ZZZZ", "Nonexistent Co", {})
    assert got["name"] == "Nonexistent Co" and got["desc"] == "" and got["extract"] == ""


def test_load_cache_bad_file(tmp_path):
    p = tmp_path / "about.json"; p.write_text("not json")
    assert about.load_cache(p) == {}
