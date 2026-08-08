from __future__ import annotations
import argparse, os, sys
from datetime import date
from pathlib import Path
from radar.dotenv import load_env
from radar import degrade
from radar.health import assess as assess_health
from radar.email_report import send_health_alert
from radar import clock
from radar.config import load_config
from radar.themes import Themes
from radar.history import History
from radar.apewisdom import fetch_mentions
from radar import tradestie
from radar.shorts import fetch_short_ratios
from radar.options import option_stats
from radar.cramer import fetch_cramer
from radar.composite import components_for, blend, DEFAULT_WEIGHTS
from radar.score import score_aggregates, top_signals, assign_relative_states
from radar.still_running import still_running
from radar.sentiment import summarize, engagement_pct, daily_read, why_it_matters, recommend_buys
from radar.enrich import enrich
from radar.render import render_html, write_outputs
from radar.email_report import send_email
from radar import trump, about, news
from radar import backtest
from radar.plays_log import append_picks, load_picks

def _enrich_ticker(s, by_ticker, about_cache, about_ua, themes):
    """Attach themes, engagement, 'what it is', the news catalyst, and a DeepSeek
    summary to one Signal. Shared by the board and the Still Running lane."""
    a = by_ticker.get(s.ticker)
    s.themes = themes.themes_for(s.ticker)
    if a is None:
        return
    s.upvotes = a.upvotes
    s.pct_bull = engagement_pct(a.upvotes, a.mentions)   # engagement proxy (not directional)
    info = about.describe(s.ticker, a.name, about_cache, about_ua)  # 'what is this company'
    s.name, s.about_desc, s.about_extract = info["name"], info["desc"], info["extract"]
    theme = s.themes[0] if s.themes else "stocks"
    s.headlines = news.headlines(s.ticker, a.name, about_ua)   # the catalyst behind the chatter
    s.summary = summarize(s.ticker, s.headlines, theme)        # WHY it's trending, from real news

def main(argv=None) -> int:
    load_env()                                          # local .env (no-op in CI; env wins)
    degrade.reset()                                     # health assesses this run only
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
    ts_rows = tradestie.fetch_wsb(cfg)                  # directional sentiment (fail-soft)
    board_source = "apewisdom"
    if not aggregates and ts_rows:                      # ApeWisdom down -> partial WSB board
        degrade.warn("apewisdom empty", "falling back to tradestie top-50 board")
        aggregates = tradestie.to_aggregates(ts_rows)
        board_source = "tradestie-fallback"
    signals = score_aggregates(aggregates, history, cfg, run_day)
    board = top_signals(signals, cfg.top_n)
    still = still_running(signals, history, run_day, board, cfg)
    assign_relative_states(signals, board)              # relative lifecycle tiers (Phase B)

    # Tag themes on a wider slice than the board so every category in Today's Read
    # can find its strongest representative even when it's off the top-15 board.
    for s in signals[:50]:
        s.themes = themes.themes_for(s.ticker)

    by_ticker = {a.ticker: a for a in aggregates}
    about_cache = about.load_cache("data/about.json")
    about_ua = getattr(getattr(cfg, "apewisdom", None), "user_agent", "reddit-signal-radar/0.1")
    for s in board:
        _enrich_ticker(s, by_ticker, about_cache, about_ua, themes)
    for s in still:
        _enrich_ticker(s, by_ticker, about_cache, about_ua, themes)
    enrich(board + still)
    today_read = _today_read(board, themes)            # DeepSeek smart read (deterministic fallback)
    why_matters = _why_matters(board, today_read)      # DeepSeek 'why you should care' so-what
    early_plays = _early_plays(board)                  # DeepSeek 'get in early' buy ideas (fail-closed)
    if early_plays and not args.dry_run:
        try:                                            # log the call — the track record
            crypto_tickers = {t for t, a in by_ticker.items() if a.subreddit == "all-crypto"}
            append_picks("data/plays_log.json", run_day, early_plays,
                         {s.ticker: s for s in board}, crypto_tickers=crypto_tickers)
        except Exception as e:
            degrade.warn("plays-log append", e)
    scorecard = _daily_scorecard(run_day) if not args.dry_run else None
    if not args.dry_run:
        about.save_cache("data/about.json", about_cache)

    for s in signals:
        history.record(run_day, s.ticker, s.weighted_today, s.mentions, s.distinct_authors,
                       s.pct_bull, s.score, s.state)
    ts_by = {r.ticker: r for r in ts_rows}
    for s in signals:
        r = ts_by.get(s.ticker)
        if r:
            history.annotate(run_day, s.ticker,
                             ts_bull=tradestie.bull_pct(r.score), ts_comments=r.comments)
    short_ratios, _shorts_day = fetch_short_ratios(cfg, run_day)   # fail-soft {} on outage
    for s in signals:
        r = short_ratios.get(s.ticker)
        if r is not None:
            s.short_ratio = round(r, 4)
            history.annotate(run_day, s.ticker, short_ratio=s.short_ratio)
    cboe_cfg = getattr(cfg, "cboe", None)
    cboe_hits = 0
    cboe_slice = board[:int(getattr(cboe_cfg, "top_n", 10))]
    consecutive_failures = 0
    for i, s in enumerate(cboe_slice):
        stats = option_stats(s.ticker, cfg)
        if stats is None:                           # real outage — warn + count toward the breaker
            degrade.warn("cboe options", s.ticker)
            consecutive_failures += 1
            if consecutive_failures >= 3:
                remaining = len(cboe_slice) - i - 1
                degrade.warn("cboe options",
                             f"skipping remaining {remaining} after 3 consecutive failures")
                break
            continue
        consecutive_failures = 0
        cboe_hits += 1                               # service responded (chain or a clean 404)
        if stats == "missing":                       # no chain for this name — not a failure
            continue
        if stats["pc_ratio"] is not None:
            s.pc_ratio = round(stats["pc_ratio"], 3)
        s.uoa = bool(stats["total_oi"] > 0
                     and stats["total_vol"] >= float(getattr(cboe_cfg, "min_volume", 1000))
                     and stats["total_vol"] / stats["total_oi"]
                         > float(getattr(cboe_cfg, "uoa_vol_oi", 1.0)))
        history.annotate(run_day, s.ticker, pc_ratio=s.pc_ratio, uoa=s.uoa)
    cramer_by = fetch_cramer(cfg, run_day) if not args.dry_run else {}
    for s in signals:
        c = cramer_by.get(s.ticker)
        if c:
            s.cramer = c
            history.annotate(run_day, s.ticker, cramer=c)
    history.prune(keep_through=run_day, days=cfg.history_days)
    if not args.dry_run:
        history.save()

    corpus = sum(a.mentions for a in aggregates)       # total Reddit mentions scanned
    refreshed = clock.now_stamp(cfg.timezone)          # when this run actually generated the page
    refreshed_iso = clock.now_iso_utc()
    chips = _chip_list(board, themes)
    reddit_subs = list(getattr(getattr(cfg, "reddit", None), "discussion_subreddits", []) or [])
    alerts = _load_alerts("data")                      # every monitor's fresh alert card
    alert_tickers = {t.strip("$") for a in alerts for t in a["tickers"].split(" · ") if t}
    comp_cfg = getattr(cfg, "composite", None)
    weights = ({k: float(v) for k, v in vars(comp_cfg.weights).items()}
               if getattr(comp_cfg, "weights", None) else dict(DEFAULT_WEIGHTS))
    ts_by_bull = {r.ticker: tradestie.bull_pct(r.score) for r in ts_rows}
    for s in board:
        s.components = components_for(s, board, ts_by_bull.get(s.ticker), alert_tickers)
        s.composite, _used = blend(s.components, weights)
    detail_json = _detail_blob(board + still, history, run_day, reddit_subs)
    sources = {                                        # shown as footer LEDs + published in health
        "apewisdom": ("ok" if board_source == "apewisdom" and board else "down"),
        "tradestie": ("fallback" if board_source == "tradestie-fallback"
                      else ("ok" if ts_rows else "down")),
        "finnhub": ("ok" if os.environ.get("FINNHUB_API_KEY") else "unused"),
        "finra": "ok" if short_ratios else "down",
        "cboe": "ok" if cboe_hits else ("down" if board else "unused"),
        "cramer": "ok" if cramer_by else "down",
    }
    html = render_html(**_build_context(board, signals, run_day, corpus, refreshed,
                                        refreshed_iso, today_read, chips, detail_json,
                                        why_matters=why_matters, early_plays=early_plays,
                                        still=still, alerts=alerts, scorecard=scorecard,
                                        sources=sources))
    health = assess_health(board, degrade.events(),
                           bool(os.environ.get("DEEPSEEK_API_KEY")),
                           sources=sources)
    health["date"] = run_day
    payload = {"board": [s.ticker for s in board], "health": health,
               "signals": [dict(ticker=s.ticker, composite=s.composite,
                                components=s.components,
                                short_ratio=s.short_ratio, pc_ratio=s.pc_ratio,
                                uoa=s.uoa, cramer=s.cramer,
                                mentions=s.mentions, score=round(s.score, 2),
                                state=s.state, price=s.price)
                           for s in board],
               "weights": weights}
    if scorecard:
        payload["scorecard"] = scorecard
    write_outputs(html, payload, out_dir=args.out)

    if not args.no_email and not args.dry_run:
        # Email is best-effort — never fail the publish — but DON'T swallow silently:
        # log why it didn't go out so a broken key/domain/recipient is visible in CI logs.
        try:
            sent = send_email(run_day, [_email_row(s) for s in board[:cfg.top_n]],
                              [_still_email_row(s) for s in still])
            if not sent:
                print("EMAIL: not sent — RESEND_API_KEY or EMAIL_RECIPIENTS missing/empty",
                      file=sys.stderr)
        except Exception as e:                         # surface the provider error, keep publishing
            print(f"EMAIL: send failed — {e!r}", file=sys.stderr)
    if health["status"] == "severe" and not args.no_email and not args.dry_run:
        # The radar's own alarm: the published board is materially wrong (empty, mostly
        # price-less, or summary-less with a key configured). Best-effort like the digest.
        try:
            if not send_health_alert(run_day, health):
                print("HEALTH: severe degradation but alert not sent — RESEND creds missing",
                      file=sys.stderr)
        except Exception as e:
            print(f"HEALTH: alert send failed — {e!r}", file=sys.stderr)
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
                pct_bull=s.pct_bull, price=s.price, pct_change=s.pct_change,
                summary=s.summary, mentions=s.mentions, name=s.name)

def _still_email_row(s):
    return dict(ticker=s.ticker, price=s.price, pct_change=s.pct_change,
                days_running=(s.days_running or 0), name=s.name, mentions=s.mentions)

def _emoji(state): return {"new":"🆕","hot":"🔥","sustained":"➡️","cooling":"🧊"}.get(state,"➡️")
def _css(state): return {"new":"live","hot":"live","cooling":"cool"}.get(state,"")

def _category_order(themes):
    """Display order of categories = the theme labels in themes.yaml order."""
    return [t["label"] for t in themes.raw.values()]

def _trend_word(s):
    """Qualitative mention-trend label (no raw counts) for the DeepSeek prompt + fallback."""
    if s.vel_24h is None:
        return "new"
    if s.vel_24h >= 1.15:
        return "heating up vs yesterday"
    if s.vel_24h <= 0.85:
        return "cooling vs yesterday"
    return "steady"

def _read_bullet_why(s):
    """Deterministic per-ticker 'why' with NO mention counts — the fallback when DeepSeek
    is unavailable, so Today's Read is never blank or numeric."""
    base = {"new": "new to the tracker",
            "heating up vs yesterday": "heating up vs yesterday",
            "cooling vs yesterday": "cooling off vs yesterday",
            "steady": "holding steady"}[_trend_word(s)]
    tail = {"hot": "running hot above its 90-day norm",
            "cooling": "fading below its recent average"}.get(s.state)
    theme = s.themes[0] if s.themes else None
    return " · ".join(p for p in (base, tail, theme) if p)

def _today_read(board, themes):
    """Today's Read = a DeepSeek smart summary of what's going on (lead sentence + a 'why'
    per notable ticker, no mention counts). Falls back to deterministic qualitative text so
    the block is never blank and never shows raw counts. Returns {lead, bullets}."""
    top = board[:6]
    if not top:
        return dict(lead="No signals on the board today — the tape is quiet.", bullets=[])
    items = [dict(ticker=s.ticker, name=s.name, theme=(s.themes[0] if s.themes else "stocks"),
                  trend=_trend_word(s), state=s.state, about=(s.about_extract or s.about_desc))
             for s in top]
    read = daily_read(items)
    if read and read.get("bullets"):
        have = {b["ticker"] for b in read["bullets"]}
        for s in top:                                  # backfill any ticker DeepSeek skipped
            if s.ticker not in have:
                read["bullets"].append(dict(ticker=s.ticker, why=_read_bullet_why(s)))
        if not read.get("lead"):
            read["lead"] = _read_fallback(top)["lead"]
        return read
    return _read_fallback(top)                          # no key / DeepSeek down

def _daily_scorecard(run_day):
    """Grade all logged picks vs SPY — the cheap daily slice of the weekly backtest.
    Fail-soft: any problem returns None and the board ships without a scorecard.

    The plays log is append-only, so one permanently-unpriceable pick (delisted/crypto
    ticker) would otherwise trip fetch_prices's "backtest prices" warn on every single
    daily run, degrading health.status forever. warn_missing=False silences that; a
    genuine benchmark outage (no SPY prices at all, so there are no trading days to grade
    against) still surfaces its own "daily scorecard" breadcrumb -- transient and heals
    once yfinance is back, unlike the permanent one it replaces."""
    try:
        plays = load_picks("data/plays_log.json")
        if not plays:
            return None
        from datetime import date, timedelta
        first = min(p["date"] for p in plays)
        start = (date.fromisoformat(first) - timedelta(days=5)).isoformat()
        tickers = {p["ticker"] for p in plays} | {"SPY"}
        prices = backtest.fetch_prices(tickers, start, run_day, warn_missing=False)
        days = backtest.trading_days(prices)
        if not days:
            degrade.warn("daily scorecard", "no benchmark prices from yfinance")
            return None
        return backtest.scorecard(plays, prices, days)
    except Exception as e:
        degrade.warn("daily scorecard", e)
        return None

def _early_plays(board):
    """DeepSeek 'early plays' card: feed the top of the board (with each name's catalyst summary)
    to recommend_buys and return up to 3 ranked picks, each tagged with the company name for
    display. Empty list -> the card is hidden (we never fabricate buy ideas)."""
    top = board[:12]
    if not top:
        return []
    cands = [dict(ticker=s.ticker, name=s.name, theme=(s.themes[0] if s.themes else "stocks"),
                  mentions=s.mentions, vel=_vel24(s)[0], state=s.state, summary=s.summary)
             for s in top]
    by = {s.ticker: s for s in top}
    picks = recommend_buys(cands)
    for p in picks:
        s = by.get(p["ticker"])
        p["name"] = s.name if s else p["ticker"]
        p["vel24"] = _vel24(s)[0] if s else ""
    return picks

def _why_matters(board, today_read):
    """'Why It Matters' = a DeepSeek so-what take on the day. Deterministic fallback keeps the
    section populated (and number-free) when DeepSeek is down. Returns a string."""
    top = board[:6]
    if not top:
        return ("Nothing is breaking out today — a quiet tape is itself a signal that retail "
                "attention has rotated elsewhere. Worth a look tomorrow.")
    items = [dict(ticker=s.ticker, name=s.name, theme=(s.themes[0] if s.themes else "stocks"),
                  trend=_trend_word(s), state=s.state) for s in top]
    take = why_it_matters(items, (today_read or {}).get("lead", ""))
    if take:
        return take
    hot = [s for s in top if s.state == "hot" or (s.vel_24h or 0) >= 1.15]
    movers = ", ".join(s.ticker for s in (hot or top)[:3])
    return (f"Reddit attention is rising fastest around {movers} right now — the kind of early crowd "
            f"signal that sometimes precedes a move, which is exactly what this radar is built to "
            f"surface before it's obvious. Worth watching, but Reddit volume reflects attention, not "
            f"conviction, so treat it as a lead to investigate rather than a buy signal.")

def _read_fallback(top):
    lead_theme = (top[0].themes[0] if top[0].themes else "the board")
    lead = (f"{lead_theme} is leading today, with {top[0].ticker} the standout; "
            f"{len(top)} names are drawing the most Reddit attention.")
    return dict(lead=lead,
                bullets=[dict(ticker=s.ticker, why=_read_bullet_why(s)) for s in top])

def _load_alerts(data_dir="data"):
    """Collect every monitor's fresh alert (data/*_alert.json) into render-ready view-models,
    newest-first. Self-describing files mean new monitors appear with no render-code change.
    Tolerates the legacy Trump schema (post/when) alongside the new schema (summary)."""
    import glob
    out = []
    for path in glob.glob(str(Path(data_dir) / "*_alert.json")):
        raw = trump.load_alert(path)
        if not raw:
            continue
        max_age = int(raw.get("max_age_h") or 48)
        if not trump.alert_is_fresh(raw, clock.now_utc(), max_age):
            continue
        tickers = raw.get("tickers", [])
        out.append(dict(
            tag=raw.get("label", "⚠ Alert"),
            tickers=" · ".join("$" + t for t in tickers),
            body=raw.get("summary") or raw.get("post", ""),     # new schema | legacy
            url=raw.get("url", ""),
            meta=raw.get("published") or raw.get("detected_at") or raw.get("when", ""),
            style=raw.get("card_style", "trump"),
            link_text=raw.get("link_text") or "View ↗",
            theme_attr=(raw.get("monitor_key") or "alert").title(),
            detected=raw.get("detected_at") or raw.get("published") or "",
        ))
    out.sort(key=lambda a: a.get("detected", ""), reverse=True)
    return out


def _coerce_alerts(alerts, legacy_alert):
    """Prefer the new alerts list; else wrap a legacy single `alert` dict
    (keys: tickers,str / post / url / when) into the new card view-model."""
    if alerts is not None:
        return alerts
    if not legacy_alert:
        return []
    return [dict(tag="⚠ Trump Alert", tickers=legacy_alert.get("tickers", ""),
                 body=legacy_alert.get("post", ""), url=legacy_alert.get("url", ""),
                 meta=legacy_alert.get("when", ""), style="trump",
                 link_text="Truth Social post ↗", theme_attr="Trump")]

def _reddit_search_url(ticker, subs=None):
    """Link to the live Reddit discussions for a ticker — a cashtag search sorted by top this
    week, scoped to the finance subreddits in `subs` (less noise) or site-wide when empty.
    A human's browser (not a cloud IP) loads it fine."""
    if subs:
        base = "https://www.reddit.com/r/" + "+".join(subs) + "/search/"
        return f"{base}?q=%24{ticker}&restrict_sr=1&sort=top&t=week"
    return f"https://www.reddit.com/search/?q=%24{ticker}&sort=top&t=week"

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

def _detail_blob(board, history, run_day, reddit_subs=None):
    """Per-ticker detail (all metrics + 90-day series) embedded for the click modal."""
    blob = {}
    for s in board:
        blob[s.ticker] = dict(
            ticker=s.ticker, name=s.name, about=(s.about_extract or s.about_desc),
            mentions=s.mentions, vel24=_vel24(s)[0], surprise=s.surprise,
            state=s.state, pct_bull=int(s.pct_bull), price=s.price, pct_change=s.pct_change,
            composite=s.composite, components=(s.components or {}),
            short_ratio=s.short_ratio, pc_ratio=s.pc_ratio, uoa=s.uoa, cramer=s.cramer,
            upvotes=s.upvotes, themes=(s.themes or []), summary=s.summary, why=_why(s),
            headlines=(s.headlines or [])[:3],   # the actual news driving the chatter
            reddit=_reddit_search_url(s.ticker, reddit_subs),  # link to live Reddit discussions
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

_COMP_ORDER = [("velocity", "vel"), ("direction", "dir"), ("engagement", "eng"),
               ("short_pressure", "shorts"), ("options", "options"),
               ("events", "alerts"), ("cramer_inverse", "cramer⁻¹")]

def _comp_list(s):
    """Fixed-order (label, value) pairs for the signal-DNA strip. A None value means
    the source didn't cover this name today (rendered as an empty cell), which is a
    different fact than a real 0."""
    comps = s.components or {}
    return [dict(key=k, label=lbl, val=comps.get(k)) for k, lbl in _COMP_ORDER]

def _build_context(board, signals, run_day, corpus_count, refreshed="", refreshed_iso="",
                   today_read=None, chips=None, detail_json=None, alert=None, why_matters="",
                   early_plays=None, still=None, alerts=None, scorecard=None, sources=None):
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
        today_read=(today_read or dict(lead="", bullets=[])),
        why_matters=(why_matters or ""),
        early_plays=(early_plays or []),
        scorecard=scorecard,
        sources=(sources or {}),
        detail_json=(detail_json or {}),
        alerts=_coerce_alerts(alerts, alert),
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
                     composite=s.composite, short_ratio=s.short_ratio,
                     pc_ratio=s.pc_ratio, uoa=s.uoa, cramer=s.cramer,
                     pct_bull=int(s.pct_bull), summary=s.summary, subreddits=" · ".join(s.subreddits[:3]))
                for i, s in enumerate(board[:6])],
        listings=[dict(ticker=s.ticker, theme=(s.themes[0] if s.themes else ""), score=s.score,
                       mentions=s.mentions, vel24_disp=_vel24(s)[0], vel24_num=_vel24(s)[1],
                       surprise=s.surprise, themes_attr="|".join(s.themes or []),
                       authors=s.upvotes, pct_bull=int(s.pct_bull), price=s.price,
                       composite=s.composite, comp_list=_comp_list(s),
                       uoa=s.uoa, cramer=s.cramer,
                       pct_change=s.pct_change, emoji=_emoji(s.state)) for s in board],
        still_running=[dict(rank=i+1, ticker=s.ticker, name=s.name, mentions=s.mentions,
                            vel24_disp=_vel24(s)[0], vel24_num=_vel24(s)[1],
                            price=s.price, pct_change=s.pct_change,
                            days_running=(s.days_running or 0),
                            theme=(s.themes[0] if s.themes else ""),
                            themes_attr="|".join(s.themes or []),
                            css=_css(s.state), state_label=s.state.title())
                       for i, s in enumerate(still or [])],
        themes=(chips or ["All"]),
        cooling=[dict(ticker=s.ticker, surprise=s.surprise) for s in cooling],
        trend="0,50 60,48 120,40 160,30 200,8")

if __name__ == "__main__":
    sys.exit(main())
