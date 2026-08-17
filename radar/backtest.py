"""Self-grading backtest — does the velocity signal predict anything?

Pre-committed test set (spec 2026-08-07, no fishing beyond these): quintile forward
excess returns, daily rank IC, event study around hot-transitions, forward-volatility
quintiles, and the Early Plays scorecard. The look-ahead rule is structural: every
price window starts at entry_index() -- the first trading day STRICTLY after the
signal day. Effective sample size is DAYS, not ticker-days; power() says when the
read is real (>=150 days). Runs weekly (backtest.yml); must never touch the daily board.
"""
from __future__ import annotations

import argparse, json, math, statistics, sys
from datetime import date, timedelta
from pathlib import Path

from radar.history import History
from radar.plays_log import load_picks

REGIME_NOTES = [
    {"date": "2026-08-17",
     "note": "E1 catalyst layer: composite `events` became signed (bearish 0 / "
             "neutral 50 / bullish 100) and None when no fresh alert covers the "
             "ticker, where it was previously 100/0 with 0 for 'no alert'. Every "
             "composite before and after this date is incomparable. Four new alert "
             "classes (dilution/shelf/activist/delisting) also feed `events`."},
    {"date": "2026-08-07",
     "note": "PR #4 merged: history 'state' becomes board-relative for board names; "
             "noise floor min_mentions 5 -> 10."},
]
TARGET_DAYS = 150
HORIZONS = (1, 5, 10)


# ---------- price plumbing ----------

def trading_days(prices: dict, benchmark: str = "SPY") -> list[str]:
    return sorted((prices.get(benchmark) or {}).keys())


def entry_index(days: list[str], signal_day: str) -> int | None:
    """First trading day STRICTLY after signal_day — the look-ahead gate."""
    for i, d in enumerate(days):
        if d > signal_day:
            return i
    return None


def _open(prices, sym, day):
    rec = (prices.get(sym) or {}).get(day)
    return rec.get("open") if rec else None


def window_return(prices, sym, days, i0, h):
    if i0 is None or i0 + h >= len(days):
        return None
    a, b = _open(prices, sym, days[i0]), _open(prices, sym, days[i0 + h])
    if not a or b is None:
        return None
    return b / a - 1.0


def excess_return(prices, sym, days, i0, h, benchmark="SPY"):
    r, br = window_return(prices, sym, days, i0, h), window_return(prices, benchmark, days, i0, h)
    if r is None or br is None:
        return None
    return r - br


# ---------- stats ----------

def _rank(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):                       # average ranks for ties
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(xs, ys) -> float:
    if len(xs) < 2 or len(xs) != len(ys):
        return 0.0
    rx, ry = _rank(xs), _rank(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    dy = math.sqrt(sum((b - my) ** 2 for b in ry))
    if dx == 0 or dy == 0:
        return 0.0
    return num / (dx * dy)


def _newey_west_t(series: list[float], lag: int) -> float:
    """t-stat of the mean with Newey-West (Bartlett) correction for overlap."""
    n = len(series)
    if n < 3:
        return 0.0
    mean = statistics.fmean(series)
    e = [x - mean for x in series]
    var = sum(v * v for v in e) / n
    for k in range(1, min(lag, n - 1) + 1):
        w = 1.0 - k / (lag + 1.0)
        var += 2.0 * w * sum(e[i] * e[i - k] for i in range(k, n)) / n
    if var <= 0:
        return 0.0
    return mean / math.sqrt(var / n)


# ---------- signal frames ----------

def _frames(history: dict):
    """{day: [(ticker, score)]} for every recorded ticker-day."""
    frames: dict[str, list] = {}
    for t, days in history.items():
        for d, rec in days.items():
            frames.setdefault(d, []).append((t, float(rec.get("score") or 0.0)))
    return frames


def _quintile(rows_sorted, q):                  # q in 1..5, rows sorted ascending by score
    n = len(rows_sorted)
    lo, hi = (q - 1) * n // 5, q * n // 5
    return rows_sorted[lo:hi]


# ---------- the pre-committed tests ----------

def quintile_table(history, prices, days, horizon, benchmark="SPY"):
    per_q = {q: [] for q in range(1, 6)}
    n_total = 0
    for day, rows in _frames(history).items():
        i0 = entry_index(days, day)
        if i0 is None or len(rows) < 5:
            continue
        rows_sorted = sorted(rows, key=lambda r: r[1])
        for q in range(1, 6):
            for t, _score in _quintile(rows_sorted, q):
                r = excess_return(prices, t, days, i0, horizon, benchmark)
                if r is not None:
                    per_q[q].append(r); n_total += 1
    out = {"horizon": horizon, "n": n_total}
    for q in range(1, 6):
        vals = per_q[q]
        out[f"q{q}"] = {"mean_excess": (statistics.fmean(vals) if vals else None),
                        "n": len(vals)}
    q1, q5 = out["q1"]["mean_excess"], out["q5"]["mean_excess"]
    out["spread"] = (q5 - q1) if (q1 is not None and q5 is not None) else None
    return out


def rank_ic(history, prices, days, horizon):
    ics = []
    for day, rows in sorted(_frames(history).items()):
        i0 = entry_index(days, day)
        if i0 is None or len(rows) < 5:
            continue
        scores, rets = [], []
        for t, score in rows:
            r = excess_return(prices, t, days, i0, horizon)
            if r is not None:
                scores.append(score); rets.append(r)
        if len(scores) >= 5:
            ics.append(spearman(scores, rets))
    if not ics:
        return {"mean": None, "t": None, "days": 0}
    return {"mean": statistics.fmean(ics), "t": _newey_west_t(ics, lag=horizon),
            "days": len(ics)}


def event_study(history, prices, days, pre=5, post=20):
    """Mean cumulative excess (close-to-close log) return around transitions INTO 'hot'.

    Only COMPLETE events enter the averages -- every bar from -pre..post must be priced
    and in range. A partial event (unpriced ticker, or too close to the end of the price
    series to fill the window) would otherwise dilute the curve with a frozen/zero-padded
    contribution counted as if it were a full observation. n_events is every transition
    found; n_used is how many were actually complete enough to average -- that, not
    n_events, is the real denominator.

    The curve is rebased so offset -1 is 0.0: car["0"] onward is pure post-event drift,
    not contaminated by the pre-event run-up baked into cumulating from -pre. The
    offset-0 bar itself spans the signal day's close to the entry day's close -- an
    event-study measurement window, not a tradeable return (actual entry only happens at
    the next open, per the look-ahead gate used everywhere else in this module)."""
    events = []
    for t, tdays in history.items():
        ordered = sorted(tdays)
        for prev, cur in zip(ordered, ordered[1:]):
            if tdays[cur].get("state") == "hot" and tdays[prev].get("state") != "hot":
                events.append((t, cur))

    def _close(sym, day):
        rec = (prices.get(sym) or {}).get(day)
        return rec.get("close") if rec else None

    offsets = list(range(-pre, post + 1))
    sums = {off: 0.0 for off in offsets}
    n_used = 0
    for t, day0 in events:
        i0 = entry_index(days, day0)
        if i0 is None:
            continue
        bars = {}
        for off in offsets:
            i = i0 + off
            if not (1 <= i < len(days)):
                bars = None
                break
            a, b = _close(t, days[i - 1]), _close(t, days[i])
            ba, bb = _close("SPY", days[i - 1]), _close("SPY", days[i])
            if not (a and b and ba and bb):
                bars = None
                break
            bars[off] = math.log(b / a) - math.log(bb / ba)
        if bars is None:
            continue                                       # incomplete -- excluded from the averages
        cum, cumulative = 0.0, {}
        for off in offsets:
            cum += bars[off]
            cumulative[off] = cum
        base = cumulative.get(-1, 0.0)                      # rebase so offset -1 == 0.0
        n_used += 1
        for off in offsets:
            sums[off] += cumulative[off] - base
    car_mean = {str(off): (sums[off] / n_used if n_used else None) for off in offsets}
    return {"n_events": len(events), "n_used": n_used, "car": car_mean}


def vol_quintiles(history, prices, days, horizon=10):
    """Forward realized vol (stdev of daily close-to-close log returns, annualized)."""
    def _fwd_vol(t, i0):
        rets = []
        for i in range(i0 + 1, min(i0 + 1 + horizon, len(days))):
            a = (prices.get(t) or {}).get(days[i - 1], {}).get("close")
            b = (prices.get(t) or {}).get(days[i], {}).get("close")
            if a and b:
                rets.append(math.log(b / a))
        if len(rets) < 3:
            return None
        return statistics.pstdev(rets) * math.sqrt(252)

    per_q = {q: [] for q in range(1, 6)}
    for day, rows in _frames(history).items():
        i0 = entry_index(days, day)
        if i0 is None or len(rows) < 5:
            continue
        rows_sorted = sorted(rows, key=lambda r: r[1])
        for q in range(1, 6):
            for t, _s in _quintile(rows_sorted, q):
                v = _fwd_vol(t, i0)
                if v is not None:
                    per_q[q].append(v)
    out = {}
    for q in range(1, 6):
        v = per_q[q]
        out[f"q{q}"] = {"mean": (statistics.fmean(v) if v else None), "n": len(v)}
    return out


def scorecard(plays, prices, days, benchmark="SPY"):
    """Grade every logged Early Plays pick from its first tradeable open. Crypto picks
    (logged with a truthy "crypto" field) are excluded from grading -- yfinance can
    silently price a same-symbol NYSE equity instead of the crypto asset -- and are
    counted in `excluded_crypto` instead."""
    rows = []
    excluded_crypto = 0
    for pk in plays:
        if pk.get("crypto"):
            excluded_crypto += 1
            continue
        i0 = entry_index(days, pk.get("date", ""))
        row = {"date": pk.get("date"), "ticker": pk.get("ticker"),
               "conviction": pk.get("conviction", ""),
               "excess_5d": excess_return(prices, pk.get("ticker"), days, i0, 5, benchmark),
               "excess_10d": excess_return(prices, pk.get("ticker"), days, i0, 10, benchmark)}
        rows.append(row)
    g5 = [r["excess_5d"] for r in rows if r["excess_5d"] is not None]
    g10 = [r["excess_10d"] for r in rows if r["excess_10d"] is not None]
    return {"n_picks": len(rows),
            "since": min((r["date"] for r in rows if r["date"]), default=None),
            "mean_excess_5d": (statistics.fmean(g5) if g5 else None),
            "mean_excess_10d": (statistics.fmean(g10) if g10 else None),
            "win_rate_5d": (sum(1 for x in g5 if x > 0) / len(g5) if g5 else None),
            "win_rate_10d": (sum(1 for x in g10 if x > 0) / len(g10) if g10 else None),
            "picks": rows,
            "excluded_crypto": excluded_crypto,
            "disclaimer": "Hypothetical, frictionless, benchmark-adjusted. Not investment advice."}


def power(history: dict) -> dict:
    days = {d for t in history.values() for d in t}
    return {"days": len(days), "sufficient": len(days) >= TARGET_DAYS,
            "target_days": TARGET_DAYS}


# ---------- orchestration (network + I/O) ----------

def fetch_prices(tickers, start: str, end: str, warn_missing: bool = True) -> dict:
    """Daily open/close via yfinance batch download. Per-ticker fail-soft: a symbol
    Yahoo can't price is simply absent (every consumer treats missing as None).

    A single bad row does not take its whole ticker down with it: row extraction is
    guarded per-row, and a ticker's rows are only committed to the result once the
    whole per-ticker block succeeds -- an exception partway through (frame access or
    mid-iteration) drops that ticker entirely rather than leaving a silently truncated
    partial history, which would be worse than absence. One summary breadcrumb reports
    how many requested tickers came back unpriced (a small sample, not the whole list)
    instead of staying silent about every failure -- unless warn_missing=False, which
    callers pass when an unpriceable ticker is an expected, permanent fact (e.g. a
    delisted/crypto pick sitting in the append-only plays log) rather than a transient
    outage worth surfacing on every run."""
    from radar import degrade
    requested = sorted(set(tickers))
    out: dict = {}
    try:
        import yfinance as yf
        data = yf.download(requested, start=start, end=end,
                           interval="1d", auto_adjust=True, progress=False,
                           group_by="ticker", threads=True)
    except Exception as e:
        degrade.warn("backtest price download", e)
        return out
    for t in requested:
        ticker_prices: dict = {}
        try:
            df = data[t] if len(requested) > 1 else data
            for idx, row in df.iterrows():
                try:
                    o, c = float(row["Open"]), float(row["Close"])
                    if o > 0 and c > 0 and o == o and c == c:      # NaN-safe
                        ticker_prices[idx.strftime("%Y-%m-%d")] = {"open": o, "close": c}
                except Exception:
                    continue                                       # one bad row -> skip just that row
        except Exception:
            continue                                               # frame access/iteration failed -> drop ticker entirely
        if ticker_prices:
            out[t] = ticker_prices
    missing = [t for t in requested if t not in out]
    if missing and warn_missing:
        degrade.warn("backtest prices",
                     f"{len(missing)}/{len(requested)} tickers unpriced: {missing[:5]}")
    return out


def _pricing_universe(history: dict) -> set[str]:
    """Tickers worth pricing: every ticker that ever appears in history -- not just
    ones that reached a top-quintile score frame. Restricting to top-quintile-only
    (the original implementation) priced q5 completely while grading q1-q4 against a
    survivorship-biased 'formerly hot' subsample, distorting spread and rank_ic."""
    return set(history.keys())


def run_backtest(history_path="data/history.json", plays_path="data/plays_log.json",
                 out_path="out/backtest.json") -> dict:
    history = History.load(history_path).data
    plays = load_picks(plays_path)
    all_days = sorted({d for t in history.values() for d in t})
    if not all_days:
        result = {"error": "no history", "power": power(history)}
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=1))
        return result

    start = (date.fromisoformat(all_days[0]) - timedelta(days=10)).isoformat()
    end = (date.fromisoformat(all_days[-1]) + timedelta(days=25)).isoformat()
    tickers = (_pricing_universe(history)
               | {p.get("ticker") for p in plays if p.get("ticker")}
               | {"SPY", "IWM"})
    prices = fetch_prices(tickers, start, end)
    days = trading_days(prices)
    if not days:
        # yfinance down / empty batch -- do NOT overwrite the last good artifact with an
        # all-null one that the weekly workflow would commit and that reads exactly like
        # "the signal has no power" (Finding 5). Fail loud instead of silently wrong.
        return {"error": "price fetch failed", "power": power(history)}

    result = {
        "as_of": all_days[-1],
        "power": power(history),
        "regime_notes": REGIME_NOTES,
        "quintiles": {str(h): quintile_table(history, prices, days, h) for h in HORIZONS},
        "quintiles_iwm": {str(h): quintile_table(history, prices, days, h, benchmark="IWM")
                          for h in HORIZONS},
        "rank_ic": {str(h): rank_ic(history, prices, days, h) for h in HORIZONS},
        "event_study": event_study(history, prices, days),
        "vol_test": vol_quintiles(history, prices, days),
        "scorecard": scorecard(plays, prices, days),
        "price_coverage": {"requested": len(tickers), "priced": len(prices),
                           "missing": sorted(tickers - set(prices))[:10]},
        "universe": {"description": "all history tickers + logged picks + benchmarks",
                     "n_tickers": len(tickers)},
    }
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1))
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--history", default="data/history.json")
    ap.add_argument("--plays", default="data/plays_log.json")
    ap.add_argument("--out", default="out")
    args = ap.parse_args(argv)
    result = run_backtest(args.history, args.plays, str(Path(args.out) / "backtest.json"))
    if "error" in result:
        print(f"backtest: {result['error']}", file=sys.stderr)
        return 1
    pw = result.get("power", {})
    print(f"backtest: {pw.get('days', 0)} days of history "
          f"(sufficient={pw.get('sufficient')}); wrote backtest.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
