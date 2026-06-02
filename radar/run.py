from __future__ import annotations
import argparse, sys
from datetime import date
from radar import clock
from radar.config import load_config
from radar.themes import Themes
from radar.history import History
from radar.apewisdom import fetch_mentions
from radar.score import score_aggregates, top_signals
from radar.sentiment import summarize, engagement_pct
from radar.enrich import enrich
from radar.render import render_html, write_outputs
from radar.email_report import send_email
from radar import trump, about

def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-email", action="store_true")
    ap.add_argument("--out", default="out")
    args = ap.parse_args(argv)

    cfg = load_config("config.yaml")
    run_day = clock.run_date(cfg.timezone)
    themes = Themes.load("data/themes.yaml")
    history = History.load("data/history.json")

    aggregates = fetch_mentions(cfg)                    # ApeWisdom; never raises
    signals = score_aggregates(aggregates, history, cfg, run_day)
    board = top_signals(signals, cfg.top_n)

    # Tag themes on a wider slice than the board so every category in Today's Read
    # can find its strongest representative even when it's off the top-15 board.
    for s in signals[:50]:
        s.themes = themes.themes_for(s.ticker)
    category_reads = _category_reads(signals, themes)

    by_ticker = {a.ticker: a for a in aggregates}
    about_cache = about.load_cache("data/about.json")
    about_ua = getattr(getattr(cfg, "apewisdom", None), "user_agent", "reddit-signal-radar/0.1")
    for s in board:
        a = by_ticker.get(s.ticker)
        s.themes = themes.themes_for(s.ticker)
        if a is None:
            continue
        s.upvotes = a.upvotes
        s.pct_bull = engagement_pct(a.upvotes, a.mentions)   # engagement proxy (not directional)
        info = about.describe(s.ticker, a.name, about_cache, about_ua)  # 'what is this company'
        s.name, s.about_desc, s.about_extract = info["name"], info["desc"], info["extract"]
        theme = s.themes[0] if s.themes else "stocks"
        meta_line = (f"{a.name or s.ticker}: {a.mentions} Reddit mentions today vs "
                     f"{a.mentions_24h_ago} yesterday, {a.upvotes} upvotes, "
                     f"velocity {s.velocity}x vs its 90-day baseline.")
        s.summary = summarize(s.ticker, [meta_line], theme)
    enrich(board)
    if not args.dry_run:
        about.save_cache("data/about.json", about_cache)

    for s in signals:
        history.record(run_day, s.ticker, s.weighted_today, s.mentions, s.distinct_authors,
                       s.pct_bull, s.score, s.state)
    history.prune(keep_through=run_day, days=cfg.history_days)
    if not args.dry_run:
        history.save()

    corpus = sum(a.mentions for a in aggregates)       # total Reddit mentions scanned
    refreshed = clock.now_stamp(cfg.timezone)          # when this run actually generated the page
    refreshed_iso = clock.now_iso_utc()
    chips = _chip_list(board, themes)
    detail_json = _detail_blob(board, history, run_day)
    alert = _load_alert("data/trump_alert.json")       # Trump pump alert (if fresh)
    html = render_html(**_build_context(board, signals, run_day, corpus, refreshed,
                                        refreshed_iso, category_reads, chips, detail_json, alert))
    write_outputs(html, {"board": [s.ticker for s in board]}, out_dir=args.out)

    if not args.no_email and not args.dry_run:
        try:
            send_email(run_day, [_email_row(s) for s in board[:cfg.top_n]])
        except Exception:
            pass                                       # email is best-effort; never fail the publish
    return 0

def _vel(s):
    # Internal engine velocity (vs 90-day baseline), capped for any incidental display.
    return round(min(s.velocity, 99.9), 1)

def _vel24(s):
    """Display velocity = mentions vs 24h ago (meaningful from day 1). Returns
    (display_string, numeric). NEW when there's no prior-day data; numeric 1.0 for
    NEW keeps the template's `< 1` down-colouring neutral rather than red."""
    if s.vel_24h is None:
        return ("NEW", 1.0)
    return (f"{min(s.vel_24h, 99.9):.1f}×", s.vel_24h)

def _kfmt(n):
    return f"{n/1000:.1f}k" if n and n >= 1000 else str(int(n or 0))

def _why(s):
    """Deterministic 'why it's trending' blurb from the metrics — always present, so the
    detail modal explains the trend even without a DeepSeek summary."""
    parts = []
    if s.vel_24h is None:
        parts.append(f"new to the tracker with {s.mentions} mentions today")
    elif s.vel_24h >= 1.15:
        parts.append(f"mentions up {min(s.vel_24h, 99.9):.1f}× vs yesterday ({s.mentions} today)")
    elif s.vel_24h <= 0.85:
        parts.append(f"mentions cooling to {s.vel_24h:.1f}× of yesterday ({s.mentions} today)")
    else:
        parts.append(f"steady at {s.mentions} mentions ({s.vel_24h:.1f}× vs yesterday)")
    state_phrase = {
        "new": "no 90-day baseline yet, so it reads as brand-new",
        "hot": f"running {s.surprise:.1f}σ above its 90-day norm",
        "cooling": "fading below its recent average",
        "sustained": "holding near its 90-day average",
    }.get(s.state)
    if state_phrase:
        parts.append(state_phrase)
    if s.themes:
        parts.append(f"{s.themes[0]} theme")
    if s.upvotes:
        parts.append(f"{_kfmt(s.upvotes)} upvotes")
    text = "; ".join(parts)
    return (text[:1].upper() + text[1:] + ".") if text else ""

def _email_row(s):
    return dict(ticker=s.ticker, velocity=_vel24(s)[0], state=s.state,
                pct_bull=s.pct_bull, price=s.price, pct_change=s.pct_change, summary=s.summary)

def _emoji(state): return {"new":"🆕","hot":"🔥","sustained":"➡️","cooling":"🧊"}.get(state,"➡️")
def _css(state): return {"new":"live","hot":"live","cooling":"cool"}.get(state,"")

def _category_order(themes):
    """Display order of categories = the theme labels in themes.yaml order."""
    return [t["label"] for t in themes.raw.values()]

def _category_reads(signals, themes):
    """One line per tracked category: its top-scoring signal, or 'quiet'. Computed
    from data so Today's Read is never blank, even without a DeepSeek summary.
    `signals` is sorted by score desc; only the wider-tagged slice has themes set."""
    reads = []
    for label in _category_order(themes):
        top = next((s for s in signals if label in (s.themes or [])), None)
        if top is None:
            reads.append(dict(category=label, line=f"{label} — quiet", quiet=True))
        else:
            reads.append(dict(category=label, ticker=top.ticker, quiet=False,
                              line=f"{label} — {top.ticker} {_vel24(top)[0]} ({top.mentions} mentions)"))
    return reads

def _load_alert(path):
    """Load the Trump alert for the dashboard card, but only if still fresh (<48h).
    Returns a render-ready dict (post text rendered server-side, autoescaped)."""
    raw = trump.load_alert(path)
    if not raw or not trump.alert_is_fresh(raw, clock.now_utc()):
        return None
    return dict(tickers=" · ".join("$" + t for t in raw.get("tickers", [])),
                post=raw.get("post", ""), url=raw.get("url", ""),
                when=raw.get("published") or raw.get("detected_at") or "")

def _history_series(history, ticker, run_day, days=90):
    """Chronological [{d, m}] mention series within the trailing window, for the
    detail-modal sparkline. Uses the recorded raw mention count per day."""
    hist = history.days_for(ticker)
    before_ord = date.fromisoformat(run_day).toordinal()
    cutoff = before_ord - days
    out = []
    for d in sorted(hist):
        o = date.fromisoformat(d).toordinal()
        if cutoff <= o <= before_ord:
            out.append({"d": d, "m": hist[d].get("raw", 0)})
    return out

def _detail_blob(board, history, run_day):
    """Per-ticker detail (all metrics + 90-day series) embedded for the click modal."""
    blob = {}
    for s in board:
        blob[s.ticker] = dict(
            ticker=s.ticker, name=s.name, about=(s.about_extract or s.about_desc),
            mentions=s.mentions, vel24=_vel24(s)[0], surprise=s.surprise,
            state=s.state, pct_bull=int(s.pct_bull), price=s.price, pct_change=s.pct_change,
            upvotes=s.upvotes, themes=(s.themes or []), summary=s.summary, why=_why(s),
            subreddits=(s.subreddits or []), series=_history_series(history, s.ticker, run_day))
    return blob

def _chip_list(board, themes):
    """Filter chips: 'All' + the categories actually present on the board (in display
    order), and always 'Trump' (it's monitored, so it stays filterable)."""
    order = _category_order(themes)
    present = set()
    for s in board:
        present.update(s.themes or [])
    chips = ["All"] + [c for c in order if c in present]
    if "Trump" not in chips:
        chips.append("Trump")
    return chips

def _build_context(board, signals, run_day, corpus_count, refreshed="", refreshed_iso="",
                   category_reads=None, chips=None, detail_json=None, alert=None):
    maxw = max((s.weighted_today for s in board), default=1) or 1
    ranked = [s for s in board if s.vel_24h is not None]
    breakout = max(ranked, key=lambda s: s.vel_24h, default=None) or \
        max(board, key=lambda s: s.velocity, default=None)
    bull = max(board, key=lambda s: s.pct_bull, default=None)
    cooling = sorted([s for s in signals if s.state == "cooling"], key=lambda s: s.surprise)[:3]
    return dict(
        meta=dict(date=run_day, edition_no=1, corpus_count=f"{corpus_count/1000:.1f}k",
                  signals_tracked=len(board),
                  biggest_breakout=(f"{breakout.ticker} {_vel24(breakout)[0]}" if breakout else "—"),
                  most_bullish=(f"{int(bull.pct_bull)}%" if bull else "—"),
                  refreshed=refreshed, refreshed_iso=refreshed_iso),
        mood=(board[0].summary if board and board[0].summary else ""),
        category_reads=(category_reads or []),
        detail_json=(detail_json or {}),
        alert=alert,
        board=[dict(rank=i+1, ticker=s.ticker, mentions=s.mentions,
                    vel24_disp=_vel24(s)[0], vel24_num=_vel24(s)[1],
                    state=s.state, emoji=_emoji(s.state), themes_attr="|".join(s.themes or []),
                    heat_pct=int(100*s.weighted_today/maxw), css=_css(s.state))
               for i, s in enumerate(board)],
        movers=[dict(rank=i+1, ticker=s.ticker, state_label=s.state.title(), css=_css(s.state),
                     price=s.price, pct_change=s.pct_change, themes_attr="|".join(s.themes or []),
                     theme=(s.themes[0] if s.themes else ""), mentions=s.mentions,
                     vel24_disp=_vel24(s)[0], vel24_num=_vel24(s)[1],
                     surprise=s.surprise, authors=s.upvotes,
                     pct_bull=int(s.pct_bull), summary=s.summary, subreddits=" · ".join(s.subreddits[:3]))
                for i, s in enumerate(board[:6])],
        listings=[dict(ticker=s.ticker, theme=(s.themes[0] if s.themes else ""), score=s.score,
                       mentions=s.mentions, vel24_disp=_vel24(s)[0], vel24_num=_vel24(s)[1],
                       surprise=s.surprise, themes_attr="|".join(s.themes or []),
                       authors=s.upvotes, pct_bull=int(s.pct_bull), price=s.price,
                       pct_change=s.pct_change, emoji=_emoji(s.state)) for s in board],
        themes=(chips or ["All"]),
        cooling=[dict(ticker=s.ticker, surprise=s.surprise) for s in cooling],
        trend="0,50 60,48 120,40 160,30 200,8")

if __name__ == "__main__":
    sys.exit(main())
