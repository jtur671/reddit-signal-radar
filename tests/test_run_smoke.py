def test_dry_run_writes_dashboard(tmp_path, monkeypatch):
    import radar.run as run
    from radar.apewisdom import Aggregate
    monkeypatch.setattr(run, "fetch_mentions", lambda cfg: [
        Aggregate(ticker="IREN", name="Iris Energy", mentions=120,
                  mentions_24h_ago=40, upvotes=900, subreddit="all-stocks"),
        Aggregate(ticker="KEEL", name="Keel Infrastructure", mentions=80,
                  mentions_24h_ago=10, upvotes=400, subreddit="all-stocks"),
    ])
    monkeypatch.setattr(run.tradestie, "fetch_wsb", lambda cfg: [])  # stub live Tradestie
    monkeypatch.setattr(run, "fetch_short_ratios", lambda cfg, run_day: ({}, ""))
    monkeypatch.setattr(run, "option_stats", lambda ticker, cfg: None)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")    # skip LLM
    monkeypatch.setattr(run.news, "headlines", lambda *a, **k: [])  # stub live Google News
    code = run.main(["--dry-run", "--out", str(tmp_path / "out"), "--no-email"])
    assert code == 0
    html = (tmp_path / "out" / "index.html").read_text()
    assert "IREN" in html and "KEEL" in html      # populated board from aggregates


def test_dry_run_writes_signals_and_weights(tmp_path, monkeypatch):
    """F5 — a full offline run wires the composite pipeline end to end: data.json's
    `signals` array (one entry per board row, ticker/composite/components) and the raw
    `weights` config it was blended against (summing to ~1.0)."""
    import json
    import radar.run as run
    from radar.apewisdom import Aggregate
    monkeypatch.setattr(run, "fetch_mentions", lambda cfg: [
        Aggregate(ticker="IREN", name="Iris Energy", mentions=120,
                  mentions_24h_ago=40, upvotes=900, subreddit="all-stocks"),
        Aggregate(ticker="KEEL", name="Keel Infrastructure", mentions=80,
                  mentions_24h_ago=10, upvotes=400, subreddit="all-stocks"),
    ])
    monkeypatch.setattr(run.tradestie, "fetch_wsb", lambda cfg: [])  # no live network in tests
    monkeypatch.setattr(run, "fetch_short_ratios", lambda cfg, run_day: ({}, ""))
    monkeypatch.setattr(run, "fetch_cramer", lambda cfg, run_day: {})
    monkeypatch.setattr(run, "option_stats", lambda ticker, cfg: None)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")    # skip LLM
    monkeypatch.setattr(run.news, "headlines", lambda *a, **k: [])  # no live Google News in tests

    out = tmp_path / "out"
    code = run.main(["--dry-run", "--no-email", "--out", str(out)])
    assert code == 0
    data = json.loads((out / "data.json").read_text())

    assert isinstance(data["signals"], list) and len(data["signals"]) == len(data["board"])
    assert {row["ticker"] for row in data["signals"]} == {"IREN", "KEEL"}
    for row in data["signals"]:
        assert {"ticker", "composite", "components"} <= row.keys()
        assert isinstance(row["components"], dict)

    assert isinstance(data["weights"], dict) and data["weights"]
    assert abs(sum(data["weights"].values()) - 1.0) < 1e-6


def test_run_maps_titles_and_reports_the_source(monkeypatch, tmp_path):
    """The map reaches about.describe, and the source reports itself like every other.

    IREN is mapped, KEEL is not: the exact mapped title is what gets fetched, and the
    unmapped ticker makes NO request at all (the anti-fuzzy guarantee, end to end)."""
    import json
    import radar.run as run
    from radar.apewisdom import Aggregate
    monkeypatch.setattr(run, "fetch_mentions", lambda cfg: [
        Aggregate(ticker="IREN", name="Iris Energy", mentions=120,
                  mentions_24h_ago=40, upvotes=900, subreddit="all-stocks"),
        Aggregate(ticker="KEEL", name="Keel Infrastructure", mentions=80,
                  mentions_24h_ago=10, upvotes=400, subreddit="all-stocks"),
    ])
    monkeypatch.setattr(run.tradestie, "fetch_wsb", lambda cfg: [])  # no live network in tests
    monkeypatch.setattr(run, "fetch_short_ratios", lambda cfg, run_day: ({}, ""))
    monkeypatch.setattr(run, "fetch_cramer", lambda cfg, run_day: {})
    monkeypatch.setattr(run, "option_stats", lambda ticker, cfg: None)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")    # skip LLM
    monkeypatch.setattr(run.news, "headlines", lambda *a, **k: [])  # no live Google News in tests

    fetched = []
    # Realistic shape: fetch_ticker_map always merges the curated overrides over what it
    # resolved, so a stub returning a bare {"IREN": ...} would be a map BELOW the health
    # floor and would (correctly) light the LED red. Neither IREN nor KEEL is an override.
    mapped = dict(run.tickermap.load_overrides("radar/ticker_overrides.yml"))
    mapped["IREN"] = "IREN Limited"
    monkeypatch.setattr(run.tickermap, "fetch_ticker_map", lambda cfg, run_day, **k: mapped)
    monkeypatch.setattr(run.about, "fetch_summary",
                        lambda title, ua="x": fetched.append(title) or {
                            "desc": "d", "extract": "e", "title": title})

    out = tmp_path / "out"
    code = run.main(["--dry-run", "--no-email", "--out", str(out)])
    assert code == 0
    health = json.loads((out / "health.json").read_text())
    assert "tickermap" in health["sources"]
    assert health["sources"]["tickermap"] == "ok"
    assert fetched == ["IREN Limited"], "mapped title fetched; unmapped ticker not requested"


def test_run_reports_tickermap_down_when_the_map_is_empty(monkeypatch, tmp_path):
    """Fails soft and says so: an empty map still publishes a board, with a red LED."""
    import json
    import radar.run as run
    from radar.apewisdom import Aggregate
    monkeypatch.setattr(run, "fetch_mentions", lambda cfg: [
        Aggregate(ticker="IREN", name="Iris Energy", mentions=120,
                  mentions_24h_ago=40, upvotes=900, subreddit="all-stocks"),
    ])
    monkeypatch.setattr(run.tradestie, "fetch_wsb", lambda cfg: [])
    monkeypatch.setattr(run, "fetch_short_ratios", lambda cfg, run_day: ({}, ""))
    monkeypatch.setattr(run, "fetch_cramer", lambda cfg, run_day: {})
    monkeypatch.setattr(run, "option_stats", lambda ticker, cfg: None)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    monkeypatch.setattr(run.news, "headlines", lambda *a, **k: [])
    monkeypatch.setattr(run.tickermap, "fetch_ticker_map", lambda cfg, run_day, **k: {})

    out = tmp_path / "out"
    assert run.main(["--dry-run", "--no-email", "--out", str(out)]) == 0
    health = json.loads((out / "health.json").read_text())
    assert health["sources"]["tickermap"] == "down"
    assert "IREN" in (out / "index.html").read_text()      # board still publishes


def test_tickermap_led_is_down_when_only_the_overrides_survive(monkeypatch, tmp_path):
    """The LED must reflect what WIKIDATA produced, not the size of the merged dict.

    `fetch_ticker_map` unconditionally merges the ~30 curated overrides over whatever it
    resolved, so it NEVER returns {} -- a truthiness check on the merged map is a health
    LED that can only ever say "ok", which is worse than no LED because it actively
    asserts health during a total outage. A map no larger than the override file means
    the live query and the vendored snapshot both produced nothing."""
    import json
    import radar.run as run
    from radar.apewisdom import Aggregate
    monkeypatch.setattr(run, "fetch_mentions", lambda cfg: [
        Aggregate(ticker="IREN", name="Iris Energy", mentions=120,
                  mentions_24h_ago=40, upvotes=900, subreddit="all-stocks"),
    ])
    monkeypatch.setattr(run.tradestie, "fetch_wsb", lambda cfg: [])
    monkeypatch.setattr(run, "fetch_short_ratios", lambda cfg, run_day: ({}, ""))
    monkeypatch.setattr(run, "fetch_cramer", lambda cfg, run_day: {})
    monkeypatch.setattr(run, "option_stats", lambda ticker, cfg: None)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    monkeypatch.setattr(run.news, "headlines", lambda *a, **k: [])

    only_overrides = run.tickermap.load_overrides("radar/ticker_overrides.yml")
    assert only_overrides, "the curated override file must be readable for this test to mean anything"
    monkeypatch.setattr(run.tickermap, "fetch_ticker_map", lambda cfg, run_day, **k: dict(only_overrides))

    out = tmp_path / "out"
    assert run.main(["--dry-run", "--no-email", "--out", str(out)]) == 0
    health = json.loads((out / "health.json").read_text())
    assert health["sources"]["tickermap"] == "down", \
        "overrides-only is a dead map, not a healthy one"


def test_tickermap_led_is_ok_when_wikidata_adds_anything(monkeypatch, tmp_path):
    """The other side of the floor: one resolution beyond the overrides is life."""
    import json
    import radar.run as run
    from radar.apewisdom import Aggregate
    monkeypatch.setattr(run, "fetch_mentions", lambda cfg: [
        Aggregate(ticker="IREN", name="Iris Energy", mentions=120,
                  mentions_24h_ago=40, upvotes=900, subreddit="all-stocks"),
    ])
    monkeypatch.setattr(run.tradestie, "fetch_wsb", lambda cfg: [])
    monkeypatch.setattr(run, "fetch_short_ratios", lambda cfg, run_day: ({}, ""))
    monkeypatch.setattr(run, "fetch_cramer", lambda cfg, run_day: {})
    monkeypatch.setattr(run, "option_stats", lambda ticker, cfg: None)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    monkeypatch.setattr(run.news, "headlines", lambda *a, **k: [])

    merged = dict(run.tickermap.load_overrides("radar/ticker_overrides.yml"))
    # Without this the test passes vacuously: an empty override file would make the floor
    # 0, and 1 > 0 reads "ok" for entirely the wrong reason — a green test asserting that
    # the floor works when in fact there is no floor.
    assert len(merged) > 1, "the curated override file must be readable and non-trivial"
    assert "IREN" not in merged, "IREN must be a Wikidata resolution, not an override"
    merged["IREN"] = "IREN Limited"        # one thing Wikidata resolved
    monkeypatch.setattr(run.tickermap, "fetch_ticker_map", lambda cfg, run_day, **k: merged)

    out = tmp_path / "out"
    assert run.main(["--dry-run", "--no-email", "--out", str(out)]) == 0
    health = json.loads((out / "health.json").read_text())
    assert health["sources"]["tickermap"] == "ok"


def test_footer_leds_render_the_tickermap_source(monkeypatch, tmp_path):
    """Task 5 Step 7, verified by rendering rather than assumed: the dashboard's data-
    sources footer is a generic `for name, st in sources.items()` loop, so a new source
    gets its LED with no template change. This test is what proves that claim."""
    import radar.run as run
    from radar.apewisdom import Aggregate
    monkeypatch.setattr(run, "fetch_mentions", lambda cfg: [
        Aggregate(ticker="IREN", name="Iris Energy", mentions=120,
                  mentions_24h_ago=40, upvotes=900, subreddit="all-stocks"),
    ])
    monkeypatch.setattr(run.tradestie, "fetch_wsb", lambda cfg: [])
    monkeypatch.setattr(run, "fetch_short_ratios", lambda cfg, run_day: ({}, ""))
    monkeypatch.setattr(run, "fetch_cramer", lambda cfg, run_day: {})
    monkeypatch.setattr(run, "option_stats", lambda ticker, cfg: None)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    monkeypatch.setattr(run.news, "headlines", lambda *a, **k: [])
    monkeypatch.setattr(run.tickermap, "fetch_ticker_map", lambda cfg, run_day, **k: {})

    out = tmp_path / "out"
    assert run.main(["--dry-run", "--no-email", "--out", str(out)]) == 0
    html = (out / "index.html").read_text()
    assert "tickermap" in html and "tickermap · down" in html


# --- E2: pageviews attention + FINRA short interest -------------------------------

def _offline(monkeypatch, run, aggregates):
    """The public fetches a smoke test must replace. conftest's autouse guard shuts the
    private transports; this shuts the sources whose absence would otherwise change the
    board itself."""
    monkeypatch.setattr(run, "fetch_mentions", lambda cfg: aggregates)
    monkeypatch.setattr(run.tradestie, "fetch_wsb", lambda cfg: [])
    monkeypatch.setattr(run, "fetch_short_ratios", lambda cfg, run_day: ({}, ""))
    monkeypatch.setattr(run, "fetch_cramer", lambda cfg, run_day: {})
    monkeypatch.setattr(run, "option_stats", lambda ticker, cfg: None)
    monkeypatch.setattr(run.news, "headlines", lambda *a, **k: [])
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")


def _board(run):
    from radar.apewisdom import Aggregate
    return [Aggregate(ticker="IREN", name="Iris Energy", mentions=120,
                      mentions_24h_ago=40, upvotes=900, subreddit="all-stocks"),
            Aggregate(ticker="KEEL", name="Keel Infrastructure", mentions=80,
                      mentions_24h_ago=10, upvotes=400, subreddit="all-stocks")]


def test_attention_ships_in_components_and_weights_stay_seven(monkeypatch, tmp_path):
    """attention is PUBLISHED and UNWEIGHTED, and that combination is the whole design:
    the consuming bot gets the number, while blend()'s `weights.get(k, 0) > 0` filter
    keeps it out of the composite so the score stays bit-for-bit comparable with every
    day of backtest history before it. This test asserts both halves at the run level,
    where a config edit would actually land."""
    import json
    import radar.run as run
    _offline(monkeypatch, run, _board(run))
    monkeypatch.setattr(run.pageviews, "fetch_attention",
                        lambda titles, tickers, run_day, **k: ({"IREN": 88.0},
                                                                {"IREN": 5000}, 0))

    out = tmp_path / "out"
    assert run.main(["--dry-run", "--no-email", "--out", str(out)]) == 0
    data = json.loads((out / "data.json").read_text())
    row = next(s for s in data["signals"] if s["ticker"] == "IREN")
    assert row["components"]["attention"] == 88.0
    assert row["pageviews"] == 5000
    assert "attention" not in data["weights"]
    assert abs(sum(data["weights"].values()) - 1.0) < 1e-6


def test_attention_does_not_move_the_composite(monkeypatch, tmp_path):
    """The invariant the unweighted design exists to protect, measured end to end: the
    same run with and without a maxed-out attention score must publish the SAME
    composite. If someone adds `attention: 0.10` to config.yaml, this fails."""
    import json
    import radar.run as run

    def composites(attention):
        _offline(monkeypatch, run, _board(run))
        monkeypatch.setattr(run.pageviews, "fetch_attention",
                            lambda titles, tickers, run_day, **k: (attention, {}, 0))
        out = tmp_path / ("out" + str(len(attention)))
        assert run.main(["--dry-run", "--no-email", "--out", str(out)]) == 0
        data = json.loads((out / "data.json").read_text())
        return {s["ticker"]: s["composite"] for s in data["signals"]}

    assert composites({"IREN": 100.0, "KEEL": 0.0}) == composites({})


def test_pageviews_uses_the_canonical_title_not_the_mapped_one(monkeypatch, tmp_path):
    """MEASURED requirement, not a preference. The pageviews API does NOT follow
    redirects: it answers HTTP 200 with the REDIRECT page's own traffic. Measured,
    `Dow Inc.` yields 12 views/day against canonical `Dow Chemical Company`'s 468 — a
    39x silent understatement, no error, nothing downstream able to tell. Wikidata's
    sitelinks do include redirect titles, so the mapped title is not safe to send.

    about.py's REST summary call DOES follow redirects and caches the canonical title,
    on a request the run already makes. That cached title must win."""
    import radar.run as run
    _offline(monkeypatch, run, _board(run))
    monkeypatch.setattr(run.about, "load_cache", lambda path: {})
    monkeypatch.setattr(run.tickermap, "fetch_ticker_map",
                        lambda cfg, run_day, **k: {"IREN": "Iris Energy",   # a REDIRECT title
                                               "KEEL": "Keel Infrastructure"})
    # The summary endpoint resolves IREN's redirect; KEEL's article answers under the
    # title we asked for, so its canonical and mapped titles are the same string.
    canonical = {"Iris Energy": "IREN Limited"}
    monkeypatch.setattr(run.about, "fetch_summary",
                        lambda title, ua="x": {"desc": "d", "extract": "e",
                                                "title": canonical.get(title, title)})
    seen = {}
    monkeypatch.setattr(run.pageviews, "fetch_attention",
                        lambda titles, tickers, run_day, **k: (seen.update(titles), ({}, {}, 0))[1])

    out = tmp_path / "out"
    assert run.main(["--dry-run", "--no-email", "--out", str(out)]) == 0
    assert seen["IREN"] == "IREN Limited", "the canonical title must beat the mapped one"
    assert seen["KEEL"] == "Keel Infrastructure"


def test_pageviews_falls_back_to_the_mapped_title_when_about_has_none(monkeypatch, tmp_path):
    """The other half of the preference: a cached entry with no canonical title (the
    summary call failed, or the ticker was never described) must not blank the request
    out — the mapped title is still the best exact title available."""
    import radar.run as run
    _offline(monkeypatch, run, _board(run))
    monkeypatch.setattr(run.about, "load_cache", lambda path: {})
    monkeypatch.setattr(run.tickermap, "fetch_ticker_map",
                        lambda cfg, run_day, **k: {"IREN": "IREN Limited"})
    monkeypatch.setattr(run.about, "fetch_summary", lambda *a, **k: None)   # empty title
    seen = {}
    monkeypatch.setattr(run.pageviews, "fetch_attention",
                        lambda titles, tickers, run_day, **k: (seen.update(titles), ({}, {}, 0))[1])

    out = tmp_path / "out"
    assert run.main(["--dry-run", "--no-email", "--out", str(out)]) == 0
    assert seen["IREN"] == "IREN Limited"
    assert "KEEL" not in seen, "an unmapped, undescribed ticker sends no title at all"


def test_short_interest_never_ships_without_its_settlement_date(monkeypatch, tmp_path):
    """Short interest is 11-24 days stale by nature (measured 2026-08-17: the latest
    available settlement was 2026-07-31) and it ships beside short_ratio, which is
    genuinely D-1. A bare days-to-cover number on a daily board implies a freshness it
    does not have, so `as_of` travels with it through every surface."""
    import json
    import radar.run as run
    _offline(monkeypatch, run, _board(run))
    monkeypatch.setattr(run.short_interest, "fetch_short_interest",
                        lambda cfg, run_day, **k: ({"IREN": {"days_to_cover": 6.7,
                                                         "shares": 12_000_000}},
                                               "2026-07-31"))

    out = tmp_path / "out"
    assert run.main(["--dry-run", "--no-email", "--out", str(out)]) == 0
    data = json.loads((out / "data.json").read_text())
    row = next(s for s in data["signals"] if s["ticker"] == "IREN")
    assert row["days_to_cover"] == 6.7
    assert row["short_interest_as_of"] == "2026-07-31"
    assert "attention" not in data["weights"]        # and it is still not a component
    assert "days_to_cover" not in row["components"], "short interest is context, never a component"

    html = (out / "index.html").read_text()
    # Weak by construction, and labelled as such: the date is in the page because the
    # detail blob is embedded as JSON, so this cannot tell whether the modal RENDERS it
    # beside the number. test_the_modal_cannot_render_days_to_cover_without_its_as_of is
    # the guard that actually checks that; this only pins that the field ships at all.
    assert "2026-07-31" in html, "the settlement date reaches the page payload"


def test_a_dateless_settlement_suppresses_days_to_cover_entirely(monkeypatch, tmp_path):
    """`as_of` is non-negotiable, so it is enforced where the value is SET, not only
    where it is rendered: rows with no settlement date (a malformed vendored snapshot
    is the realistic path) ship no days-to-cover at all rather than an undated one."""
    import json
    import radar.run as run
    _offline(monkeypatch, run, _board(run))
    monkeypatch.setattr(run.short_interest, "fetch_short_interest",
                        lambda cfg, run_day, **k: ({"IREN": {"days_to_cover": 6.7,
                                                         "shares": 12_000_000}}, ""))

    out = tmp_path / "out"
    assert run.main(["--dry-run", "--no-email", "--out", str(out)]) == 0
    data = json.loads((out / "data.json").read_text())
    row = next(s for s in data["signals"] if s["ticker"] == "IREN")
    assert row["days_to_cover"] is None
    assert row["short_interest_as_of"] is None


def test_the_modal_cannot_render_days_to_cover_without_its_as_of():
    """A source-level guard on the one surface a payload test cannot reach: the detail
    modal builds its metrics in JavaScript, so an edit that drops the settlement date
    from that line would leave every payload assertion above green. Every mention of
    days_to_cover in the template must sit on a line that also carries the date."""
    from pathlib import Path
    tpl = Path("radar/templates/dashboard.html.j2").read_text()
    lines = [ln for ln in tpl.splitlines() if "days_to_cover" in ln]
    assert lines, "the detail modal must render days to cover somewhere"
    for ln in lines:
        assert "short_interest_as_of" in ln, f"undated days-to-cover: {ln.strip()}"


def test_finra_si_goes_red_and_wikimedia_reads_unused_on_a_dead_run(monkeypatch, tmp_path):
    """The LED trap, guarded: `"ok" if X else "down"` is only honest when X can actually
    be empty on failure. FINRA here is genuinely dead — no upstream (the transport guard)
    and no vendored snapshot (absent in a test checkout) — so red is reachable, which is
    exactly what the tickermap LED could not do before it was fixed.

    Wikimedia in this same run is NOT dead, and the original version of this test claimed
    it was: with tickermap serving overrides only, neither board ticker has a title, so
    `_get_series` is called ZERO times (measured — asserted below, not assumed). Nothing
    was asked, so nothing failed, and the honest reading is "unused". The two states are
    pinned separately by the two tests above this one."""
    import json
    import radar.run as run
    _offline(monkeypatch, run, _board(run))
    calls = []
    real = run.pageviews._get_series
    monkeypatch.setattr(run.pageviews, "_get_series",
                        lambda *a, **k: calls.append(a) or real(*a, **k))

    out = tmp_path / "out"
    assert run.main(["--dry-run", "--no-email", "--out", str(out)]) == 0
    health = json.loads((out / "health.json").read_text())
    assert calls == [], "no mapped titles, so Wikimedia was never asked anything"
    assert health["sources"]["wikimedia"] == "unused"
    assert health["sources"]["finra_si"] == "down"
    html = (out / "index.html").read_text()
    assert "wikimedia · unused" in html and "finra_si · down" in html  # generic footer loop
    assert "IREN" in html                                             # and the board still ships


def test_new_sources_report_ok_when_they_answer(monkeypatch, tmp_path):
    """The green side of both LEDs. wikimedia keys off RAW VIEWS, not scores: a healthy
    Wikimedia whose tickers all fail spike_score's 21-day/10-view baseline floor has
    answered every request, and lighting that red would be a false alarm about a source
    that is up.

    Titles are mapped rather than left empty, because without them this test asserted
    green against a state production cannot reach: fetch_attention returning raw views
    for tickers it was never given a title for. It passed only because the old LED
    checked `raw_views` before `pv_titles`, so an impossible input masked the ordering
    bug that let a partial outage read green (see the degraded test below)."""
    import json
    import radar.run as run
    _offline(monkeypatch, run, _board(run))
    _mapped_board(monkeypatch, run)
    monkeypatch.setattr(run.pageviews, "fetch_attention",
                        lambda titles, tickers, run_day, **k: ({}, {"IREN": 5000}, 0))
    monkeypatch.setattr(run.short_interest, "fetch_short_interest",
                        lambda cfg, run_day, **k: ({"IREN": {"days_to_cover": 6.7,
                                                         "shares": 12_000_000}},
                                               "2026-07-31"))

    out = tmp_path / "out"
    assert run.main(["--dry-run", "--no-email", "--out", str(out)]) == 0
    health = json.loads((out / "health.json").read_text())
    assert health["sources"]["wikimedia"] == "ok"
    assert health["sources"]["finra_si"] == "ok"


def test_a_ticker_finra_never_reported_gets_no_settlement_date_either(monkeypatch, tmp_path):
    """The pairing runs in BOTH directions. Stamping the run's settlement date onto a
    ticker with no row implies a short-interest measurement that does not exist — the
    date is only meaningful as an age for a NUMBER. Caught in a rendered dry run: KEEL
    is off FINRA's list, IREN is on it."""
    import json
    import radar.run as run
    _offline(monkeypatch, run, _board(run))
    monkeypatch.setattr(run.short_interest, "fetch_short_interest",
                        lambda cfg, run_day, **k: ({"IREN": {"days_to_cover": 6.7,
                                                         "shares": 12_000_000}},
                                               "2026-07-31"))

    out = tmp_path / "out"
    assert run.main(["--dry-run", "--no-email", "--out", str(out)]) == 0
    rows = {s["ticker"]: s for s in json.loads((out / "data.json").read_text())["signals"]}
    assert rows["IREN"]["short_interest_as_of"] == "2026-07-31"
    assert rows["KEEL"]["days_to_cover"] is None
    assert rows["KEEL"]["short_interest_as_of"] is None, "a date with no number is a claim of data"
    assert rows["KEEL"]["short_interest_shares"] is None


def _pipeline_workflows():
    """Every workflow that invokes the pipeline, DISCOVERED rather than listed.

    Naming the files is how fleet-monitor.yml was missed for the whole of E2: the
    original invariant read daily.yml and only daily.yml, while TWO workflows run
    `python -m radar.run`. A third would have slipped through the same gap, so the
    check finds its own subjects and asserts it found the ones we know about."""
    from pathlib import Path
    wfs = sorted(p for p in Path(".github/workflows").iterdir()
                 if p.suffix in (".yml", ".yaml") and "python -m radar.run" in p.read_text())
    assert {p.name for p in wfs} >= {"daily.yml", "fleet-monitor.yml"}, \
        f"the pipeline runners moved or were renamed: found {[p.name for p in wfs]}"
    return wfs


def test_every_vendored_snapshot_survives_every_workflow_that_runs_the_pipeline():
    """The data-branch copy list is a WHITELIST, so a snapshot missing from it is
    silently regenerated from scratch — the vendoring design is dead on arrival and its
    documented outage fallback can never fire, because there is never a cached file to
    fall back TO.

    Every `snapshot_path` in config.yaml is a declaration that a file must survive the
    run, which makes this checkable rather than reviewable: short_interest.json was
    missing when this test was written, ticker_articles.json was missing one commit
    before that, and fleet-monitor.yml was missing BOTH — because the check only ever
    read daily.yml while two workflows run the pipeline. Three misses is a pattern."""
    import re
    from pathlib import Path
    paths = re.findall(r"^\s*snapshot_path:\s*[\"']?(\S+?)[\"']?\s*$",
                       Path("config.yaml").read_text(), re.M)
    assert len(paths) >= 3, f"expected every vendoring source to declare one, got {paths}"
    for wf in _pipeline_workflows():
        copy_line = next(ln for ln in wf.read_text().splitlines()
                         if "/tmp/state/data/" in ln)
        for p in paths:
            assert p in copy_line, f"{p} is not in {wf.name}'s data-branch copy list"


def test_every_workflow_that_runs_the_pipeline_declares_a_timeout():
    """GitHub's default is 360 minutes. Both of these jobs hold the `pages` concurrency
    group (cancel-in-progress: false) that daily-radar's publish must acquire, and
    daily.yml's own timeout comment explicitly leans on that wait being SHORT — so an
    undeclared timeout on either one is six hours of a hung transport blocking the
    6:17 AM board, not just a slow job."""
    import re
    for wf in _pipeline_workflows():
        text = wf.read_text()
        m = re.search(r"^\s*timeout-minutes:\s*(\d+)\s*$", text, re.M)
        assert m, f"{wf.name} inherits GitHub's 360-minute default"
        assert int(m.group(1)) <= 45, f"{wf.name}: timeout-minutes {m.group(1)} is not a backstop"
        assert "concurrency:" in text and "group: pages" in text, \
            f"{wf.name} no longer shares the pages group — re-derive the number above"


def test_wikimedia_led_is_unused_when_nothing_was_asked(monkeypatch, tmp_path):
    """A red LED must mean Wikimedia FAILED, not that we never called it. With no titles —
    tickermap down and a cold about cache, which is a real Tuesday — fetch_attention makes
    ZERO requests, and a red LED there asserts an outage that did not happen. Same third
    state as the cboe LED one line above it in run.py."""
    import json
    import radar.run as run
    _offline(monkeypatch, run, _board(run))
    monkeypatch.setattr(run.tickermap, "fetch_ticker_map", lambda cfg, run_day, **k: {})
    calls = []
    real = run.pageviews._get_series
    monkeypatch.setattr(run.pageviews, "_get_series",
                        lambda *a, **k: calls.append(a) or real(*a, **k))

    out = tmp_path / "out"
    assert run.main(["--dry-run", "--no-email", "--out", str(out)]) == 0
    assert calls == [], "no titles means no requests — nothing was asked of Wikimedia"
    health = json.loads((out / "health.json").read_text())
    assert health["sources"]["wikimedia"] == "unused"


def test_wikimedia_led_is_down_when_a_title_was_asked_and_the_transport_failed(monkeypatch,
                                                                               tmp_path):
    """The other side, and the one no test covered: a title IS present, fetch_attention
    really runs, `_get_series` really fails (conftest's transport guard raises the same
    RequestException a Wikimedia outage would), and the LED goes red. This exercises the
    whole chain — titles -> fetch_attention -> raw_views -> LED — rather than asserting
    on a stubbed-out fetch_attention."""
    import json
    import radar.run as run
    _offline(monkeypatch, run, _board(run))
    mapped = dict(run.tickermap.load_overrides("radar/ticker_overrides.yml"))
    mapped["IREN"] = "IREN Limited"
    monkeypatch.setattr(run.tickermap, "fetch_ticker_map", lambda cfg, run_day, **k: mapped)
    calls = []
    real = run.pageviews._get_series
    monkeypatch.setattr(run.pageviews, "_get_series",
                        lambda *a, **k: calls.append(a) or real(*a, **k))

    out = tmp_path / "out"
    assert run.main(["--dry-run", "--no-email", "--out", str(out)]) == 0
    assert calls, "a mapped title must actually be requested"
    assert all(c[0] == "IREN Limited" for c in calls)
    health = json.loads((out / "health.json").read_text())
    assert health["sources"]["wikimedia"] == "down", "asked and got nothing back IS an outage"


def test_still_running_names_get_attention_too(monkeypatch, tmp_path):
    """The E2 spec costs this ingest as "~15-20 requests per run (board plus Still
    Running)" (non-social-attention-design 2.4); run.py only ever asked about the board.

    Still Running names are off the top-N board precisely because Reddit attention has
    moved on, which makes "is the wider world still looking this name up?" the single
    most informative thing left to ask about them. The detail modal already renders
    `wiki views` for every row it is given — and `_detail_blob` is fed `board + still` —
    so before this the lane rendered a permanent blank.

    Both lanes are forced here rather than grown: the real Still Running lane needs
    breakout history a smoke test does not have, and the two lanes must be DISJOINT
    (still_running.py skips anything already on the board) or the walk asks twice."""
    import json
    import re
    import radar.run as run
    _offline(monkeypatch, run, _board(run))
    monkeypatch.setattr(run, "top_signals",
                        lambda signals, n: [s for s in signals if s.ticker == "IREN"])
    monkeypatch.setattr(run, "still_running",
                        lambda signals, history, run_day, board, cfg: [
                            s for s in signals if s.ticker == "KEEL"])
    mapped = dict(run.tickermap.load_overrides("radar/ticker_overrides.yml"))
    mapped.update({"IREN": "IREN Limited", "KEEL": "Keel Infrastructure"})
    monkeypatch.setattr(run.tickermap, "fetch_ticker_map", lambda cfg, run_day, **k: mapped)

    seen = {}

    def fake_fetch(titles, tickers, run_day, **k):
        seen["titles"] = dict(titles)
        seen["tickers"] = list(tickers)
        return ({t: 70.0 for t in tickers}, {t: 4321 for t in tickers}, 0)

    monkeypatch.setattr(run.pageviews, "fetch_attention", fake_fetch)

    out = tmp_path / "out"
    assert run.main(["--dry-run", "--no-email", "--out", str(out)]) == 0
    assert seen["tickers"] == ["IREN", "KEEL"], "the Still Running lane was never asked"
    assert seen["titles"]["KEEL"] == "Keel Infrastructure"

    html = (out / "index.html").read_text()
    blob = json.loads(re.search(r'id="radar-data">(.*?)</script>', html, re.S).group(1))
    assert blob["KEEL"]["pageviews"] == 4321, \
        "the fields are populated for a Still Running row exactly as for a board row"
    assert blob["IREN"]["pageviews"] == 4321


def test_wikimedia_led_is_not_down_when_every_mapped_title_404s(monkeypatch, tmp_path):
    """The third world the LED used to collapse into "down": every mapped title answers,
    and every answer is "no such article". That is a HEALTHY Wikimedia — a 404 is an
    answer — and the same shape covers the more dangerous case, a board-wide stale tail
    when Wikimedia has not published D-1 by the 10:17 UTC board time (availability there
    is INFERRED from dump timestamps, never observed — docs/HANDOFF.md). Under the old
    `"ok" if raw_views` rule the whole board reported an outage that never happened.

    Driven through the real transport so the chain runs end to end: titles ->
    fetch_attention -> transport failure count -> LED."""
    import json
    import radar.run as run
    _offline(monkeypatch, run, _board(run))
    mapped = dict(run.tickermap.load_overrides("radar/ticker_overrides.yml"))
    mapped.update({"IREN": "IREN Limited", "KEEL": "Keel Infrastructure"})
    monkeypatch.setattr(run.tickermap, "fetch_ticker_map", lambda cfg, run_day, **k: mapped)

    calls = []

    class Resp:
        status_code = 404

        def json(self):
            return {}

    def fake_get(url, headers=None, timeout=None):
        calls.append(url)
        return Resp()

    monkeypatch.setattr(run.pageviews.requests, "get", fake_get)

    out = tmp_path / "out"
    assert run.main(["--dry-run", "--no-email", "--out", str(out)]) == 0
    assert calls, "mapped titles must actually be requested"
    health = json.loads((out / "health.json").read_text())
    assert health["sources"]["wikimedia"] != "down", \
        "every article 404ing is our mapping's problem, not a Wikimedia outage"
    assert health["sources"]["wikimedia"] == "ok"


def test_the_dna_strip_and_the_modal_bars_stay_in_sync():
    """run.py's _COMP_ORDER and the template's `CO` array are a hand-maintained mirror
    with no drift guard: the table strip renders from one and the modal bars from the
    other, so a component added or removed on one side alone shows different signals on
    two surfaces of the same page and nothing goes red. Verified by deletion — dropping
    `attention` from BOTH left the entire suite passing before this test existed.

    The third assertion catches the reverse drift: a component added to composite.py
    that neither surface renders at all."""
    import re
    from pathlib import Path
    import radar.run as run
    from radar.composite import components_for
    from radar.models import Signal

    tpl = Path("radar/templates/dashboard.html.j2").read_text()
    block = re.search(r"var CO=\[(.*?)\];", tpl, re.S)
    assert block, "the modal's component array must be findable"
    pairs = [list(p) for p in re.findall(r"\['([a-z_]+)'\s*,\s*'([^']+)'\]", block.group(1))]
    assert pairs == [list(p) for p in run._COMP_ORDER], "strip and modal bars have drifted"
    assert ["attention", "attn"] in pairs, "attention is published, so it renders"

    emitted = set(components_for(Signal(ticker="X"), [Signal(ticker="X")], None, {}))
    assert emitted == {k for k, _ in run._COMP_ORDER}, \
        "every component the composite emits must have a cell on both surfaces"


def test_dry_run_writes_no_vendored_snapshot(monkeypatch, tmp_path):
    """--dry-run must not mutate repo state. Every other vendoring source is gated
    (fetch_cramer, history.save, about.save_cache, append_picks); short interest and the
    ticker map were not, so debugging a run locally rewrote files the daily job owns.
    The FETCH still runs — only the write is suppressed — so --dry-run keeps exercising
    the full path."""
    import radar.run as run
    _offline(monkeypatch, run, _board(run))
    snaps = {"si": tmp_path / "si.json", "tm": tmp_path / "tm.json"}
    cfg_real = run.load_config

    def cfg_patched(path):
        cfg = cfg_real(path)
        cfg.short_interest.snapshot_path = str(snaps["si"])
        cfg.tickermap.snapshot_path = str(snaps["tm"])
        return cfg
    monkeypatch.setattr(run, "load_config", cfg_patched)
    # Both upstreams must ANSWER, or the test is vacuous: each module only writes on a
    # successful fetch, so a stubbed-out transport reaches a fallback path that was never
    # going to write anything. Verified by mutation — with the gate removed both files
    # appear, and this test goes red for both.
    monkeypatch.setattr(run.short_interest, "_latest_settlement", lambda ua: "2026-07-31")
    monkeypatch.setattr(run.short_interest, "_post_json",
                        lambda url, payload, ua, **k: ([{"symbolCode": "IREN",
                                                          "daysToCoverQuantity": 6.7,
                                                          "currentShortPositionQuantity": 12,
                                                          "settlementDate": "2026-07-31"}], 1))
    # A healthy WDQS answer: MIN_ROWS (1000) rows and a COUNT that agrees with them.
    rows = [{"ticker": {"value": f"T{i}"}, "enwiki": {"value": f"Title {i}"},
             "rank": {"value": "http://wikiba.se/ontology#NormalRank"}}
            for i in range(run.tickermap.MIN_ROWS)]
    monkeypatch.setattr(run.tickermap, "_get_json",
                        lambda q, ua, **kw: ({"results": {"bindings": [
                            {"n": {"value": str(len(rows))}}]}} if "COUNT" in q
                            else {"results": {"bindings": rows}}))

    out = tmp_path / "out"
    assert run.main(["--dry-run", "--no-email", "--out", str(out)]) == 0
    assert not snaps["si"].exists(), "--dry-run wrote the short-interest snapshot"
    assert not snaps["tm"].exists(), "--dry-run wrote the ticker-map snapshot"


def test_a_dateless_snapshot_cannot_light_the_finra_led_green(monkeypatch, tmp_path):
    """The LED trap once more, through the vendored snapshot instead of the live pull.

    A snapshot with rows but no `settlement` (partial write, hand-edit — it rides the
    data branch) used to be served as if it were data. `si_rows` came back non-empty, so
    `"ok" if si_rows else "down"` read green, while run.py's board loop is gated on
    `if si_as_of` and therefore shipped not one days-to-cover. Both halves are asserted
    here, because only the pair makes the point: the LED claimed a healthy source on a
    run that published nothing from it."""
    import json
    import radar.run as run
    _offline(monkeypatch, run, _board(run))
    snap = tmp_path / "si.json"     # NOT under a state dir, so conftest's guard lets it be read
    snap.write_text(json.dumps({"schema": 1, "rows": {"IREN": {"days_to_cover": 6.7,
                                                               "shares": 12_000_000}}}))
    cfg_real = run.load_config

    def cfg_patched(path):
        cfg = cfg_real(path)
        cfg.short_interest.snapshot_path = str(snap)
        return cfg
    monkeypatch.setattr(run, "load_config", cfg_patched)

    out = tmp_path / "out"
    assert run.main(["--dry-run", "--no-email", "--out", str(out)]) == 0
    rows = {s["ticker"]: s for s in json.loads((out / "data.json").read_text())["signals"]}
    health = json.loads((out / "health.json").read_text())
    assert rows["IREN"]["days_to_cover"] is None, "no settlement date, so no number ships"
    assert health["sources"]["finra_si"] == "down", "and the LED must report that, not ok"
    assert "finra_si · down" in (out / "index.html").read_text()


# --- wikimedia LED: the partial outage --------------------------------------

def _pv_body(url, views=1234):
    """A well-formed pageviews body whose TAIL is the end day the URL asked for.

    Built from the URL rather than hardcoded because `end` is run_day - 1 and run_day
    comes from a real clock — a fixed date would make `_get_series` return MISS (its
    stale-tail refusal) and the test would assert nothing about a healthy answer."""
    import re
    from datetime import date, timedelta
    start, end = re.search(r"/daily/(\d{8})/(\d{8})$", url).groups()
    d0 = date(int(start[:4]), int(start[4:6]), int(start[6:]))
    d1 = date(int(end[:4]), int(end[4:6]), int(end[6:]))
    return {"items": [{"timestamp": (d0 + timedelta(days=i)).strftime("%Y%m%d") + "00",
                       "views": views}
                      for i in range((d1 - d0).days + 1)]}


class _PartialWikimedia:
    """Wikimedia up for some titles and transport-dead for the rest — the shape of a
    real partial outage (one edge cache, one datacentre, one rate-limited window)."""

    RequestException = __import__("requests").RequestException

    def __init__(self, ok_titles):
        import urllib.parse
        self.ok = [urllib.parse.quote(t.replace(" ", "_"), safe="") for t in ok_titles]
        self.asked = []

    def get(self, url, headers=None, timeout=None):
        self.asked.append(url)
        if any(t in url for t in self.ok):
            body = _pv_body(url)
            return type("R", (), {"status_code": 200, "json": lambda s: body})()
        raise self.RequestException("partial Wikimedia outage")


def _mapped_board(monkeypatch, run):
    mapped = dict(run.tickermap.load_overrides("radar/ticker_overrides.yml"))
    mapped.update({"IREN": "IREN Limited", "KEEL": "Keel Infrastructure"})
    monkeypatch.setattr(run.tickermap, "fetch_ticker_map", lambda cfg, run_day, **k: mapped)


def test_wikimedia_led_is_degraded_when_only_some_titles_answer(monkeypatch, tmp_path):
    """The LED that could not tell the truth, third instance on this branch.

    `"ok" if raw_views` was checked BEFORE the transport-failure count, so a genuine
    partial outage — measured: 12 tickers, 2 answer, 3 consecutive transport failures
    trip the breaker, 10 tickers get nothing — lit GREEN. The two degrade warns landed
    in health["problems"], so it was discoverable; the glanceable surface lied.

    Transport failures now WIN over partial success, and a partial outage is not
    binary: some names really do have attention data, so "down" would be as wrong as
    "ok". Three states, keyed only on things Wikimedia itself controls."""
    import json
    import radar.run as run
    _offline(monkeypatch, run, _board(run))
    _mapped_board(monkeypatch, run)
    fake = _PartialWikimedia(["IREN Limited"])           # KEEL's transport dies
    monkeypatch.setattr(run.pageviews, "requests", fake)

    out = tmp_path / "out"
    assert run.main(["--dry-run", "--no-email", "--out", str(out)]) == 0
    assert fake.asked, "both titles must actually be requested"
    data = json.loads((out / "data.json").read_text())
    rows = {s["ticker"]: s for s in data["signals"]}
    assert rows["IREN"]["pageviews"] == 1234, "the half that answered still ships"
    assert rows["KEEL"]["pageviews"] is None, "and the half that did not, does not"

    health = json.loads((out / "health.json").read_text())
    assert health["sources"]["wikimedia"] == "degraded", \
        "a transport failure alongside a success is a partial outage, not a clean run"
    assert any("failed transport" in p for p in health["problems"]), \
        "the LED is the glanceable surface; the warn is the detail — both, not either"
    assert "wikimedia · degraded" in (out / "index.html").read_text()


def test_a_transport_failure_can_never_light_wikimedia_green(monkeypatch, tmp_path):
    """The direction the old ordering got wrong, pinned as a property rather than as
    one scenario: whatever else happened, a run with `transport_failures > 0` must not
    report "ok". Driven through the real LED expression at every raw_views shape."""
    import json
    import radar.run as run
    for raw_views, expected in (({}, "down"), ({"IREN": 5000}, "degraded")):
        _offline(monkeypatch, run, _board(run))
        _mapped_board(monkeypatch, run)
        monkeypatch.setattr(run.pageviews, "fetch_attention",
                            lambda titles, tickers, run_day, _rv=raw_views, **k: ({}, _rv, 3))
        out = tmp_path / ("out" + expected)
        assert run.main(["--dry-run", "--no-email", "--out", str(out)]) == 0
        health = json.loads((out / "health.json").read_text())
        assert health["sources"]["wikimedia"] == expected


def test_the_led_stylesheet_can_render_every_state_run_py_emits():
    """A state with no CSS rule renders as the DEFAULT green dot with a text suffix
    beside it — the exact "LED reads green during an outage" failure, moved one layer
    down into the stylesheet. The template's LED span emits `class="led {{ st }}"` for
    anything that is not "ok", so every non-ok state run.py can produce needs a rule."""
    import re
    from pathlib import Path
    import radar.run as run
    src = Path(run.__file__).read_text()
    block = re.search(r"sources = \{(.*?)\n    \}", src, re.S).group(1)
    emitted = set(re.findall(r'"(ok|down|degraded|unused|fallback)"', block))
    assert {"degraded", "down", "unused", "fallback"} <= emitted, \
        "this test must see the real LED states, not a refactored-away block"
    tpl = Path("radar/templates/dashboard.html.j2").read_text()
    for state in emitted - {"ok"}:
        assert f".srcs .led.{state}{{" in tpl, f"no LED colour for state {state!r}"


def test_a_corrupt_history_still_publishes_a_board(monkeypatch, tmp_path):
    """The pipeline half of the History.load fix. `data/history.json` rides the orphan
    data branch and is written with a bare truncate-then-write, so one interrupted job
    leaves a torn file — and a hard `json.loads` there took down every subsequent run,
    not just the one that tore it. Measured before the fix: truncating the file red-lined
    25 tests and would equally have killed the publish.

    Now it degrades: the board ships, every name reads as brand-new against an empty
    baseline (score.py's documented INV-8 path, identical to a genuine day-1 cold start),
    the Still Running lane is empty for a day, and health carries the reason."""
    import json
    import radar.run as run
    _offline(monkeypatch, run, _board(run))
    corrupt = tmp_path / "history.json"
    corrupt.write_text('{"IREN": {"2026-08-1')            # killed mid-write
    real = run.History.load.__func__                      # the real body, on a fake path
    monkeypatch.setattr(run.History, "load",
                        classmethod(lambda cls, path: real(cls, str(corrupt))))

    out = tmp_path / "out"
    assert run.main(["--dry-run", "--no-email", "--out", str(out)]) == 0
    health = json.loads((out / "health.json").read_text())
    assert any("history unreadable" in p for p in health["problems"]), \
        "a silently empty baseline is worse than the crash it replaced"
    data = json.loads((out / "data.json").read_text())
    assert set(data["board"]) == {"IREN", "KEEL"}, "the board still ships"
    assert all(s["state"] == "new" for s in data["signals"]), \
        "an empty baseline is a cold start, and every name reads brand-new against it"


# --- polarity: two different measurements that live one line apart -------------------

def test_short_ratio_and_days_to_cover_land_in_their_own_fields(monkeypatch, tmp_path):
    """These are DIFFERENT MEASUREMENTS and transposing them is silent.

      short_ratio    — the share of a single day's volume that was sold short. A
                       FRACTION, D-1 fresh, from FINRA's daily short-volume file.
      days_to_cover  — the open short POSITION expressed as days of average volume.
                       A COUNT, 11-24 days stale, from the twice-monthly settlement.

    Neither number carries a unit through the payload, so swapping them produces a
    perfectly well-formed board: the modal would print "0.6 days to cover" for a name
    with a 6.7-day squeeze, and "670% short vol" for one with a 62% one.

    Nothing caught that. Every fixture in this file stubbed `fetch_short_ratios` to
    ({}, ""), so `s.short_ratio` was None in every end-to-end test, and feeding
    `s.days_to_cover` into the payload's `short_ratio` (or `s.short_ratio` into
    `_detail_blob`'s `days_to_cover`, which is what the modal prints as "days to
    cover") survived the whole suite. Distinct non-None values on both, asserted in
    both surfaces, is the only thing that can tell them apart."""
    import json
    import re
    import radar.run as run
    _offline(monkeypatch, run, _board(run))
    monkeypatch.setattr(run, "fetch_short_ratios",
                        lambda cfg, run_day: ({"IREN": 0.62}, "2026-08-16"))
    monkeypatch.setattr(run.short_interest, "fetch_short_interest",
                        lambda cfg, run_day, **k: ({"IREN": {"days_to_cover": 6.7,
                                                             "shares": 12_000_000}},
                                                   "2026-07-31"))

    out = tmp_path / "out"
    assert run.main(["--dry-run", "--no-email", "--out", str(out)]) == 0

    row = next(s for s in json.loads((out / "data.json").read_text())["signals"]
               if s["ticker"] == "IREN")
    assert row["short_ratio"] == 0.62, "daily short VOLUME share, not the position"
    assert row["days_to_cover"] == 6.7, "open POSITION in days, not the volume share"
    assert row["short_interest_shares"] == 12_000_000
    assert row["short_interest_as_of"] == "2026-07-31"

    html = (out / "index.html").read_text()
    blob = json.loads(re.search(r'id="radar-data">(.*?)</script>', html, re.S).group(1))
    assert blob["IREN"]["short_ratio"] == 0.62, "the modal's 'short vol' metric"
    assert blob["IREN"]["days_to_cover"] == 6.7, "the modal's 'days to cover' metric"
    assert blob["IREN"]["short_interest_as_of"] == "2026-07-31"


def test_the_modal_pairs_days_to_cover_with_its_date_by_CONJUNCTION():
    """The line's own comment asserts "there is no code path here that can print a bare
    days-to-cover number" — and nothing checked it. The existing same-line guard passes
    on `&&` and on `||` alike, because both identifiers stay on the line either way, and
    `||` renders exactly the bare undated number the pairing exists to forbid.

    run.py's side of this invariant IS tested (a ticker FINRA never reported gets no
    settlement date either). The template's side was not."""
    import re
    from pathlib import Path
    tpl = Path("radar/templates/dashboard.html.j2").read_text()
    lines = [ln for ln in tpl.splitlines() if "d.days_to_cover" in ln]
    assert lines, "the detail modal must render days to cover somewhere"
    for ln in lines:
        compact = re.sub(r"\s+", "", ln)
        assert re.search(r"d\.days_to_cover!=null&&d\.short_interest_as_of"
                         r"|d\.short_interest_as_of&&d\.days_to_cover!=null", compact), \
            f"days-to-cover is not CONJOINED with its settlement date: {ln.strip()}"


def test_the_dna_cell_gets_brighter_as_the_component_gets_stronger():
    """A visually BACKWARDS attention signal ships green otherwise. The DNA strip's only
    encoding of magnitude is opacity, and inverting `0.15 + (c.val/100)*0.85` to
    `1.0 - (c.val/100)*0.85` renders a maxed-out component as the DIMMEST cell on the
    row — no test, no payload, no rendered string changes.

    Checked by EVALUATING the template's own expression rather than matching its text,
    so any rewrite that stays monotonic passes and any rewrite that flips fails."""
    import re
    from pathlib import Path
    tpl = Path("radar/templates/dashboard.html.j2").read_text()
    m = re.search(r'--a:\{\{\s*"%\.2f"\|format\((.+?)\)\s*\}\}', tpl)
    assert m, "the DNA cell's alpha expression must be findable"
    expr = m.group(1).replace("c.val", "v")          # valid Python as written

    alpha = [eval(expr, {"__builtins__": {}}, {"v": v}) for v in (0, 25, 50, 75, 100)]
    assert alpha == sorted(alpha), f"stronger components must not render dimmer: {alpha}"
    assert alpha[0] < alpha[-1], "the strip encodes magnitude only as opacity"
    assert all(0.0 <= a <= 1.0 for a in alpha), f"alpha outside the legal range: {alpha}"
    assert alpha[0] > 0.0, \
        "a real 0 must stay VISIBLE — an invisible cell is the `nul` (not covered) state"


def test_the_modal_renders_short_ratio_as_a_percentage():
    """`short_ratio` is a FRACTION on the wire (0.62 = 62% of the day's volume sold
    short). Dropping the `*100` turns that into `Math.round(0.62)+'%'` = "1%" — a
    hundredfold understatement of the single most bearish number on the row, rendered
    without an error and asserted by nothing."""
    import re
    from pathlib import Path
    tpl = Path("radar/templates/dashboard.html.j2").read_text()
    lines = [ln for ln in tpl.splitlines()
             if "d.short_ratio" in ln and "short vol" in ln]
    assert lines, "the modal must render a short-volume metric"
    for ln in lines:
        compact = re.sub(r"\s+", "", ln)
        assert "d.short_ratio*100" in compact, \
            f"a fraction rendered as a percentage without scaling: {ln.strip()}"
