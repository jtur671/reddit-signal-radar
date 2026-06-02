"""Minimal, dependency-free .env loader.

Local runs keep secrets in a gitignored .env; production sets them as real environment
variables (GitHub repo secrets). We use setdefault so anything already in the environment
ALWAYS wins — CI never gets shadowed by a stray .env, and `op`/shell exports still work.
"""
from __future__ import annotations

import os
from pathlib import Path


def load_env(path: str = ".env") -> None:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, val)            # never override an existing value
