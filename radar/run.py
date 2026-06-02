from __future__ import annotations
import argparse, sys
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

    by_ticker = {a.ticker: a for a in aggregates}
    for s in board:
        a = by_ticker.get(s.ticker)
        s.themes = themes.themes_for(s.ticker)
        if a is None:
            continue
        s.upvotes = a.upvotes
        s.pct_bull = engagement_pct(a.upvotes, a.mentions)   # engagement proxy (not directional)
        theme = s.themes[0] if s.themes else "stocks"
        meta_line = (f"{a.name or s.ticker}: {a.mentions} Reddit mentions today vs "
                     f"{a.mentions_24h_ago} yesterday, {a.upvotes} upvotes, "
                     f"velocity {s.velocity}x vs its 90-day baseline.")
        s.summary = summarize(s.ticker, [meta_line], theme)
    enrich(board)

    for s in signals:
        history.record(run_day, s.ticker, s.weighted_today, s.mentions, s.distinct_authors,
                       s.pct_bull, s.score, s.state)
    history.prune(keep_through=run_day, days=cfg.history_days)
    if not args.dry_run:
        history.save()

    corpus = sum(a.mentions for a in aggregates)       # total Reddit mentions scanned
    html = render_html(**_build_context(board, signals, run_day, corpus))
    write_outputs(html, {"board": [s.ticker for s in board]}, out_dir=args.out)

    if not args.no_email and not args.dry_run:
        try:
            send_email(run_day, [_email_row(s) for s in board[:cfg.top_n]])
        except Exception:
            pass                                       # email is best-effort; never fail the publish
    return 0

def _vel(s):
    # Display velocity. A brand-new ticker has no baseline, so the engine's internal
    # 999.0 "undefined" sentinel (and genuinely huge comeback ratios) are capped to a
    # clean 99.9 for the UI rather than rendering as "999.0×". Stays numeric so the
    # template's `velocity < 1` comparisons keep working.
    return round(min(s.velocity, 99.9), 1)

def _email_row(s):
    return dict(ticker=s.ticker, velocity=_vel(s), state=s.state,
                pct_bull=s.pct_bull, price=s.price, pct_change=s.pct_change, summary=s.summary)

def _emoji(state): return {"new":"🆕","hot":"🔥","sustained":"➡️","cooling":"🧊"}.get(state,"➡️")
def _css(state): return {"new":"live","hot":"live","cooling":"cool"}.get(state,"")

def _build_context(board, signals, run_day, corpus_count):
    maxw = max((s.weighted_today for s in board), default=1) or 1
    breakout = max(board, key=lambda s: s.velocity, default=None)
    bull = max(board, key=lambda s: s.pct_bull, default=None)
    cooling = sorted([s for s in signals if s.state == "cooling"], key=lambda s: s.surprise)[:3]
    return dict(
        meta=dict(date=run_day, edition_no=1, corpus_count=f"{corpus_count/1000:.1f}k",
                  signals_tracked=len(board),
                  biggest_breakout=(f"{breakout.ticker} {_vel(breakout):.1f}×" if breakout else "—"),
                  most_bullish=(f"{int(bull.pct_bull)}%" if bull else "—")),
        mood=(board[0].summary if board and board[0].summary else "No signals today."),
        board=[dict(rank=i+1, ticker=s.ticker, mentions=s.mentions, velocity=_vel(s),
                    state=s.state, emoji=_emoji(s.state),
                    heat_pct=int(100*s.weighted_today/maxw), css=_css(s.state))
               for i, s in enumerate(board)],
        movers=[dict(rank=i+1, ticker=s.ticker, state_label=s.state.title(), css=_css(s.state),
                     price=s.price, pct_change=s.pct_change,
                     theme=(s.themes[0] if s.themes else ""), mentions=s.mentions,
                     velocity=_vel(s), surprise=s.surprise, authors=s.upvotes,
                     pct_bull=int(s.pct_bull), summary=s.summary, subreddits=" · ".join(s.subreddits[:3]))
                for i, s in enumerate(board[:6])],
        listings=[dict(ticker=s.ticker, theme=(s.themes[0] if s.themes else ""), score=s.score,
                       mentions=s.mentions, velocity=_vel(s), surprise=s.surprise,
                       authors=s.upvotes, pct_bull=int(s.pct_bull), price=s.price,
                       pct_change=s.pct_change, emoji=_emoji(s.state)) for s in board],
        themes=["All","AI Compute","Crypto","Meme","Defense","Bio/Pharma","Oil","Short Squeeze"],
        cooling=[dict(ticker=s.ticker, surprise=s.surprise) for s in cooling],
        trend="0,50 60,48 120,40 160,30 200,8")

if __name__ == "__main__":
    sys.exit(main())
