# scripts/gen_universe.py
"""Generate data/universe.txt.

Fetches the listed equity symbols from NasdaqTrader, then ALWAYS unions in
(a) a fixed crypto list, (b) every theme seed parsed from data/themes.yaml,
and (c) KEEL. The network fetch is wrapped in try/except so that the script
produces a valid universe.txt even when the NasdaqTrader endpoints are
unreachable (offline fallback).
"""
import os
import re

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
THEMES_PATH = os.path.join(ROOT, "data", "themes.yaml")
OUT_PATH = os.path.join(ROOT, "data", "universe.txt")

CRYPTO = [
    "BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT", "MATIC",
    "LTC", "BCH", "ATOM", "UNI", "ETC", "XLM", "ALGO", "NEAR", "APT", "ARB",
    "OP", "SHIB", "PEPE", "SUI", "TIA",
]

URLS = [
    "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
    "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt",
]


def fetch_listed_symbols():
    """Return set of listed equity symbols from NasdaqTrader, or empty on failure."""
    out = set()
    if requests is None:
        return out
    for url in URLS:
        try:
            txt = requests.get(url, timeout=30).text.splitlines()
            for line in txt[1:-1]:
                sym = line.split("|")[0].strip().upper()
                if sym.isalpha() and 1 <= len(sym) <= 5:
                    out.add(sym)
        except Exception as exc:  # noqa: BLE001
            print(f"WARN: fetch failed for {url}: {exc}")
    return out


def parse_theme_seeds(path):
    """Parse seed tickers from themes.yaml.

    Uses PyYAML when available, otherwise a small regex fallback so the script
    never hard-depends on a parser being importable.
    """
    seeds = set()
    if not os.path.exists(path):
        return seeds
    try:
        import yaml
        with open(path) as fh:
            data = yaml.safe_load(fh) or {}
        for theme in data.values():
            for s in (theme or {}).get("seeds", []) or []:
                seeds.add(str(s).strip().upper())
        return seeds
    except Exception:  # noqa: BLE001 - fall back to regex
        pass
    with open(path) as fh:
        for line in fh:
            m = re.search(r"seeds:\s*\[(.*?)\]", line)
            if m:
                for tok in m.group(1).split(","):
                    tok = tok.strip().strip('"').strip("'").upper()
                    if tok:
                        seeds.add(tok)
    return seeds


def main():
    out = fetch_listed_symbols()
    if out:
        print(f"fetched listed symbols: {len(out)}")
    else:
        print("WARN: no symbols fetched from network; using offline fallback")

    # ALWAYS union in crypto, theme seeds, and KEEL.
    out.update(CRYPTO)
    seeds = parse_theme_seeds(THEMES_PATH)
    out.update(seeds)
    out.add("KEEL")

    with open(OUT_PATH, "w") as fh:
        fh.write("\n".join(sorted(out)) + "\n")
    print("symbols:", len(out))


if __name__ == "__main__":
    main()
