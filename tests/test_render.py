from radar.render import render_html

def _mover(**k):
    base = dict(rank=1, ticker="IREN", state_label="Breaking", css="live", price=14.2,
                pct_change=8.1, theme="AI Compute", mentions=312, velocity=9.4, surprise=4.7,
                authors=184, pct_bull=78, summary="GPU pivot", subreddits="r/wsb")
    base.update(k); return base

def test_render_contains_board_and_escapes_xss():
    html = render_html(
        meta=dict(date="Jun 1 2026", edition_no=142, corpus_count="41.2k",
                  signals_tracked=15, biggest_breakout="IREN 9.4×", most_bullish="78%"),
        mood="AI miners breaking out",
        board=[dict(rank=1,ticker="IREN",mentions=312,velocity=9.4,state="new",emoji="🆕",heat_pct=100,css="live")],
        movers=[_mover(summary="<script>alert(1)</script>")],
        listings=[], themes=["All","AI Compute"], cooling=[], trend="0,50 100,5")
    assert "IREN" in html
    assert "<script>alert(1)</script>" not in html      # escaped
    assert "&lt;script&gt;" in html

def test_render_empty_board_shows_no_signals():
    html = render_html(meta=dict(date="x",edition_no=1,corpus_count="0",signals_tracked=0,
                       biggest_breakout="—",most_bullish="—"), mood="No signals today.",
                       board=[], movers=[], listings=[], themes=["All"], cooling=[], trend="")
    assert "No signals" in html or "no signals" in html.lower()
