"""Event-tripwire monitor: watch an RSS feed where every NEW item is itself the signal.

Unlike ProseMonitor (which infers a ticker from the text), an event feed names no company —
each new release is the event, tagged with a FIXED macro ticker set. Used for institutional
feeds like the Fed's monetary-policy releases, which move whole-market names (SPY/TLT/…)
rather than a single stock. Reuses radar/trump.py's RSS parsing; no LLM, no ticker inference.
"""
from __future__ import annotations

from radar import trump
from radar.monitors.base import Signal


class RssEventMonitor:
    def __init__(self, *, key: str, label: str, feed_url: str, tickers, card_style: str,
                 link_text: str = "", max_age_h: int = 72):
        self.key = key
        self.label = label
        self.feed_url = feed_url
        self.tickers = list(tickers)
        self.card_style = card_style
        self.link_text = link_text
        self.max_age_h = max_age_h

    def fetch_new(self, seen):
        posts = trump.fetch_rss(self.feed_url)               # newest-first; never raises
        signals, evaluated = [], []
        for p in posts:
            evaluated.append(p.id)
            if p.id in seen:
                continue
            summary = (p.text or "").strip()
            if not summary:                                  # skip empty items
                continue
            signals.append(Signal(tickers=list(self.tickers), summary=summary, url=p.url,
                                  published=p.published, monitor_key=self.key,
                                  link_text=self.link_text))
        return signals, evaluated                            # newest-first == most-salient-first

    def validate(self, signals):
        return signals                                       # every new item is a real event
