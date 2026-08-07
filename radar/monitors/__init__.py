# radar/monitors/__init__.py
"""The monitor fleet registry. build_registry(cfg) returns the live monitors the
fleet-monitor workflow runs each tick. Adding a monitor = appending one instance here
(prose monitors are ~a config row; structured monitors get an adapter class)."""
from __future__ import annotations

from radar.monitors.prose import ProseMonitor
from radar.monitors.edgar import EdgarMonitor
from radar.monitors.events import RssEventMonitor
from radar.monitors.congress import CongressMonitor
from radar.monitors.edgar_events import EdgarEventsMonitor


def build_registry(cfg) -> list:
    ec = cfg.edgar
    fc = cfg.fed
    cc = cfg.congress
    ev = cfg.edgar_events
    return [
        ProseMonitor(
            key="trump", label="⚠ Trump Alert", card_style="trump",
            feed_url="https://www.trumpstruth.org/feed",
            watch_map_path="data/trump_watch.yaml",
            source_context="A Truth Social post by Donald Trump",
            link_text="Truth Social post ↗", max_age_h=48,
        ),
        EdgarMonitor(
            key="edgar", label="📄 Insider Buy", card_style="insider",
            transaction_codes=list(ec.transaction_codes), min_usd=ec.min_usd,
            max_age_h=ec.max_age_h, user_agent=ec.user_agent,
        ),
        RssEventMonitor(
            key="fed", label="🏛 Fed / FOMC", card_style="fed",
            feed_url=fc.feed_url, tickers=list(fc.tickers),
            link_text="Fed release ↗", max_age_h=fc.max_age_h,
        ),
        CongressMonitor(
            key="congress", label="🏛 Congress Buy", card_style="congress",
            feed_url=cc.feed_url, watch_path=cc.watch_path, min_usd=cc.min_usd,
            max_records=cc.max_records, max_age_h=cc.max_age_h,
        ),
        EdgarEventsMonitor(
            phrases=list(ev.phrases), user_agent=ev.user_agent, max_age_h=ev.max_age_h,
        ),
    ]
