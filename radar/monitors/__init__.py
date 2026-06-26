# radar/monitors/__init__.py
"""The monitor fleet registry. build_registry(cfg) returns the live monitors the
fleet-monitor workflow runs each tick. Adding a monitor = appending one instance here
(prose monitors are ~a config row; structured monitors get an adapter class)."""
from __future__ import annotations

from radar.monitors.prose import ProseMonitor
from radar.monitors.edgar import EdgarMonitor


def build_registry(cfg) -> list:
    ec = cfg.edgar
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
    ]
