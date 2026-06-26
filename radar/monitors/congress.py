"""Congressional-trade monitor (structured). Polls a free, no-auth JSON feed of US Congress
STOCK Act disclosures (kadoa-org/congress-trading-monitor — House + Senate, refreshed several
times daily) and alerts on PURCHASES that are EITHER by a curated notable member
(data/congress_watch.yaml) OR above a large dollar floor. The ticker is a field — no PDF
parsing, no LLM.

Caveat baked into the law: disclosures lag the actual trade by up to 45 days (STOCK Act), so
this is a slower signal than the prose/Fed monitors. This is a radar, not a trader — it
notifies; it never places an order.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import yaml

from radar.monitors.base import Signal
from radar.monitors.edgar import _http_get, _NO_TICKER

FEED_URL = ("https://raw.githubusercontent.com/kadoa-org/congress-trading-monitor/"
            "main/public/data/trades.json")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def load_watch(path) -> set[str]:
    """Curated notable members -> a set of SURNAMES (last name token). Surname matching is
    robust to first-name variants in the feed (e.g. 'Dan' vs 'Daniel Crenshaw'); the curated
    names are distinctive enough that collisions are unlikely."""
    try:
        raw = yaml.safe_load(Path(path).read_text()) or []
    except Exception:
        return set()
    out = set()
    for x in raw:
        toks = _norm(x).split()
        if toks:
            out.add(toks[-1])
    return out


def _norm(name) -> str:
    """Lowercase, keep only alphanumerics/space, collapse — robust to commas/suffixes."""
    s = "".join(c for c in str(name or "").lower() if c.isalnum() or c.isspace())
    return " ".join(s.split())


def _date_to_iso(d: str) -> str:
    d = (d or "").strip()
    return f"{d}T00:00:00Z" if _DATE.match(d) else ""


class CongressMonitor:
    def __init__(self, *, watch_path: str, min_usd: float, key: str = "congress",
                 label: str = "🏛 Congress Buy", card_style: str = "congress",
                 feed_url: str = FEED_URL, user_agent: str = "reddit-signal-radar/0.1",
                 max_records: int = 200, max_age_h: int = 72, seen_cap: int = 5000):
        self.key = key
        self.label = label
        self.card_style = card_style
        self.feed_url = feed_url
        self.user_agent = user_agent
        self.min_usd = float(min_usd)
        self.max_records = max_records
        self.max_age_h = max_age_h
        self.seen_cap = seen_cap
        self.watch = load_watch(watch_path)

    def _is_notable(self, filer_name) -> bool:
        return bool(self.watch & set(_norm(filer_name).split()))

    def fetch_new(self, seen):
        debug = os.environ.get("CONGRESS_DEBUG", "").strip().lower() in ("1", "true", "yes")
        try:
            records = json.loads(_http_get(self.feed_url, self.user_agent))
        except Exception:
            records = []
        if not isinstance(records, list):
            records = []
        records = records[: self.max_records]            # feed is newest-filing-first
        buys, evaluated = [], []
        n_purchase = n_qualify = 0
        for r in records:
            rid = r.get("id")
            if not rid:
                continue
            evaluated.append(rid)
            if rid in seen:
                continue
            if "urchase" not in (r.get("transaction_type") or ""):   # purchases only
                continue
            n_purchase += 1
            ticker = (r.get("ticker") or "").strip().upper()
            if ticker in _NO_TICKER:                     # skip no-ticker / non-equity rows
                continue
            low = float(r.get("amount_range_low") or 0)
            notable = self._is_notable(r.get("filer_name"))
            if not notable and low < self.min_usd:       # alert if notable OR big
                continue
            n_qualify += 1
            member = (r.get("filer_name") or "").strip().rstrip(",")
            ps = "-".join(p for p in (r.get("party"), r.get("state")) if p)
            who = f"{member} ({ps})" if ps else member
            summary = (f"Congress buy — {who} bought ${ticker} "
                       f"({r.get('amount_range_label') or '?'})")
            if debug:
                print(f"CONGRESS: {'★' if notable else ' '} {member} {ticker} "
                      f"{r.get('amount_range_label')} ({r.get('filing_date')})", file=sys.stderr)
            buys.append(((1 if notable else 0, low),      # notable first, then largest $
                         Signal(tickers=[ticker], summary=summary, url=r.get("doc_url", ""),
                                published=_date_to_iso(r.get("filing_date")),
                                monitor_key=self.key, link_text="View disclosure ↗")))
        buys.sort(key=lambda t: t[0], reverse=True)       # most-salient-first
        print(f"CONGRESS: examined {len(records)} disclosures "
              f"(purchases {n_purchase}, qualifying {n_qualify})", file=sys.stderr)
        return [s for _, s in buys], evaluated

    def validate(self, signals):
        return signals                                    # structured: no LLM gate
