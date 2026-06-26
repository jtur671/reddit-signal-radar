from __future__ import annotations
import os, html as _html

DASHBOARD_URL = "https://jtur671.github.io/reddit-signal-radar/"

# brand palette (light variant of the dashboard's terminal theme)
INK = "#16242e"
DIM = "#8b9199"
UP = "#3f9c6d"
DOWN = "#e0654f"
GOLD = "#e0b049"
HAIR = "#e6e9ec"
BG = "#ffffff"
PANEL = "#f6f8fa"

SANS = '-apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif'
MONO = '"SF Mono", SFMono-Regular, Consolas, "Liberation Mono", monospace'


def _esc(x) -> str:
    return _html.escape("" if x is None else str(x))


def _pct(value) -> tuple[str, str]:
    """(color, display) for a percent change. None -> em dash."""
    if value is None:
        return (DIM, "—")
    if value < 0:
        return (DOWN, f"▼{abs(value):.1f}%")
    return (UP, f"▲{value:.1f}%")


def _money(value) -> str:
    return f"${value:.2f}" if value is not None else "—"


def _button(href: str, label: str) -> str:
    return (f'<a href="{_esc(href)}" style="display:inline-block;padding:10px 18px;'
            f'background:{INK};color:#ffffff;text-decoration:none;border-radius:6px;'
            f'font-family:{SANS};font-size:13px;font-weight:600">{_esc(label)}</a>')


def _section(label: str) -> str:
    return (f'<div style="font-family:{SANS};font-size:12px;font-weight:700;letter-spacing:1px;'
            f'text-transform:uppercase;color:{DIM};margin:18px 0 4px">{_esc(label)}</div>')


def _shell(preheader: str, subtitle: str, body: str, accent: str = INK) -> str:
    """Outer 600px card: branded header (wordmark + subtitle, tinted by accent), body, footer."""
    return (
        f'<div style="background:{PANEL};padding:24px 0;font-family:{SANS};color:{INK}">'
        f'<span style="display:none!important;opacity:0;color:transparent;height:0;width:0;'
        f'overflow:hidden">{_esc(preheader)}</span>'
        f'<table align="center" width="600" cellpadding="0" cellspacing="0" '
        f'style="max-width:600px;margin:0 auto;background:{BG};border:1px solid {HAIR};'
        f'border-radius:10px;overflow:hidden">'
        f'<tr><td style="padding:18px 24px;border-bottom:2px solid {accent}">'
        f'<table width="100%" cellpadding="0" cellspacing="0"><tr>'
        f'<td style="font-family:{MONO};font-size:15px;font-weight:700;letter-spacing:1px;'
        f'color:{accent}">📡 SIGNAL RADAR</td>'
        f'<td align="right" style="font-family:{MONO};font-size:12px;color:{DIM}">{_esc(subtitle)}</td>'
        f'</tr></table></td></tr>'
        f'<tr><td style="padding:8px 24px 22px">{body}</td></tr>'
        f'<tr><td style="padding:16px 24px;border-top:1px solid {HAIR};background:{PANEL}">'
        f'<table width="100%" cellpadding="0" cellspacing="0"><tr>'
        f'<td>{_button(DASHBOARD_URL, "View live dashboard ↗")}</td>'
        f'<td align="right" style="font-family:{SANS};font-size:11px;color:{DIM}">'
        f'Not investment advice.</td>'
        f'</tr></table></td></tr>'
        f'</table></div>'
    )


def _mover_card(s: dict) -> str:
    color, pct = _pct(s.get("pct_change"))
    name = _esc(s.get("name") or "")
    state = _esc((s.get("state") or "").upper())
    chips = f'{_esc(s.get("mentions", ""))} mentions · {_esc(s.get("velocity", ""))}'
    if state:
        chips += f' · {state}'
    summary = _esc(s.get("summary") or "")
    name_html = (f'<div style="font-family:{SANS};font-size:13px;color:{DIM};margin-top:2px">'
                 f'{name}</div>') if name else ""
    summary_html = (f'<div style="font-family:{SANS};font-size:13px;color:{INK};margin-top:8px;'
                    f'line-height:1.45">"{summary}"</div>') if summary else ""
    return (
        f'<table width="100%" cellpadding="0" cellspacing="0" '
        f'style="margin:10px 0;border:1px solid {HAIR};border-radius:8px;background:{BG}">'
        f'<tr><td style="padding:14px 16px">'
        f'<table width="100%" cellpadding="0" cellspacing="0"><tr>'
        f'<td style="font-family:{MONO};font-size:22px;font-weight:700;color:{INK}">'
        f'{_esc(s.get("ticker", ""))}</td>'
        f'<td align="right" style="font-family:{MONO};font-size:17px;font-weight:700;color:{color}">'
        f'{_money(s.get("price"))}&nbsp;&nbsp;{pct}</td>'
        f'</tr></table>'
        f'{name_html}'
        f'<div style="font-family:{MONO};font-size:12px;color:{DIM};margin-top:6px">{chips}</div>'
        f'{summary_html}'
        f'</td></tr></table>'
    )


def _rest_table(rows: list[dict]) -> str:
    if not rows:
        return ""
    trs = ""
    for s in rows:
        color, pct = _pct(s.get("pct_change"))
        trs += (
            f'<tr>'
            f'<td style="padding:6px 0;font-family:{MONO};font-size:13px;font-weight:700;'
            f'color:{INK}">{_esc(s.get("ticker", ""))}</td>'
            f'<td style="padding:6px 0;font-family:{MONO};font-size:13px;color:{color}">{pct}</td>'
            f'<td align="right" style="padding:6px 0;font-family:{MONO};font-size:12px;color:{DIM}">'
            f'{_esc(s.get("mentions", ""))} · {_esc(s.get("velocity", ""))}</td>'
            f'</tr>')
    return f'<table width="100%" cellpadding="0" cellspacing="0">{trs}</table>'


def _still_block(still) -> str:
    if not still:
        return ""
    trs = ""
    for s in still:
        color, pct = _pct(s.get("pct_change"))
        trs += (
            f'<tr>'
            f'<td style="padding:6px 0;font-family:{MONO};font-size:13px;font-weight:700;'
            f'color:{INK}">{_esc(s.get("ticker", ""))}</td>'
            f'<td style="padding:6px 0;font-family:{MONO};font-size:13px;color:{color}">'
            f'{_money(s.get("price"))} {pct}</td>'
            f'<td align="right" style="padding:6px 0;font-family:{MONO};font-size:12px;color:{GOLD}">'
            f'running {int(s.get("days_running") or 0)}d</td>'
            f'</tr>')
    return _section("Still Running") + f'<table width="100%" cellpadding="0" cellspacing="0">{trs}</table>'


def build_email_html(date_str: str, signals: list[dict], still: list[dict] | None = None) -> str:
    signals = signals or []
    if not signals:
        body = (f'<div style="font-family:{SANS};font-size:14px;color:{DIM};padding:12px 0">'
                f'No signals on the board today — the tape is quiet.</div>')
        return _shell(f"Signal Radar — {date_str}", date_str, body)
    body = _section("Top Movers") + "".join(_mover_card(s) for s in signals[:3])
    rest = _rest_table(signals[3:])
    if rest:
        body += _section("The Rest") + rest
    body += _still_block(still)
    pre = f"Top: {signals[0].get('ticker', '')} {_pct(signals[0].get('pct_change'))[1]}"
    return _shell(pre, date_str, body)


def build_trump_alert_email(alert: dict) -> str:
    tickers = alert.get("tickers", [])
    chips = "".join(
        f'<span style="display:inline-block;margin:0 6px 6px 0;padding:6px 12px;'
        f'background:#fdf3df;color:{GOLD};border:1px solid {GOLD};border-radius:6px;'
        f'font-family:{MONO};font-size:14px;font-weight:700">${_esc(t)}</span>'
        for t in tickers)
    post = _esc(alert.get("post", ""))
    when = _esc(alert.get("published") or alert.get("detected_at") or "")
    body = (
        f'<div style="font-family:{SANS};font-size:14px;color:{INK};margin:10px 0 8px">'
        f'Trump just named</div>'
        f'<div style="margin-bottom:4px">{chips}</div>'
        f'<table width="100%" cellpadding="0" cellspacing="0" '
        f'style="margin:12px 0;border-left:3px solid {DOWN};background:{PANEL};border-radius:4px">'
        f'<tr><td style="padding:12px 14px;font-family:{SANS};font-size:15px;line-height:1.5;'
        f'color:{INK}">"{post}"</td></tr></table>'
        f'<table width="100%" cellpadding="0" cellspacing="0"><tr>'
        f'<td style="font-family:{MONO};font-size:12px;color:{DIM}">{when}</td>'
        f'<td align="right">{_button(alert.get("url", ""), "View post ↗")}</td>'
        f'</tr></table>'
    )
    pre = "Trump named " + ", ".join("$" + t for t in tickers)
    return _shell(pre, "🚨 PUMP ALERT", body, accent=DOWN)


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


def send_email(date_str: str, signals: list[dict], still: list[dict] | None = None) -> bool:
    return _send(f"📡 Signal Radar — {date_str}", build_email_html(date_str, signals, still))


def send_trump_alert(alert: dict) -> bool:
    tickers = ", ".join("$" + t for t in alert.get("tickers", []))
    return _send(f"🚨 Trump post mentions {tickers}", build_trump_alert_email(alert))


def build_monitor_alert_email(alert: dict) -> str:
    """Generic alert email for any monitor. `alert` is the self-describing dict written by
    monitors.base.write_alert (label, tickers, summary, url, published/detected_at, link_text).
    summary is HTML-escaped (untrusted source text)."""
    label = _esc(alert.get("label", "Alert"))
    tickers = alert.get("tickers", [])
    accent = DOWN if "trump" in label.lower() else GOLD
    chips = "".join(
        f'<span style="display:inline-block;margin:0 6px 6px 0;padding:6px 12px;'
        f'background:#fdf3df;color:{GOLD};border:1px solid {GOLD};border-radius:6px;'
        f'font-family:{MONO};font-size:14px;font-weight:700">${_esc(t)}</span>'
        for t in tickers)
    summary = _esc(alert.get("summary", ""))
    when = _esc(alert.get("published") or alert.get("detected_at") or "")
    link_text = alert.get("link_text") or "View ↗"
    body = (
        f'<div style="font-family:{SANS};font-size:13px;font-weight:700;letter-spacing:1px;'
        f'text-transform:uppercase;color:{accent};margin:10px 0 8px">{label}</div>'
        f'<div style="margin-bottom:4px">{chips}</div>'
        f'<table width="100%" cellpadding="0" cellspacing="0" '
        f'style="margin:12px 0;border-left:3px solid {accent};background:{PANEL};border-radius:4px">'
        f'<tr><td style="padding:12px 14px;font-family:{SANS};font-size:15px;line-height:1.5;'
        f'color:{INK}">{summary}</td></tr></table>'
        f'<table width="100%" cellpadding="0" cellspacing="0"><tr>'
        f'<td style="font-family:{MONO};font-size:12px;color:{DIM}">{when}</td>'
        f'<td align="right">{_button(alert.get("url", ""), link_text)}</td>'
        f'</tr></table>'
    )
    pre = label + ": " + ", ".join("$" + t for t in tickers)
    return _shell(pre, "🚨 SIGNAL ALERT", body, accent=accent)


def send_monitor_alert(alert: dict) -> bool:
    tickers = ", ".join("$" + t for t in alert.get("tickers", []))
    subject = f"🚨 {alert.get('label', 'Alert')} — {tickers}"
    return _send(subject, build_monitor_alert_email(alert))
