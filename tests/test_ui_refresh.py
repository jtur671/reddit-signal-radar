"""UI refresh — the new-data surfaces render (and degrade) correctly."""
from radar.render import render_html
from radar.run import _build_context
from radar.models import Signal


def _sig(t, **kw):
    s = Signal(ticker=t, mentions=50, score=60.0, pct_bull=40.0, state="hot")
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def _board():
    a = _sig("AAA", composite=61,
             components={"velocity": 100.0, "direction": 55.0, "engagement": 40.0,
                         "short_pressure": 80.0, "options": None, "events": 0.0,
                         "cramer_inverse": None},
             short_ratio=0.62, pc_ratio=1.4, uoa=True, cramer="strong_buy")
    b = _sig("BBB")   # no alt-data coverage at all
    return [a, b]


def test_listings_show_composite_and_dna():
    html = render_html(**_build_context(_board(), [], "2026-08-08", 0))
    assert "Signal DNA" in html
    assert '<span class="cmp">61</span>' in html
    assert '<span class="cmp na">—</span>' in html    # uncovered name shows a dash
    assert 'class="nul"' in html                      # None components render as empty cells
    assert "signal dna: vel · dir · eng" in html      # legend
    assert "◆" in html                                # UOA marker


def test_mover_card_alt_data():
    html = render_html(**_build_context(_board(), [], "2026-08-08", 0))
    assert "CRAMER: strong buy" in html
    assert ">UOA</span>" in html
    assert "short vol" in html and "put/call" in html


def test_modal_scaffolding_present():
    html = render_html(**_build_context(_board(), [], "2026-08-08", 0))
    assert 'id="m-comps"' in html and "signal components" in html


def test_sources_leds():
    html = render_html(**_build_context(_board(), [], "2026-08-08", 0,
                       sources={"apewisdom": "ok", "cboe": "down", "finnhub": "unused"}))
    assert "data sources" in html
    assert 'class="led"' in html
    assert 'class="led down"' in html and "cboe · down" in html
    assert 'class="led unused"' in html


def test_sources_strip_hidden_when_absent():
    html = render_html(**_build_context(_board(), [], "2026-08-08", 0))
    assert "data sources" not in html


def test_track_record_rows_and_crypto_note():
    sc = {"n_picks": 2, "since": "2026-08-07", "mean_excess_10d": None,
          "win_rate_10d": None, "mean_excess_5d": None, "win_rate_5d": None,
          "excluded_crypto": 1,
          "picks": [{"date": "2026-08-07", "ticker": "AAA", "conviction": "high",
                     "excess_5d": None, "excess_10d": None},
                    {"date": "2026-08-07", "ticker": "BBB", "conviction": "low",
                     "excess_5d": 0.031, "excess_10d": -0.012}],
          "disclaimer": "Not advice."}
    html = render_html(**_build_context(_board(), [], "2026-08-08", 0, scorecard=sc))
    assert "grading" in html
    assert "+3.1%" in html and "-1.2%" in html
    assert "1 crypto pick excluded from grading" in html


def test_empty_board_still_renders():
    html = render_html(**_build_context([], [], "2026-08-08", 0))
    assert "No listings today." in html
