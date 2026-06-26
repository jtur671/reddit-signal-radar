# radar/monitors/base.py
"""Monitor fleet core: the Signal/Monitor contract and the shared run_fleet() runner.

Every monitor — prose (infer ticker from text) or structured (ticker is a field) —
flows through identical dedup-cursor / alert-file / validation / email plumbing here.
Generic cursor + freshness helpers are reused from radar.trump (already source-agnostic)
rather than duplicated.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

from radar.trump import load_seen, save_seen, alert_is_fresh  # generic, reused


@dataclass
class Signal:
    tickers: list[str]
    summary: str                 # one-line human text (prose: the post; structured: filing facts)
    url: str
    published: str               # ISO-8601 'Z'
    monitor_key: str
    link_text: str = ""          # dashboard/email link label, e.g. "Truth Social post ↗"


class Monitor(Protocol):
    key: str                     # namespaces data files: data/<key>_seen.json / _alert.json
    label: str                   # card/email title
    card_style: str              # dashboard card variant
    max_age_h: int               # freshness window for the dashboard card

    def fetch_new(self, seen: set[str]) -> tuple[list[Signal], list[str]]:
        """Fetch source, skip ids in `seen`. Return (new signals most-salient-first,
        ALL evaluated source ids — so rejected/no-hit records still advance the cursor)."""

    def validate(self, signals: list[Signal]) -> list[Signal]:
        """Optional semantic gate. Default identity; ProseMonitor overrides with DeepSeek."""


def alert_path(key: str, data_dir: str = "data") -> str:
    return str(Path(data_dir) / f"{key}_alert.json")


def seen_path(key: str, data_dir: str = "data") -> str:
    return str(Path(data_dir) / f"{key}_seen.json")


def write_alert(monitor, signal: Signal, detected_at_iso: str, data_dir: str = "data") -> None:
    """Write a SELF-DESCRIBING alert file so the dashboard can render it without the registry."""
    alert = dict(
        monitor_key=monitor.key, label=monitor.label, card_style=monitor.card_style,
        link_text=signal.link_text, tickers=signal.tickers, summary=signal.summary,
        url=signal.url, published=signal.published, detected_at=detected_at_iso,
    )
    Path(alert_path(monitor.key, data_dir)).write_text(json.dumps(alert))


def run_fleet(monitors, *, now_iso: str, on_alert: Callable | None = None,
              data_dir: str = "data") -> bool:
    """Run every monitor: load cursor -> fetch_new -> save cursor (only if changed) ->
    validate -> write the single most-salient surviving alert -> on_alert hook.
    Returns True if ANY monitor fired (drives the workflow's conditional rebuild)."""
    any_fired = False
    for m in monitors:
        seen = load_seen(seen_path(m.key, data_dir))
        signals, evaluated = m.fetch_new(set(seen))

        seen_set = set(seen)
        new_seen = list(seen) + [i for i in evaluated if i not in seen_set]
        if new_seen != seen:
            save_seen(seen_path(m.key, data_dir), new_seen)

        signals = m.validate(signals)          # fail-open lives inside the monitor's validate
        if not signals:
            continue
        salient = signals[0]                    # monitors return most-salient-first
        write_alert(m, salient, now_iso, data_dir)
        any_fired = True
        if on_alert:
            on_alert(m, salient)
    return any_fired
