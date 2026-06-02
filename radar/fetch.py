from __future__ import annotations
import time, requests
from radar.models import Item

def _as_float(v) -> float:
    try:
        f = float(v or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return f if f == f and f not in (float("inf"), float("-inf")) else 0.0  # reject NaN/inf


def _as_int(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def parse_listing(raw, kind: str) -> list[Item]:
    """Tolerant parser for untrusted/malformed Reddit JSON. MUST never raise:
    null data, null/non-list children, non-dict children, and non-numeric
    created_utc/score all degrade to safe defaults rather than crashing."""
    items: list[Item] = []
    data = raw.get("data") if isinstance(raw, dict) else None
    children = data.get("children") if isinstance(data, dict) else None
    if not isinstance(children, list):
        return items
    for child in children:
        if not isinstance(child, dict):
            continue
        d = child.get("data")
        if not isinstance(d, dict):
            d = {}
        text = " ".join(str(x) for x in (d.get("title"), d.get("selftext"), d.get("body")) if x)
        items.append(Item(
            id=d.get("id", "") or "", kind=kind, subreddit=d.get("subreddit", "") or "",
            author=d.get("author") or "[deleted]",
            created_utc=_as_float(d.get("created_utc")),
            text=text, score=_as_int(d.get("score")),
            permalink=d.get("permalink", "") or "",
        ))
    return items

def _get(url: str, ua: str, retries: int, sleep_s: float) -> dict | None:
    for attempt in range(retries):
        try:
            r = requests.get(url, headers={"User-Agent": ua}, timeout=20)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503):
                time.sleep(sleep_s * (2 ** attempt)); continue
            return None                      # 403/404 etc -> skip
        except requests.RequestException:
            time.sleep(sleep_s * (2 ** attempt))
    return None

def fetch_subreddit(sub: str, cfg) -> list[Item]:
    """Fetch configured listings + comment trees for hottest posts. Never raises."""
    ua, items = cfg.fetch.user_agent, []
    for listing in cfg.fetch.listings:
        url = f"https://www.reddit.com/r/{sub}/{listing}.json?limit={cfg.fetch.post_limit}"
        raw = _get(url, ua, cfg.fetch.max_retries, cfg.fetch.sleep_seconds)
        time.sleep(cfg.fetch.sleep_seconds)
        if raw:
            items.extend(parse_listing(raw, kind="post"))
    seen, hot = set(), [i for i in items if i.permalink][: cfg.fetch.comment_posts]
    for post in hot:
        if post.permalink in seen:
            continue
        seen.add(post.permalink)
        raw = _get(f"https://www.reddit.com{post.permalink}.json?limit=200&depth=2",
                   ua, cfg.fetch.max_retries, cfg.fetch.sleep_seconds)
        time.sleep(cfg.fetch.sleep_seconds)
        if isinstance(raw, list) and len(raw) > 1:
            items.extend(parse_listing(raw[1], kind="comment"))
    return items
