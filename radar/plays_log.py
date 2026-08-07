"""Append-only log of Early Plays picks — the radar's track record (data-branch state).

Each daily run appends that day's recommend_buys output; nothing is ever rewritten,
so the scorecard/backtest can grade every pick the radar ever made. Dedupe key is
(date, ticker). Corrupt/missing files start fresh rather than crash (fail-soft, but
append_picks may raise on write errors — the caller wraps it in degrade.warn)."""
from __future__ import annotations

import json
from pathlib import Path


def load_picks(path) -> list[dict]:
    """The full pick log, oldest first. [] on missing/corrupt file."""
    p = Path(path)
    try:
        data = json.loads(p.read_text())
        picks = data.get("picks", [])
        return picks if isinstance(picks, list) else []
    except (OSError, ValueError):
        return []


def append_picks(path, run_day: str, picks: list[dict], board_by_ticker: dict) -> int:
    """Append today's picks (deduped on (date, ticker)); returns how many were new.
    `board_by_ticker` maps ticker -> Signal so each entry snapshots the board metrics
    that justified the pick (mentions / vel_24h / state)."""
    existing = load_picks(path)
    seen = {(r.get("date"), r.get("ticker")) for r in existing}
    added = 0
    for pk in picks:
        t = str(pk.get("ticker") or "").upper()
        if not t or (run_day, t) in seen:
            continue
        s = board_by_ticker.get(t)
        existing.append({
            "date": run_day, "ticker": t,
            "thesis": str(pk.get("thesis") or ""), "risk": str(pk.get("risk") or ""),
            "conviction": str(pk.get("conviction") or ""),
            "mentions": getattr(s, "mentions", 0) if s else 0,
            "vel": getattr(s, "vel_24h", None) if s else None,
            "state": getattr(s, "state", "") if s else ""})
        seen.add((run_day, t)); added += 1
    existing.sort(key=lambda r: (r.get("date", ""), r.get("ticker", "")))
    Path(path).write_text(json.dumps({"picks": existing}, indent=0))
    return added
