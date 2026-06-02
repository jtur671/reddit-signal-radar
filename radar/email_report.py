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

def send_email(date_str: str, signals: list[dict]):
    key = os.environ.get("RESEND_API_KEY")
    to = os.environ.get("EMAIL_RECIPIENTS", "")
    if not key or not to:
        return False              # require both an API key and a recipient; no hardcoded address
    import resend
    resend.api_key = key
    resend.Emails.send({"from": "radar@resend.dev", "to": to.split(","),
        "subject": f"📡 Signal Radar — {date_str}", "html": build_email_html(date_str, signals)})
    return True
