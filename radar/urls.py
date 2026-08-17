"""Scheme allowlist for links that came from a feed.

Alert URLs are supplied by upstream sources we do not control: the Truth Social RSS
`<link>` (radar/monitors/prose.py) and the third-party congress-trades JSON `doc_url`
(radar/monitors/congress.py). Those strings land in an `href` on the public dashboard
and in the alert emails.

Jinja autoescaping (radar/render.py) stops a feed from breaking out of the attribute,
but it does NOT stop the scheme: `javascript:alert(1)` survives escaping intact and
becomes a clickable script on a public page. So the scheme is filtered here — http and
https survive, everything else (javascript:, data:, vbscript:, file:, protocol-relative,
relative, junk) becomes "" and the caller drops the link entirely.
"""
from __future__ import annotations

from urllib.parse import urlparse

_ALLOWED_SCHEMES = ("http", "https")


def safe_url(url) -> str:
    """The URL unchanged if it is http(s), else "". Never raises — a malformed feed
    URL must not crash a run."""
    if not isinstance(url, str):
        return ""
    candidate = url.strip()
    if not candidate:
        return ""
    try:
        scheme = urlparse(candidate).scheme
    except ValueError:      # e.g. unmatched IPv6 bracket — urlsplit raises
        return ""
    return candidate if scheme.lower() in _ALLOWED_SCHEMES else ""
