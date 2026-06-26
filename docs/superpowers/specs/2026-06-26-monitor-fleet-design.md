---
project: Reddit Signal Radar
feature: Monitor Fleet (generalize the Trump tripwire) + EDGAR insider-buy monitor
status: design — approved, pre-implementation
created: 2026-06-26
tags: [spec, reddit-signal-radar, monitors, edgar]
supersedes-roadmap: "Phase: expand scope → more monitors (like Trump)"
---

# Monitor Fleet — Design

## Summary

Generalize the existing one-off Trump Truth Social tripwire into a small **monitor
framework** that any number of source-watchers plug into, then ship the **first new
monitor — a market-wide SEC EDGAR insider-buy tripwire** — on top of it. The Trump
monitor is re-homed onto the framework with **zero behavior change** (its tests are the
proof). The framework supports two source shapes from day one:

- **Prose monitors** — RSS text where the ticker must be *inferred* (cashtag + curated
  name map), then confirmed by a DeepSeek semantic gate. *(Trump today; Fed / Musk later.)*
- **Structured monitors** — feeds where the ticker is an explicit field and the rule is a
  threshold, so **no LLM inference** is needed. *(EDGAR now; Congress later.)*

**Spec 1 delivers:** the framework, Trump re-homed, and a live EDGAR insider-buy monitor.
Fed/Powell, Congressional trades, Musk, and EDGAR 8-K/13-D are **deferred to their own
follow-on specs** (the decomposition that keeps this spec shippable).

## Goals / Non-goals

**Goals**
- One reusable `Monitor` contract + shared runner; adding a monitor never adds a workflow.
- Both prose and structured detection paths real and tested on day one.
- Trump re-home is behavior-preserving (existing tests pass untouched).
- A working, market-wide EDGAR insider-buy alert end-to-end (detect → alert file → email →
  dashboard card).

**Non-goals**
- Not a trader. This stays a *radar*: publish/notify only. (Project-wide boundary.)
- No paid/authenticated sources in this spec (X/Twitter is out; EDGAR & friends are free).
- No multi-alert-per-monitor flooding — each monitor emits **at most one** alert per tick.

## Architecture

New package `radar/monitors/`:

```
radar/monitors/
  __init__.py        # REGISTRY: list[Monitor] the fleet runs (trump, edgar)
  base.py            # Signal dataclass + Monitor protocol + run_fleet() + shared cursor/alert/freshness
  prose.py           # ProseMonitor  (RSS text → cashtag/watch_map → needs LLM validation)
  edgar.py           # EdgarMonitor  (structured Form-4 records → ticker is a field)
```

### Contract

```python
@dataclass
class Signal:
    tickers: list[str]
    summary: str        # one-line human text for the card + email
    url: str
    published: str      # ISO-8601 'Z'
    monitor_key: str

class Monitor(Protocol):
    key: str                    # "trump", "edgar" — namespaces its data files (data/<key>_*.json)
    label: str                  # card title, e.g. "Trump named a ticker"
    card_style: str             # dashboard card color/kind
    needs_llm_validation: bool  # prose=True, structured=False
    max_age_h: int              # per-monitor freshness window
    def fetch_new(self, seen: set[str]) -> tuple[list[Signal], set[str]]:
        """Fetch source, skip seen ids, return (new signals, all-evaluated ids)."""
```

### Shared runner — `run_fleet(monitors) -> bool`

For each monitor, uniformly:

1. `seen = load_seen(data/<key>_seen.json)`
2. `signals, evaluated = monitor.fetch_new(seen)`
3. `save_seen` **only if** the cursor changed (no-op runs don't churn git).
4. If `monitor.needs_llm_validation`: run each signal's tickers through the DeepSeek gate
   (`validate_prose_tickers`). **Fails open** — an LLM outage keeps candidates, never
   suppresses a real alert. Structured monitors skip this entirely.
5. Pick the **single most-salient** surviving signal (prose: most recent; structured:
   largest $). Write `data/<key>_alert.json`, stamped with detection time.
6. `send_monitor_alert(signal, monitor)` — best-effort; never crashes the run.
7. Record whether this monitor fired.

Returns `True` if **any** monitor fired (drives the workflow's conditional rebuild).

### Two detector families

- **`ProseMonitor(key, label, feed_url, watch_map_path, card_style, max_age_h)`** —
  `needs_llm_validation = True`. Calls the existing `radar/trump.py` parsing/detection
  (RSS parse, `detect_tickers` via cashtag + watch_map, dedup). Trump is one instance;
  Fed and Musk later are new instances (config rows, ~no new code).
- **`EdgarMonitor`** — `needs_llm_validation = False`. Real adapter (see below).

## Shared infrastructure (promoted from `trump.py` into `base.py`)

These already exist in generic form inside `trump.py`; they move to `base.py`, keyed by
`monitor.key`:

- **Dedup cursors** — `load_seen` / `save_seen` → `data/<key>_seen.json`. Trump's file path
  is unchanged. "Save only when changed" preserved.
- **Alert store** — each monitor writes `data/<key>_alert.json` (Trump's unchanged).
  `alert_is_fresh` takes a **per-monitor `max_age_h`** (Trump = 48h; EDGAR shorter — a
  stale filing isn't news). Dashboard **globs `data/*_alert.json`** and keeps only fresh.
- **Email** — `send_trump_alert` → `send_monitor_alert(signal, monitor)`: subject/body from
  `monitor.label` + `Signal`, not a hardcoded string. Prose body renders the quoted post;
  structured body renders filing facts (insider role, $ size, form type). Resilience
  contract unchanged (best-effort, fail-open).
- **Dashboard multi-card** — `run.py` builds a **list** of fresh alert view-models instead
  of one `alert`. Template swaps `{% if alert %}` for `{% for alert in alerts %}`, each card
  colored by `alert.card_style`, titled by `alert.label`, sorted newest-first. Zero alerts →
  no cards (today's quiet-day behavior). Globbing means a future monitor's card appears with
  **no render-code change**.

## The two monitors in spec 1

### A) Trump re-home — zero behavior change

```python
ProseMonitor(
    key="trump", label="Trump named a ticker", card_style="trump",
    feed_url="https://www.trumpstruth.org/feed",
    watch_map_path="data/trump_watch.yaml",
    needs_llm_validation=True, max_age_h=48,
)
```

The only generalization: `validate_trump_tickers(text, candidates)` →
`validate_prose_tickers(text, candidates, source_context)`, with Trump passing
`source_context="Donald Trump on Truth Social"`. Same DeepSeek gate, same fail-open.

**Acceptance bar:** `test_trump.py` and the email/render tests pass **unchanged**. If a
test needs editing, the re-home went too far.

### B) EDGAR insider-buy monitor — the new structured path

- **Source:** SEC EDGAR free, no-auth "latest filings" Atom feed filtered to **Form 4**,
  then each filing's ownership XML for structured fields. SEC requires a declared
  `User-Agent` with a contact email and caps ~10 req/s — both trivially met at 30-min
  cadence.
- **Detection rule (no LLM):** keep open-market **purchases** (transaction code `P`) above
  a configurable dollar size. Ticker comes from the filing's `issuerTradingSymbol` →
  `needs_llm_validation = False`. **No universe restriction** — fires market-wide (a
  discovery tripwire, not just a board confirmer).
- **Noise control (since market-wide):** `min_usd` is the gate (set high — cluster/large
  buys, not routine top-ups), and **one alert per tick ranked by largest $** structurally
  caps volume to a single card no matter how many filings qualify. All evaluated accession
  numbers still enter the cursor, so nothing re-alerts.
- **Dedup:** EDGAR **accession number** is the stable id.
- **Signal:** `summary` ≈ *"Insider buy — Director bought ~$1.2M of $XYZ (Form 4)"*,
  `url` = filing, `published` = filing timestamp.
- **Config** (`config.yaml`, new `edgar:` block):
  ```yaml
  edgar:
    forms: [4]
    transaction_codes: [P]
    min_usd: 1000000          # tune from observed volume
    restrict_to_universe: false
    max_age_h: 24
    user_agent: "reddit-signal-radar/0.1 (contact: <email>)"
  ```
- **Card style:** distinct from Trump's red — an insider *buy* is bullish, so green/gold.

## Workflow

`trump-monitor.yml` → **`fleet-monitor.yml`** (same 30-min cron, same cheap "rebuild only
if something fired" model). One step runs `python -m radar.monitor`, which calls
`run_fleet(REGISTRY)` over `[trump, edgar]`. The commit step's `git add` includes
`data/edgar_*.json`. Rebuild + deploy fires if `run_fleet` returned any-fired. **Still one
workflow, one tick, one conditional rebuild** — adding monitors never adds workflows.

## Testing

Mirrors the existing suite (pure parsing + fixtures, no live network):

- `test_edgar.py` — captured Form-4 Atom + ownership-XML fixtures → assert ticker /
  transaction-code / $-size extraction, threshold filtering, largest-buy salience pick,
  accession-number dedup.
- `test_monitors_base.py` — `run_fleet` over a fake 2-monitor registry: cursor load/save,
  fail-open validation, alert-file write, "any fired → rebuild" signal.
- `test_render.py` / `test_email.py` — extend for the multi-card loop and
  `send_monitor_alert`; assert Trump's existing single-card output is byte-stable.
- **Regression gate:** `test_trump.py` passes untouched.

## Deferred to follow-on specs (decomposition)

- **Fed / Powell** — `ProseMonitor` on federalreserve.gov RSS + a Fed watch map. Mostly config.
- **Congressional trades** — second structured adapter (STOCK Act disclosures), `EdgarMonitor`-shaped.
- **Musk / other figures** — `ProseMonitor` instances pending a viable free feed (X is paid).
- **EDGAR 8-K / 13-D** — more form types on the existing adapter.

## Risks / open items

- **EDGAR volume unknown** — `min_usd` default ($1M) is a guess; tune from the first days of
  real filings (same burn-in discipline as the original noise floor).
- **EDGAR fetch cost** — Form-4 Atom + per-filing XML is N+1 requests; stay under SEC's
  ~10 req/s with the existing retry/backoff helper. Cap filings examined per tick.
- **`source_context` equivalence** — the generalized prose validator must produce the same
  verdicts for Trump as today; guarded by `test_trump.py` (LLM mocked).

## Decision log

- **2026-06-26** — Chose framework-first (Approach A) over copy-the-pattern (B) and
  config-only (C); prose monitors are config rows, structured monitors get adapter classes.
  EDGAR chosen as the first new monitor to force the structured/no-LLM path to be real on
  day one. **No universe restriction on EDGAR** (owner decision) → market-wide discovery
  tripwire, noise controlled by `min_usd` + one-salient-alert-per-tick. Form-4 only for v1.
</content>
</invoke>
