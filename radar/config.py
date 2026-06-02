from __future__ import annotations
import yaml
from types import SimpleNamespace
from pathlib import Path

def _ns(d):
    if isinstance(d, dict):
        return SimpleNamespace(**{k: _ns(v) for k, v in d.items()})
    return d

def load_config(path="config.yaml"):
    return _ns(yaml.safe_load(Path(path).read_text()))
