"""Trump Truth Social monitor — the ~30-min GitHub Actions entrypoint.

Fetches the trumpstruth.org feed, detects new ticker/company mentions, and on a NEW
pump: writes data/trump_alert.json, emails immediately, and signals the workflow
(via $GITHUB_OUTPUT alert=true) to rebuild + deploy the dashboard. The dedup cursor
(data/trump_seen.json) is saved only when it changes, so no-op runs don't churn git.
"""
from __future__ import annotations

import os
import sys

from radar.dotenv import load_env
from radar import clock, trump
from radar.config import load_config
from radar.universe import Universe
from radar.email_report import send_trump_alert
from radar.sentiment import validate_trump_tickers

ALERT_PATH = "data/trump_alert.json"
SEEN_PATH = "data/trump_seen.json"
WATCH_PATH = "data/trump_watch.yaml"
UNIVERSE_PATH = "data/universe.txt"
STOPLIST_PATH = "data/stoplist.txt"


def _set_output(key: str, val: str) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"{key}={val}\n")


def _validate(alerts, watch):
    """Run each candidate alert's tickers through the DeepSeek semantic gate and keep only
    confirmed ones; alerts left with no surviving ticker are dropped. The dedup cursor is
    already saved upstream, so a dropped post is recorded and never re-evaluated. DeepSeek
    failure fails open (keeps the candidates), so an LLM outage never suppresses a real pump."""
    inv = {v: k for k, v in watch.items()}              # ticker -> curated company name
    kept = []
    for a in alerts:
        cands = [dict(ticker=t, name=inv.get(t, t)) for t in a["tickers"]]
        confirmed = validate_trump_tickers(a["post"], cands)
        if confirmed:
            kept.append({**a, "tickers": sorted(confirmed)})
    return kept


def main(argv=None) -> int:
    load_env()                                          # local .env (no-op in CI; env wins)
    cfg = load_config("config.yaml")
    ua = getattr(getattr(cfg, "apewisdom", None), "user_agent", "reddit-signal-radar/0.1")
    universe = Universe.load(UNIVERSE_PATH, STOPLIST_PATH)
    watch = trump.load_watch_map(WATCH_PATH)
    seen = trump.load_seen(SEEN_PATH)

    posts = trump.fetch_rss(trump.FEED_URL, ua)
    alerts, new_seen = trump.find_new_alerts(posts, seen, universe, watch)

    if new_seen != seen:
        trump.save_seen(SEEN_PATH, new_seen)

    alerts = _validate(alerts, watch)                   # DeepSeek semantic gate on candidates

    if alerts:
        alert = trump.build_alert(alerts, clock.now_iso_utc())
        trump.write_alert_json(ALERT_PATH, alert)
        try:
            send_trump_alert(alert)                     # best-effort; never crash the run
        except Exception:
            pass
        _set_output("alert", "true")
        print(f"TRUMP ALERT: {alert['tickers']} — {alert['post'][:80]}")
    else:
        _set_output("alert", "false")
        print("no new trump pump")
    return 0


if __name__ == "__main__":
    sys.exit(main())
