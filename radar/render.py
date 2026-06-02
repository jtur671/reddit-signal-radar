from __future__ import annotations
from pathlib import Path
import json
from jinja2 import Environment, FileSystemLoader, select_autoescape

_TPL_DIR = Path(__file__).parent / "templates"
_env = Environment(loader=FileSystemLoader(_TPL_DIR),
                   autoescape=select_autoescape(["html", "j2"]))   # XSS-safe by default

def render_html(**ctx) -> str:
    return _env.get_template("dashboard.html.j2").render(**ctx)

def write_outputs(html: str, data: dict, out_dir="out"):
    out = Path(out_dir); out.mkdir(exist_ok=True)
    (out / "index.html").write_text(html)
    (out / "data.json").write_text(json.dumps(data))
