"""Fleet monitor — the ~30-min GitHub Actions entrypoint.

Runs every monitor in the registry (Trump prose tripwire + EDGAR insider-buy tripwire, …):
each fetches its source, dedups against its own cursor, and on a NEW hit writes
data/<key>_alert.json and emails. If ANY monitor fired, signals the workflow
(alert=true) to rebuild + deploy the dashboard with the alert card(s)."""
from __future__ import annotations

import os
import sys

from radar.dotenv import load_env
from radar import clock
from radar.config import load_config
from radar.monitors import build_registry
from radar.monitors import base
from radar.monitors.base import run_fleet
from radar.email_report import send_monitor_alert


def _set_output(key: str, val: str) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"{key}={val}\n")


def _email(monitor, signal) -> None:
    """Best-effort email per fired alert — never crash the run."""
    try:
        alert = dict(label=monitor.label, tickers=signal.tickers, summary=signal.summary,
                     url=signal.url, published=signal.published, link_text=signal.link_text)
        if not send_monitor_alert(alert):
            print(f"EMAIL: {monitor.key} alert not sent — RESEND_API_KEY/EMAIL_RECIPIENTS missing",
                  file=sys.stderr)
    except Exception as e:
        print(f"EMAIL: {monitor.key} alert send failed — {e!r}", file=sys.stderr)


def main(argv=None) -> int:
    load_env()                                          # local .env (no-op in CI; env wins)
    cfg = load_config("config.yaml")
    monitors = build_registry(cfg)
    fired = run_fleet(monitors, now_iso=clock.now_iso_utc(), on_alert=_email)
    _set_output("alert", "true" if fired else "false")
    print("FLEET: alert(s) fired" if fired else "FLEET: no new alerts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
