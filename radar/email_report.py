from __future__ import annotations
import os, html as _html

def build_email_html(date_str: str, signals: list[dict]) -> str:
    rows = "".join(
        f"<tr><td><b>{_html.escape(s['ticker'])}</b></td><td>{s['velocity']}×</td>"
        f"<td>{s['pct_bull']}% bull</td><td>{s.get('price') or '—'}</td>"
        f"<td>{_html.escape(str(s.get('summary','')))}</td></tr>"
        for s in signals)
    return (f"<h2>Reddit Signal Radar — {date_str}</h2>"
            f"<table cellpadding=6>{rows}</table>"
            f"<p style='color:#888'>Not investment advice.</p>")

def _send(subject: str, html: str) -> bool:
    key = os.environ.get("RESEND_API_KEY")
    to = os.environ.get("EMAIL_RECIPIENTS", "")
    if not key or not to:
        return False              # require both an API key and a recipient; no hardcoded address
    import resend
    resend.api_key = key
    sender = os.environ.get("RESEND_FROM", "onboarding@resend.dev")
    resend.Emails.send({"from": sender, "to": to.split(","),
                        "subject": subject, "html": html})
    return True

def send_email(date_str: str, signals: list[dict]) -> bool:
    return _send(f"📡 Signal Radar — {date_str}", build_email_html(date_str, signals))

def build_trump_alert_email(alert: dict) -> str:
    tickers = ", ".join("$" + t for t in alert.get("tickers", []))
    post = _html.escape(alert.get("post", ""))
    url = _html.escape(alert.get("url", ""))
    when = _html.escape(alert.get("published") or alert.get("detected_at") or "")
    return (f"<h2>🚨 Trump just named {_html.escape(tickers)}</h2>"
            f"<p style='font-size:15px;line-height:1.5'>“{post}”</p>"
            f"<p style='color:#888'>{when} · <a href=\"{url}\">view post</a></p>"
            f"<p style='color:#888'>Reddit Signal Radar · Not investment advice.</p>")

def send_trump_alert(alert: dict) -> bool:
    tickers = ", ".join("$" + t for t in alert.get("tickers", []))
    return _send(f"🚨 Trump post mentions {tickers}", build_trump_alert_email(alert))
