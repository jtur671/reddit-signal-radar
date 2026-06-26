"""Trump Truth Social monitor: pull his recent posts (via the free, no-auth, cloud-IP-
friendly trumpstruth.org RSS feed) and detect when he names a ticker/company, so the
dashboard can show an alert card and an email can fire immediately.

Pure parsing/detection here; the orchestration lives in radar/monitor.py.
"""
from __future__ import annotations

import html as _html
import json
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests
import yaml

CASHTAG = re.compile(r"\$([A-Za-z]{1,5})\b")
_TAG = re.compile(r"<[^>]+>")
FEED_URL = "https://www.trumpstruth.org/feed"


@dataclass
class Post:
    id: str
    text: str
    url: str
    published: str            # ISO-8601 'Z', or "" if unparseable


def _strip_html(s: str) -> str:
    return _html.unescape(_TAG.sub(" ", s or "")).strip()


def parse_rss(xml_text: str) -> list[Post]:
    """Parse an RSS document into Posts. Never raises. Tolerates a leading UTF-8 BOM /
    whitespace (the Fed's monetary-policy feed ships a BOM that would otherwise break ET)."""
    posts: list[Post] = []
    xml_text = (xml_text or "").lstrip("﻿").lstrip()
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return posts
    for item in root.iter("item"):
        def field(tag: str) -> str:
            el = item.find(tag)
            return (el.text or "") if el is not None else ""
        title, desc, pub = field("title"), field("description"), field("pubDate")
        text = _strip_html(desc) or _strip_html(title)
        pid = field("guid") or field("link") or str(hash((title, pub)))
        url = field("link") or field("guid")
        iso = ""
        if pub:
            try:
                iso = parsedate_to_datetime(pub).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                iso = ""
        posts.append(Post(id=pid, text=text, url=url, published=iso))
    return posts


def fetch_rss(url: str = FEED_URL, ua: str = "reddit-signal-radar/0.1",
              retries: int = 3, sleep_s: float = 1.0) -> list[Post]:
    """Fetch + parse the feed with retry/backoff. Never raises; [] on failure."""
    for attempt in range(retries):
        try:
            r = requests.get(url, headers={"User-Agent": ua}, timeout=20)
            if r.status_code == 200:
                # decode as utf-8-sig so a BOM is stripped and the XML decl is honored
                return parse_rss(r.content.decode("utf-8-sig", "replace"))
            if r.status_code in (429, 500, 502, 503):
                time.sleep(sleep_s * (2 ** attempt)); continue
            return []
        except requests.RequestException:
            time.sleep(sleep_s * (2 ** attempt))
    return []


def load_watch_map(path) -> dict[str, str]:
    try:
        raw = yaml.safe_load(Path(path).read_text()) or {}
    except Exception:
        return {}
    return {str(k).lower(): str(v).upper() for k, v in raw.items()}


def detect_tickers(text: str, universe, watch_map: dict[str, str]) -> set[str]:
    """Only two trustworthy signals in Trump's prose: an explicit cashtag ($TSLA) and a
    curated company-name match (watch_map). We deliberately do NOT scan bare ALL-CAPS words
    against the universe — he writes in caps constantly, so common words like ICE (the
    agency) or MASS collide with real tickers and flood the alert with false positives. The
    surviving candidates are then semantically validated by DeepSeek in the monitor."""
    found: set[str] = set()
    for m in CASHTAG.finditer(text):
        tok = m.group(1).upper()
        if universe.is_symbol(tok):
            found.add(tok)
    low = text.lower()
    for name, ticker in watch_map.items():
        if re.search(r"\b" + re.escape(name) + r"\b", low):
            found.add(ticker)
    return found


def load_seen(path) -> list[str]:
    try:
        data = json.loads(Path(path).read_text())
        return list(data) if isinstance(data, list) else []
    except Exception:
        return []


def save_seen(path, seen, cap: int = 200) -> None:
    Path(path).write_text(json.dumps(list(seen)[-cap:]))


def find_new_alerts(posts, seen, universe, watch_map):
    """Return (alerts, new_seen). `posts` is newest-first. Only posts not previously
    seen AND mentioning a ticker become alerts; every evaluated post id is recorded
    in new_seen so we never re-alert (dedup)."""
    seen_set = set(seen)
    new_seen = list(seen)
    alerts = []
    for p in posts:
        if p.id in seen_set:
            continue
        seen_set.add(p.id)
        new_seen.append(p.id)
        tickers = detect_tickers(p.text, universe, watch_map)
        if tickers:
            alerts.append(dict(tickers=sorted(tickers), post=p.text, url=p.url,
                               published=p.published))
    return alerts, new_seen


def build_alert(alerts, detected_at_iso: str) -> dict:
    """The single most recent alert (posts are newest-first), stamped with detection time."""
    a = dict(alerts[0])
    a["detected_at"] = detected_at_iso
    return a


def write_alert_json(path, alert: dict) -> None:
    Path(path).write_text(json.dumps(alert))


def load_alert(path) -> dict | None:
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return None


def alert_is_fresh(alert: dict, now: float, max_age_h: int = 48) -> bool:
    ts = (alert or {}).get("detected_at") or (alert or {}).get("published")
    if not ts:
        return False
    try:
        dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except Exception:
        return False
    return (now - dt.timestamp()) <= max_age_h * 3600
