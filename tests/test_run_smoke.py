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
    monkeypatch.setattr(run.tickermap, "fetch_ticker_map", lambda cfg, run_day: mapped)
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
    monkeypatch.setattr(run.tickermap, "fetch_ticker_map", lambda cfg, run_day: {})

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
    monkeypatch.setattr(run.tickermap, "fetch_ticker_map", lambda cfg, run_day: dict(only_overrides))

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
    monkeypatch.setattr(run.tickermap, "fetch_ticker_map", lambda cfg, run_day: merged)

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
    monkeypatch.setattr(run.tickermap, "fetch_ticker_map", lambda cfg, run_day: {})

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
                                                                {"IREN": 5000}))

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
                            lambda titles, tickers, run_day, **k: (attention, {}))
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
                        lambda cfg, run_day: {"IREN": "Iris Energy",   # a REDIRECT title
                                               "KEEL": "Keel Infrastructure"})
    # The summary endpoint resolves IREN's redirect; KEEL's article answers under the
    # title we asked for, so its canonical and mapped titles are the same string.
    canonical = {"Iris Energy": "IREN Limited"}
    monkeypatch.setattr(run.about, "fetch_summary",
                        lambda title, ua="x": {"desc": "d", "extract": "e",
                                                "title": canonical.get(title, title)})
    seen = {}
    monkeypatch.setattr(run.pageviews, "fetch_attention",
                        lambda titles, tickers, run_day, **k: (seen.update(titles), ({}, {}))[1])

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
                        lambda cfg, run_day: {"IREN": "IREN Limited"})
    monkeypatch.setattr(run.about, "fetch_summary", lambda *a, **k: None)   # empty title
    seen = {}
    monkeypatch.setattr(run.pageviews, "fetch_attention",
                        lambda titles, tickers, run_day, **k: (seen.update(titles), ({}, {}))[1])

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
                        lambda cfg, run_day: ({"IREN": {"days_to_cover": 6.7,
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
    assert "2026-07-31" in html, "the settlement date reaches the page, not just the payload"


def test_a_dateless_settlement_suppresses_days_to_cover_entirely(monkeypatch, tmp_path):
    """`as_of` is non-negotiable, so it is enforced where the value is SET, not only
    where it is rendered: rows with no settlement date (a malformed vendored snapshot
    is the realistic path) ship no days-to-cover at all rather than an undated one."""
    import json
    import radar.run as run
    _offline(monkeypatch, run, _board(run))
    monkeypatch.setattr(run.short_interest, "fetch_short_interest",
                        lambda cfg, run_day: ({"IREN": {"days_to_cover": 6.7,
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


def test_new_sources_report_themselves_down_when_both_are_dead(monkeypatch, tmp_path):
    """The LED trap, guarded: `"ok" if X else "down"` is only honest when X can actually
    be empty on failure. Under the hermeticity stubs both sources take their real outage
    paths — Wikimedia returns no series for any ticker, FINRA has neither an upstream nor
    a vendored snapshot — so this asserts the red state is reachable, which is exactly
    what the tickermap LED could not do before it was fixed."""
    import json
    import radar.run as run
    _offline(monkeypatch, run, _board(run))

    out = tmp_path / "out"
    assert run.main(["--dry-run", "--no-email", "--out", str(out)]) == 0
    health = json.loads((out / "health.json").read_text())
    assert health["sources"]["wikimedia"] == "down"
    assert health["sources"]["finra_si"] == "down"
    html = (out / "index.html").read_text()
    assert "wikimedia · down" in html and "finra_si · down" in html   # generic footer loop
    assert "IREN" in html                                             # and the board still ships


def test_new_sources_report_ok_when_they_answer(monkeypatch, tmp_path):
    """The green side of both LEDs. wikimedia keys off RAW VIEWS, not scores: a healthy
    Wikimedia whose tickers all fail spike_score's 21-day/10-view baseline floor has
    answered every request, and lighting that red would be a false alarm about a source
    that is up."""
    import json
    import radar.run as run
    _offline(monkeypatch, run, _board(run))
    monkeypatch.setattr(run.pageviews, "fetch_attention",
                        lambda titles, tickers, run_day, **k: ({}, {"IREN": 5000}))
    monkeypatch.setattr(run.short_interest, "fetch_short_interest",
                        lambda cfg, run_day: ({"IREN": {"days_to_cover": 6.7,
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
                        lambda cfg, run_day: ({"IREN": {"days_to_cover": 6.7,
                                                         "shares": 12_000_000}},
                                               "2026-07-31"))

    out = tmp_path / "out"
    assert run.main(["--dry-run", "--no-email", "--out", str(out)]) == 0
    rows = {s["ticker"]: s for s in json.loads((out / "data.json").read_text())["signals"]}
    assert rows["IREN"]["short_interest_as_of"] == "2026-07-31"
    assert rows["KEEL"]["days_to_cover"] is None
    assert rows["KEEL"]["short_interest_as_of"] is None, "a date with no number is a claim of data"
    assert rows["KEEL"]["short_interest_shares"] is None
