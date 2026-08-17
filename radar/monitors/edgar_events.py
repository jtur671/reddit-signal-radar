"""8-K material-event tripwire (structured). Full-text-searches EDGAR (efts.sec.gov,
free, UA-header etiquette) for high-salience 8-K phrases filed in the last day, and
alerts when the filer maps to a ticker the radar is actively tracking (recent
history.json activity — the data branch is overlaid on fleet ticks). Date-bounds every
query: the unbounded endpoint returns decade-old filings."""
from __future__ import annotations

import json
import re
import urllib.parse
from datetime import date, timedelta
from pathlib import Path

from radar.monitors.base import Signal
from radar.monitors.edgar import _http_get

EFTS = ("https://efts.sec.gov/LATEST/search-index?q={q}&forms=8-K"
        "&dateRange=custom&startdt={start}&enddt={end}")
_DISPLAY_TICKER = re.compile(
    r"\(([A-Z][A-Z0-9.\-]{0,9})(?:,\s*[A-Z][A-Z0-9.\-]{0,9})*\)\s*\(CIK")


def ticker_from_display(display: str) -> str:
    """EDGAR display_names embed the ticker: 'Acme Corp  (ACME)  (CIK 0001...)'."""
    m = _DISPLAY_TICKER.search(display or "")
    return m.group(1) if m else ""


def _fetch_json(url: str, ua: str):
    text = _http_get(url, ua)
    try:
        return json.loads(text) if text else None
    except ValueError:
        return None


def parse_hits(raw) -> list[dict]:
    """EFTS response -> [{id, ticker, display, file_date, url}]. Pure, never raises."""
    out: list[dict] = []
    try:
        hits = raw["hits"]["hits"]
    except (TypeError, KeyError):
        return out
    for h in hits or []:
        if not isinstance(h, dict):
            continue
        src = h.get("_source") or {}
        display = (src.get("display_names") or [""])[0]
        acc = str(h.get("_id") or "")
        acc_no, _, fname = acc.partition(":")
        cik = str((src.get("ciks") or [""])[0]).lstrip("0")
        url = (f"https://www.sec.gov/Archives/edgar/data/{cik}/"
               f"{acc_no.replace('-', '')}/{fname}"
               if cik and acc_no and fname
               else "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&type=8-K")
        out.append({
            "id": acc_no,                    # accession, NOT acc_no:fname -- EFTS indexes
                                             # every file in a submission separately
            "ticker": ticker_from_display(display),
            "display": display,
            "file_date": str(src.get("file_date") or ""),
            "url": url,
        })
    return out


def active_tickers(history_path: str = "data/history.json", days: int = 7,
                   today: str | None = None) -> set[str]:
    """Tickers with any history activity in the trailing window — the monitor's
    watch-set. Empty set (never an exception) when history is missing/corrupt."""
    try:
        data = json.loads(Path(history_path).read_text())
    except (OSError, ValueError):
        return set()
    if not isinstance(data, dict):
        return set()
    t = date.fromisoformat(today) if today else date.today()
    cutoff = (t - timedelta(days=days)).isoformat()
    return {tick for tick, d in data.items()
            if isinstance(d, dict) and any(day >= cutoff for day in d)}


class EdgarEventsMonitor:
    """Fleet monitor #5 — see radar.monitors.base.Monitor for the contract."""
    def __init__(self, phrases: list[str], user_agent: str,
                 watch=active_tickers, max_age_h: int = 24):
        self.key, self.label, self.card_style = "edgar8k", "📢 8-K Event", "insider"
        self.direction = "neutral"
        self.max_age_h = max_age_h
        self.phrases = list(phrases)
        self.user_agent = user_agent
        self._watch = watch
        # Three phrases over the rolling window can exceed the base.py default seen_cap
        # of 200 (one phrase alone returned 72 in-window ids) -> evicted ids re-evaluate
        # every tick (cursor churn + duplicate alerts). Match EdgarMonitor's 5000.
        self.seen_cap = 5000

    def fetch_new(self, seen: set[str]):
        # Cursors written before the accession-dedup change hold "<accession>:<filename>".
        # Normalise so the first tick after deploy does not re-alert on seen filings.
        seen = {str(s).partition(":")[0] for s in seen}
        watch = self._watch() if callable(self._watch) else set(self._watch)
        end = date.today().isoformat()
        start = (date.today() - timedelta(days=1)).isoformat()
        signals, evaluated = [], []
        for phrase in self.phrases:
            q = urllib.parse.quote(f'"{phrase}"', safe="")
            raw = _fetch_json(EFTS.format(q=q, start=start, end=end), self.user_agent)
            for row in parse_hits(raw):
                if row["id"] in seen or row["id"] in evaluated:
                    continue
                evaluated.append(row["id"])
                if row["ticker"] and row["ticker"] in watch:
                    signals.append(Signal(
                        tickers=[row["ticker"]],
                        summary=f"8-K “{phrase}” filed by {row['display']}",
                        url=row["url"], published=row["file_date"] + "T00:00:00Z",
                        monitor_key=self.key, link_text="EDGAR filing ↗"))
        return signals, evaluated

    def validate(self, signals):
        return signals
