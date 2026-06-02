from radar.email_report import build_email_html
def test_email_lists_top_signals():
    html = build_email_html("Jun 1", [dict(ticker="IREN",velocity=9.4,state="new",pct_bull=78,
                                            price=14.2,pct_change=8.1,summary="GPU")])
    assert "IREN" in html and "9.4" in html
