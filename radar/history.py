from __future__ import annotations
import json, statistics
from pathlib import Path
from datetime import date

from radar import degrade

class History:
    """Per-ticker per-day record. Stored as {ticker: {date: {...}}}. Implements INV-2/INV-6."""
    def __init__(self, path: Path, data: dict):
        self.path, self.data = path, data

    @classmethod
    def load(cls, path) -> "History":
        """Never raises. An unreadable history warns and starts empty.

        This was the only production-state reader in the package that failed HARD --
        a bare `json.loads(p.read_text())` -- while the snapshot readers beside it
        (tickermap._snapshot_map, short_interest._read_snapshot) warned and returned
        nothing. That asymmetry is a live tripwire, not a style nit: `save()` is a bare
        truncate-then-write, so ONE interrupted daily job leaves a torn file, and a torn
        file then killed every subsequent run -- no board, no email, no data-branch
        commit -- until a human hand-edited the data branch.

        The `except` catches ValueError as well as OSError, and BOTH halves are load
        bearing. `read_text()` on a file carrying a non-UTF-8 byte raises
        UnicodeDecodeError, which is a ValueError and not an OSError -- so it escaped
        this clause exactly the way the bare `json.loads` escaped everything, with the
        same permanence: data/history.json rides the orphan data branch and daily.yml
        restores it before EVERY run. Same defect, same call, already fixed in
        short_interest._read_snapshot (9d5f3c6). about.load_cache carried it too and was
        fixed alongside this one; an earlier version of this docstring claimed that
        reader already warned, which was false when it was written.

        Empty is safer than crashing at all three consumers, traced rather than assumed:
          * score._finalize -> baseline() returns (0.0, 0.0) -> the documented
            brand-new / INV-8 path, which is exactly what a genuine day-1 cold start
            already produces. The board publishes, every name reading as new.
          * still_running -> days_for() returns {} -> the lane is empty for a day.
            Degraded, not wrong.
          * backtest.run_backtest -> no `all_days` -> {"error": "no history"} ->
            main() returns 1, so the weekly workflow fails BEFORE its
            `cp -f out/backtest.json`, and the last good artifact on the data branch
            is never clobbered. Same visible outcome as the crash, plus a reason.

        The corrupt content itself is unrecoverable by definition -- it did not parse --
        and every previous day's copy is still on the data branch's commit history.

        ONE read, not two: the old body called `read_text()` for the `.strip()` test and
        again for `json.loads`, and against a file another process is mid-write on those
        two reads can disagree. Missing and empty stay SILENT: day 1 has no file and a
        fresh data branch holds an empty one, and a warn that fires every cold start is
        the noise that gets the real one ignored."""
        p = Path(path)
        try:
            text = p.read_text()
        except FileNotFoundError:
            return cls(p, {})                       # cold start; not a degradation
        except (OSError, ValueError) as e:          # permissions, I/O, a directory,
            degrade.warn("history unreadable", e)   # or a byte that is not UTF-8
            return cls(p, {})
        if not text.strip():
            return cls(p, {})                       # a fresh data branch; not a degradation
        try:
            data = json.loads(text)
        except ValueError as e:
            degrade.warn("history unreadable",
                         f"{p} is not valid JSON ({e}) — starting from an empty baseline")
            return cls(p, {})
        if not isinstance(data, dict):
            # Valid JSON is not enough. A top-level list or string parses cleanly and
            # detonates later inside the scoring loop at `self.data.get(...)`, past every
            # fail-soft boundary. Same door-check as tickermap._snapshot_map.
            degrade.warn("history unreadable",
                         f"{p} holds {type(data).__name__}, not an object — "
                         f"starting from an empty baseline")
            return cls(p, {})
        return cls(p, data)

    def days_for(self, ticker: str) -> dict:
        return self.data.get(ticker, {})

    def record(self, day, ticker, weighted, raw, authors, pct_bull, score, state):
        self.data.setdefault(ticker, {})[day] = {
            "weighted": weighted, "raw": raw, "authors": authors,
            "pct_bull": pct_bull, "score": score, "state": state}

    def annotate(self, day: str, ticker: str, **fields) -> bool:
        """Merge extra keys (e.g. ts_bull) into an EXISTING day-record. Never creates
        a record: baseline() requires 'weighted' in every day-record, so a ticker not
        scored today simply drops its annotation. Returns whether it merged."""
        rec = self.data.get(ticker, {}).get(day)
        if rec is None:
            return False
        rec.update(fields)
        return True

    def baseline(self, ticker, before: str, days: int, alpha: float) -> tuple[float, float]:
        """EMA mean + population std of weighted counts in the trailing `days`-day
        window STRICTLY before `before`.

        Silent days (no record) are folded in as 0.0, starting from the ticker's
        FIRST in-window appearance, so a ticker that spiked once and then went quiet
        sees its baseline DECAY toward zero day by day. A later resurgence then reads
        as a genuine surprise instead of being suppressed against a stale peak
        (INV-1/INV-6) -- without this, a one-time spike would freeze the baseline for
        the full window and bury real comebacks as 'cooling'. Brand-new tickers are
        not penalised: zero-fill begins at their first appearance, not the window
        edge. An ancient spike outside the trailing window is excluded entirely, so
        the 90-day window is enforced here, not only by the on-disk prune."""
        hist = self.days_for(ticker)
        before_ord = date.fromisoformat(before).toordinal()
        cutoff = before_ord - days
        present = {date.fromisoformat(d).toordinal(): hist[d]["weighted"]
                   for d in hist
                   if cutoff <= date.fromisoformat(d).toordinal() < before_ord}
        if not present:
            return (0.0, 0.0)
        start = min(present)                       # first in-window appearance
        vals = [present.get(o, 0.0) for o in range(start, before_ord)]
        ema = vals[0]
        for v in vals[1:]:
            ema = alpha * v + (1 - alpha) * ema
        std = statistics.pstdev(vals) if len(vals) > 1 else 0.0
        return (float(ema), float(std))

    def prune(self, keep_through: str, days: int):
        cutoff = (date.fromisoformat(keep_through).toordinal() - days)
        for ticker in list(self.data):
            self.data[ticker] = {d: v for d, v in self.data[ticker].items()
                                 if date.fromisoformat(d).toordinal() >= cutoff}
            if not self.data[ticker]:
                del self.data[ticker]

    def save(self):
        self.path.write_text(json.dumps(self.data, indent=0, sort_keys=True))
