"""Real Reddit post titles + links per ticker, via the authenticated Reddit API.

ApeWisdom gives counts, the public JSON 403s cloud IPs — but the *authenticated* OAuth API
(oauth.reddit.com) generally works from datacenter IPs. App-only ("client_credentials") auth
needs just a client id + secret (a Reddit "web app"), no user password.

Everything here is fail-safe: no credentials, no token, a 403, or a parse error all yield []
so the dashboard simply falls back to the existing Reddit search link. Pure parsing is split
out (parse_listing) so it can be tested without the network.
"""
from __future__ import annotations

import os

import requests

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
OAUTH = "https://oauth.reddit.com"


def get_token(client_id: str, client_secret: str, ua: str) -> str | None:
    """App-only bearer token (client_credentials grant). None on missing creds or any failure."""
    if not client_id or not client_secret:
        return None
    try:
        r = requests.post(TOKEN_URL, auth=(client_id, client_secret),
                          data={"grant_type": "client_credentials"},
                          headers={"User-Agent": ua}, timeout=15)
        if r.status_code == 200:
            return r.json().get("access_token") or None
    except requests.RequestException:
        pass
    return None


def token_from_env(ua: str) -> str | None:
    """Convenience: build a token from REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET (or None)."""
    return get_token(os.environ.get("REDDIT_CLIENT_ID", ""),
                     os.environ.get("REDDIT_CLIENT_SECRET", ""), ua)


def parse_listing(raw: dict, max_items: int = 4) -> list[dict]:
    """Pure parser of a Reddit listing JSON into [{title, url, score, subreddit}]. Never raises."""
    out: list[dict] = []
    children = (raw.get("data") or {}).get("children") if isinstance(raw, dict) else None
    for c in (children or []):
        d = (c or {}).get("data") or {}
        title = str(d.get("title") or "").strip()
        perm = d.get("permalink") or ""
        if not title or not perm:
            continue
        out.append({"title": title, "url": "https://www.reddit.com" + perm,
                    "score": int(d.get("score") or 0),
                    "subreddit": str(d.get("subreddit") or "")})
        if len(out) >= max_items:
            break
    return out


def top_posts(ticker: str, subs, token: str | None, ua: str, limit: int = 4) -> list[dict]:
    """Top posts this week mentioning $ticker, scoped to `subs` (or site-wide). [] when there's
    no token or on any failure — the caller then falls back to the Reddit search link."""
    if not token:
        return []
    base = f"{OAUTH}/r/{'+'.join(subs)}/search" if subs else f"{OAUTH}/search"
    params = {"q": f"${ticker}", "sort": "top", "t": "week", "limit": limit, "type": "link"}
    if subs:
        params["restrict_sr"] = "1"
    try:
        r = requests.get(base, params=params, timeout=15,
                         headers={"User-Agent": ua, "Authorization": f"bearer {token}"})
        if r.status_code == 200:
            return parse_listing(r.json(), limit)
    except requests.RequestException:
        pass
    return []
