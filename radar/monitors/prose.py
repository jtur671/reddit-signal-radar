# radar/monitors/prose.py
"""Prose monitor: an RSS source whose ticker must be INFERRED from free text (cashtag +
curated name map) and then confirmed by the DeepSeek semantic gate. Trump is one instance;
Fed / Musk later are new instances with different (feed_url, watch_map_path, source_context).
Wraps the existing radar/trump.py parsing/detection — no detection logic is duplicated."""
from __future__ import annotations

from radar import trump
from radar.universe import Universe
from radar.sentiment import validate_prose_tickers
from radar.monitors.base import Signal


class ProseMonitor:
    def __init__(self, *, key: str, label: str, feed_url: str, watch_map_path: str,
                 card_style: str, source_context: str, link_text: str = "",
                 universe_path: str = "data/universe.txt",
                 stoplist_path: str = "data/stoplist.txt", max_age_h: int = 48,
                 direction: str = "neutral"):
        self.key = key
        self.label = label
        self.feed_url = feed_url
        self.watch_map_path = watch_map_path
        self.card_style = card_style
        self.source_context = source_context
        self.link_text = link_text
        self.universe_path = universe_path
        self.stoplist_path = stoplist_path
        self.max_age_h = max_age_h
        self.direction = direction
        self._watch = trump.load_watch_map(watch_map_path)
        self._inv = {v: k for k, v in self._watch.items()}   # ticker -> curated name

    def fetch_new(self, seen):
        universe = Universe.load(self.universe_path, self.stoplist_path)
        posts = trump.fetch_rss(self.feed_url)               # newest-first; never raises
        signals, evaluated = [], []
        for p in posts:
            evaluated.append(p.id)
            if p.id in seen:
                continue
            tickers = trump.detect_tickers(p.text, universe, self._watch)
            if tickers:
                signals.append(Signal(tickers=sorted(tickers), summary=p.text, url=p.url,
                                      published=p.published, monitor_key=self.key,
                                      link_text=self.link_text))
        return signals, evaluated                            # newest-first == most-salient-first

    def validate(self, signals):
        kept = []
        for s in signals:
            cands = [dict(ticker=t, name=self._inv.get(t, t)) for t in s.tickers]
            confirmed = validate_prose_tickers(s.summary, cands, self.source_context)
            if confirmed:
                kept.append(Signal(tickers=sorted(confirmed), summary=s.summary, url=s.url,
                                   published=s.published, monitor_key=s.monitor_key,
                                   link_text=s.link_text))
        return kept
