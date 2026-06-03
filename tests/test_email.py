from radar.email_report import build_email_html
def test_email_lists_top_signals():
    html = build_email_html("Jun 1", [dict(ticker="IREN",velocity=9.4,state="new",pct_bull=78,
                                            price=14.2,pct_change=8.1,summary="GPU")])
    assert "IREN" in html and "9.4" in html

def test_email_includes_still_running_block():
    html = build_email_html(
        "Jun 3",
        [dict(ticker="IREN", velocity=9.4, state="new", pct_bull=78,
              price=14.2, pct_change=8.1, summary="GPU")],
        still=[dict(ticker="MRVL", price=308.69, pct_change=6.1, days_running=1)])
    assert "Still Running" in html
    assert "MRVL" in html
    assert "running 1d" in html


def test_email_no_still_block_when_empty():
    html = build_email_html(
        "Jun 3",
        [dict(ticker="IREN", velocity=9.4, state="new", pct_bull=78,
              price=14.2, pct_change=8.1, summary="GPU")])
    assert "Still Running" not in html
