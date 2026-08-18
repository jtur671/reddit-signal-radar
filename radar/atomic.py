"""Atomic file writes for the vendored snapshots on the orphan `data` branch.

Every snapshot writer in this package used a bare `Path.write_text`, which is
truncate-then-write: a reader that arrives mid-write sees a half-file. Measured
2026-08-18 with one writer and one reader thread over two seconds --
`tickermap._snapshot_map` 87% torn reads, `short_interest._read_snapshot` 83%,
`about.load_cache` 96%.

A torn file always fails `json.loads`, so no reader ever gets a *wrong* answer --
but it does lose its fallback, and for `about.json` the next `save_cache`
overwrites 400+ accumulated entries with the ~15 names on today's board.

`os.replace` is atomic on POSIX, so a reader sees the old file or the new one and
never a partial. The temp file sits in the same directory because `os.replace`
is only atomic within a filesystem.
"""
from __future__ import annotations

import os
from pathlib import Path


def write_text(path, text: str) -> None:
    """Write `text` to `path` atomically. Raises like a normal write on failure --
    callers own their own fail-soft policy, and swallowing here would hide a full
    disk from the `degrade.warn` breadcrumb that is supposed to report it."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    try:
        tmp.write_text(text)
        os.replace(tmp, p)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
