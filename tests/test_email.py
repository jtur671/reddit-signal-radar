from radar.email_report import (
    build_email_html, build_trump_alert_email, _pct, _money, DASHBOARD_URL, DIM, UP, DOWN,
)


def _sig(**k):
    base = dict(ticker="IREN", velocity="9.4×", state="new", pct_bull=78,
                price=14.2, pct_change=8.1, summary="GPU pivot", mentions=312, name="Iris Energy")
    base.update(k)
    return base


# --- preserved behavior ---

def test_email_lists_top_signals():
    html = build_email_html("Jun 1", [dict(ticker="IREN", velocity=9.4, state="new",
                                            pct_bull=78, price=14.2, pct_change=8.1, summary="GPU")])
    assert "IREN" in html and "9.4" in html


def test_email_includes_still_running_block():
    html = build_email_html(
        "Jun 3",
        [_sig()],
        still=[dict(ticker="MRVL", price=308.69, pct_change=6.1, days_running=1)])
    assert "Still Running" in html
    assert "MRVL" in html
    assert "running 1d" in html


def test_email_no_still_block_when_empty():
    html = build_email_html("Jun 3", [_sig()])
    assert "Still Running" not in html


# --- new: helpers ---

def test_pct_and_money_none_render_dash():
    assert _pct(None) == (DIM, "—")
    assert _money(None) == "—"


def test_pct_direction_and_format():
    assert _pct(8.1) == (UP, "▲8.1%")
    assert _pct(-2.0) == (DOWN, "▼2.0%")
    assert _money(14.2) == "$14.20"


# --- new: daily digest cards ---

def test_email_mover_card_shows_fields():
    html = build_email_html("Jun 3", [_sig(ticker="MRVL", name="Marvell",
                                            price=308.69, pct_change=6.1, summary="Huang hype")])
    assert "MRVL" in html
    assert "Marvell" in html
    assert "$308.69" in html
    assert "▲6.1%" in html
    assert "312 mentions" in html
    assert "Huang hype" in html


def test_email_escapes_summary_xss():
    html = build_email_html("Jun 3", [_sig(summary="<script>alert(1)</script>")])
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_email_empty_board_is_graceful():
    html = build_email_html("Jun 3", [])
    assert "No signals" in html
    assert "<table" in html


def test_email_footer_has_dashboard_button():
    html = build_email_html("Jun 3", [_sig()])
    assert DASHBOARD_URL in html
    assert "View live dashboard" in html


# --- new: trump alert ---

def test_trump_email_chips_quote_and_button():
    html = build_trump_alert_email({
        "tickers": ["DJT", "TSLA"],
        "post": "buy <b>now</b>",
        "url": "https://truthsocial.com/x",
        "detected_at": "2026-06-03T19:30:00Z",
    })
    assert "$DJT" in html and "$TSLA" in html
    assert "buy &lt;b&gt;now&lt;/b&gt;" in html
    assert "<b>now</b>" not in html
    assert "View post" in html
    assert "https://truthsocial.com/x" in html
