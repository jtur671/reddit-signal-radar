from radar.render import render_html

def _mover(**k):
    base = dict(rank=1, ticker="IREN", state_label="Breaking", css="live", price=14.2,
                pct_change=8.1, theme="AI Compute", mentions=312, vel24_disp="9.4×", vel24_num=9.4,
                surprise=4.7, authors=184, pct_bull=78, summary="GPU pivot", subreddits="r/wsb")
    base.update(k); return base

def test_render_contains_board_and_escapes_xss():
    html = render_html(
        meta=dict(date="Jun 1 2026", edition_no=142, corpus_count="41.2k",
                  signals_tracked=15, biggest_breakout="IREN 9.4×", most_bullish="78%"),
        today_read=dict(lead="AI miners breaking out", bullets=[]),
        board=[dict(rank=1,ticker="IREN",mentions=312,vel24_disp="9.4×",vel24_num=9.4,state="new",emoji="🆕",heat_pct=100,css="live")],
        movers=[_mover(summary="<script>alert(1)</script>")],
        listings=[], themes=["All","AI Compute"], cooling=[], trend="0,50 100,5")
    assert "IREN" in html
    assert "<script>alert(1)</script>" not in html      # escaped
    assert "&lt;script&gt;" in html

def test_render_empty_board_shows_no_signals():
    html = render_html(meta=dict(date="x",edition_no=1,corpus_count="0",signals_tracked=0,
                       biggest_breakout="—",most_bullish="—"), today_read=dict(lead="No signals today.", bullets=[]),
                       board=[], movers=[], listings=[], themes=["All"], cooling=[], trend="")
    assert "No signals" in html or "no signals" in html.lower()


from radar.run import _chip_list, _build_context
from radar.themes import Themes
from radar.models import Signal

def _themes_b():
    return Themes({"ai_compute": {"label": "AI Compute", "seeds": ["IREN"]},
                   "crypto": {"label": "Crypto", "seeds": ["BTC"]},
                   "trump": {"label": "Trump", "seeds": ["DJT"]}})

def _bsig(ticker, themes):
    s = Signal(ticker=ticker, mentions=10); s.themes = themes; s.vel_24h = 2.0; return s

def test_chip_list_present_plus_always_trump():
    chips = _chip_list([_bsig("IREN", ["AI Compute"])], _themes_b())
    assert chips[0] == "All" and "AI Compute" in chips and "Trump" in chips
    assert "Crypto" not in chips           # not on board -> not a chip

def test_items_carry_data_themes_and_chips_render():
    board = [_bsig("IREN", ["AI Compute", "AI"])]
    html = render_html(**_build_context(board, board, "2026-06-02", 100,
                                        chips=_chip_list(board, _themes_b())))
    assert 'data-themes="AI Compute|AI"' in html
    assert 'data-theme="Trump"' in html    # Trump chip always filterable


def test_radar_data_blob_is_xss_safe():
    from radar.run import _detail_blob, _build_context
    from radar.history import History
    s = Signal(ticker="EVIL", mentions=5)
    s.themes = ["AI Compute"]; s.subreddits = ["x"]; s.vel_24h = 1.0
    s.summary = '</script><script>alert(1)</script>'
    blob = _detail_blob([s], History("x", {}), "2026-06-02")
    html = render_html(**_build_context([s], [s], "2026-06-02", 100, detail_json=blob))
    assert '</script><script>alert(1)</script>' not in html      # not injected raw
    assert '\\u003c/script\\u003e' in html                        # tojson-escaped instead

def test_tiles_have_data_ticker():
    s = _bsig("NVDA", ["AI"])
    html = render_html(**_build_context([s], [s], "2026-06-02", 100))
    assert 'data-ticker="NVDA"' in html

def test_still_running_section_renders():
    s = _bsig("MRVL", ["AI Compute"])
    s.days_running = 1; s.price = 308.69; s.pct_change = 6.1; s.name = "Marvell"
    html = render_html(**_build_context([], [s], "2026-06-03", 100, still=[s]))
    assert "Still Running" in html
    assert 'data-ticker="MRVL"' in html
    assert "running 1d" in html


def test_still_running_section_hidden_when_empty():
    s = _bsig("IREN", ["AI Compute"])
    html = render_html(**_build_context([s], [s], "2026-06-03", 100))
    assert "Still Running" not in html


import json
from radar.run import _build_context
from radar.render import render_html


def test_two_alert_cards_render_both(tmp_path):
    (tmp_path / "trump_alert.json").write_text(json.dumps(dict(
        monitor_key="trump", label="⚠ Trump Alert", card_style="trump",
        link_text="Truth Social post ↗", tickers=["TSLA"], summary="Tesla is great",
        url="http://t", published="2026-06-26T12:00:00Z",
        detected_at="2026-06-26T12:00:00Z")))
    (tmp_path / "edgar_alert.json").write_text(json.dumps(dict(
        monitor_key="edgar", label="📄 Insider Buy", card_style="insider",
        link_text="View filing ↗", tickers=["ACME"],
        summary="Insider buy — Director bought 10,000 sh of $ACME", url="http://s",
        published="2026-06-26T11:00:00Z", detected_at="2026-06-26T11:00:00Z")))
    import radar.run as run
    alerts = run._load_alerts(str(tmp_path))
    html = render_html(**_build_context([], [], "2026-06-26", 0, alerts=alerts))
    assert "Trump Alert" in html and "Insider Buy" in html
    assert "$TSLA" in html and "$ACME" in html


def test_stale_alert_card_is_dropped(tmp_path, monkeypatch):
    (tmp_path / "edgar_alert.json").write_text(json.dumps(dict(
        monitor_key="edgar", label="📄 Insider Buy", card_style="insider",
        tickers=["OLD"], summary="ancient", url="", published="2020-01-01T00:00:00Z",
        detected_at="2020-01-01T00:00:00Z")))
    import radar.run as run
    assert run._load_alerts(str(tmp_path)) == []     # older than max_age -> filtered
