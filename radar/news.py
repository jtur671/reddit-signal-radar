"""Per-ticker news catalyst — the 'why is there chatter' source.

ApeWisdom gives mention counts but no post text, and Reddit's own JSON 403s cloud/CI IPs,
so the summary had nothing real to explain a spike. We pull recent headlines from Google
News' free, no-auth, cloud-friendly RSS search (the same RSS approach the Trump monitor
uses) and let DeepSeek turn them into the one-line reason a ticker is trending.

Pure parsing here; the network fetch never raises and returns [] on any failure.
"""
from __future__ import annotations

import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests

from radar.degrade import warn

GNEWS = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"


def build_query(ticker: str, name: str = "") -> str:
    """A focused Google News query for a ticker, disambiguated by company name when we have
    one (so 'ICE'/'MASS'-style words pull the company, not the dictionary word)."""
    parts = [f'"{ticker}"']
    if name and name.lower() not in ticker.lower():
        parts.append(f'"{name}"')
    return urllib.parse.quote("(" + " OR ".join(parts) + ") stock", safe="")


def parse_news(xml_text: str, now: datetime | None = None,
               max_items: int = 6, max_age_days: int = 10) -> list[str]:
    """Extract recent headline titles from a Google News RSS document. Drops items older than
    max_age_days (a stale earnings headline shouldn't 'explain' a meme spike). Never raises."""
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return []
    now = now or datetime.now(timezone.utc)
    out: list[str] = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        pub = item.findtext("pubDate") or ""
        if max_age_days and pub:
            try:
                age = (now - parsedate_to_datetime(pub)).days
                if age > max_age_days:
                    continue
            except Exception:
                pass                                    # unparseable date -> keep, don't guess
        out.append(title)
        if len(out) >= max_items:
            break
    return out


def headlines(ticker: str, name: str = "", ua: str = "reddit-signal-radar/0.1",
              retries: int = 2, sleep_s: float = 1.0) -> list[str]:
    """Recent news headlines for a ticker via Google News RSS. Never raises; [] on failure."""
    url = GNEWS.format(q=build_query(ticker, name))
    last = ""
    for attempt in range(retries):
        try:
            r = requests.get(url, headers={"User-Agent": ua}, timeout=15)
            if r.status_code == 200:
                return parse_news(r.text)
            last = f"HTTP {r.status_code}"
            if r.status_code in (429, 500, 502, 503):
                time.sleep(sleep_s * (2 ** attempt)); continue
            break
        except requests.RequestException as e:
            last = repr(e)
            time.sleep(sleep_s * (2 ** attempt))
    warn(f"news {ticker}", last)      # no headlines -> no catalyst summary for this ticker
    return []
