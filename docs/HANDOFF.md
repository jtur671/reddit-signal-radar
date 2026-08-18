---
project: Reddit Signal Radar
doc: handoff / live state
phase: E — Deepen the signal
updated: 2026-08-17
owner: jason
tags: [handoff, reddit-signal-radar]
---

# HANDOFF — Phase E live state

> **[[ROADMAP]] is the shape. This doc is the state.** Roadmap changes when the plan
> changes; this changes every time something lands. If the two disagree, this one is
> right — then fix the roadmap.

**Read this first if you are picking the project up cold.** Everything below marked
`measured` was verified against the live source on the date shown. Everything marked
`assumed` was not — do not build on it without measuring. That distinction is the point
of this document.

---

## 1. Where things stand right now

| | |
|---|---|
| Branch | `fix/test-hermeticity` (ahead of `main`). `harden/audit-fixes` merged to `main` as `3934e78` |
| Prod | daily board + email 6:17 AM ET; 9-monitor fleet on a 30-min tick |
| Tests | **453 passed** (measured 2026-08-17 after E2a+E2; was 353/45.24s before this branch). Re-run rather than quote: `source .venv/bin/activate && python -m pytest` |
| Data branch | `origin/data` — 654 tickers, 76 daily snapshots, 8,364 ticker-days (measured 2026-08-17) |
| Backtest power gate | needs 150 days, has 76 → opens ≈ **2026-11-01** |
| Current phase | **E2 — Non-social attention: BUILT 2026-08-17, never run live.** Next action is verifying the first 6:17 AM run, §2 |

### ~~Open defect found during research (blocks E1)~~ — RESOLVED `e602bce`, see §5.

### Known, accepted, not a bug

Board breadth halved on **2026-08-08**: min raw mentions 5→10, names/day ~119→~54. That
is the Phase B `noise_floor.min_mentions` raise landing as designed. It does thin the
backtest's cross-sections, and it means the 2026-08-07/08 boundary marks **two**
simultaneous regime changes (composite merge + noise floor) — keep them distinct in
`regime_notes`.

---

## 2. Checklist — tick as it lands

Each item carries its **update hook**: the exact thing to do to this doc when it's done.
An item is not done until its hook has been run.

### E0 — Settle the cloud-IP question · **DONE 2026-08-17**

- [x] Run the probe — run [`32049892277`](https://github.com/jtur671/reddit-signal-radar/actions/runs/32049892277),
      results in §3. StockTwits ✅ (E3 unblocked), reddit RSS ❌ (dead from CI),
      all four E2 sources ✅.
      *Gotcha for next time:* a `workflow_dispatch`-only workflow is **invisible to
      `gh workflow run`** until it lands on the **default branch** — `gh` returns a bare
      `HTTP 404`. A branch+path-scoped `push:` trigger runs it from a feature branch
      without ever putting the file on `main`.
- [x] Delete `.github/workflows/probe-sources.yml` — see §5 for the recovery SHA.

### E1 — Catalyst layer · **landed 2026-08-17** (see §5); two follow-ups still open

- [x] Sign the `events` composite component
      **↪ hook:** strike the "Open defect" block in §1 and move it to §5 with the commit SHA.
      Done — struck in §1, full record in §5 (`e602bce`).
- [x] Write the spec → `docs/superpowers/specs/2026-08-17-catalyst-layer-design.md`
      **↪ hook:** link it here and in [[ROADMAP]]'s E1 block. Done.
- [x] Form-parameterized EDGAR monitor (`forms=` and `q=` from config)
- [x] Wire the four classes (`dilution` / `shelf` / `activist` / `delisting`)
- [x] Widen the watch gate to the full 90-day history
- [ ] **Measure real alert volume after 1 week live** and compare to the ~3.2/day estimate
      **↪ hook:** put the measured number in §4 next to the estimate. If it is 2× off,
      say so — a wrong estimate that goes uncorrected is how the next plan gets built wrong.
      **↪ hook:** add a `regime_notes` entry — a new alert class changes the `events`
      component, which changes every composite, which is a backtest regime boundary.
      Second hook done (`radar/backtest.py` `REGIME_NOTES`, dated 2026-08-17); the volume
      measurement itself is still outstanding — not enough days live yet.
- [ ] **EFTS paging (or narrowing the `bankruptcy` phrase).** `edgar8k`'s `"bankruptcy"`
      query returns a full 100-hit page every day (measured 127/188/197 hits over three
      consecutive 2-day windows, §4) — roughly half those 8-Ks are silently unseen.
      Pre-existing, not caused by this branch; the new catalyst classes are all
      comfortably under the cap. Paging itself is out of scope for this phase.
      **↪ hook:** if implemented, record it here and in §5, and re-measure §4's row.
- [x] Update [[ROADMAP]] decision log
      **↪ hook:** tick E1 in [[ROADMAP]], move this whole block to §5, set §1 phase to E2.
      Done.

### E2 — Non-social attention · **BUILT 2026-08-17**, not yet run live

- [x] Decide: new weighted components, or published-but-unweighted until the power gate
      **↪ hook:** record the decision and its reason in §5 — this one will be re-litigated.
      Done — **published-but-unweighted**, full reasoning in §5.
- [x] Specs written and approved: [[2026-08-17-ticker-article-mapping-design]] (E2a,
      the prerequisite) and [[2026-08-17-non-social-attention-design]] (E2).
- [x] **E2a — ticker→article mapping.** `radar/tickermap.py` + `radar/ticker_overrides.yml`
      (30 curated entries), `radar/about.py` rewritten to consume exact titles.
- [x] Wikimedia pageviews ingest — `radar/pageviews.py`, published as an unweighted
      `attention` component.
- [x] Short interest + days-to-cover ingest — `radar/short_interest.py`, FINRA consolidated,
      an `as_of`-stamped context field that is **not** a composite component.
- [ ] **Verify the first live run.** Nothing here has ever contacted Wikimedia or FINRA
      from the daily job — the whole suite is hermetic by design, so the first real
      exercise is the next 6:17 AM run.
      **↪ hook:** check `health.json`'s `sources` for `tickermap` / `wikimedia` / `finra_si`,
      confirm `data/ticker_articles.json` and `data/short_interest.json` landed on the
      `data` branch, and put the measured ticker-map coverage in §4 next to the 80.3%
      estimate. If the map resolves materially fewer than ~265 of 330 equities, say so.
      ~~**↪ hook:** if these become composite components, add a `regime_notes` entry~~ —
      **not triggered.** `attention` ships with no weight, so the composite value is
      bit-for-bit unchanged and the backtest series stays comparable. Short interest is
      not a component at all. If either is ever weighted, this hook comes back.

### E3 — Second attention source · ✅ unblocked 2026-08-17 (StockTwits answers CI)

- [ ] StockTwits ingest (board source + direction + `watchlist_count`)
      **↪ hook:** add `stocktwits` to `health.json`'s `sources` block and to the README's
      source list; add a footer LED. Every source the radar has does this — match it.

### E4 — Agent layer

- [ ] Spec the analyst/debate layer
      **↪ hook:** this one changes what the *product* is, not just the data. Re-read
      the "radar, not a trader" scope decision (2026-08-07 decision log) before writing it.

---

## 3. Endpoint status board

Everything here was measured from a **residential IP on 2026-08-17** unless stated.
Residential ≠ CI: the original raw-Reddit path died on exactly that gap.

| Endpoint | Residential | From CI | Verdict |
|---|---|---|---|
| ApeWisdom | 200 | **200 (prod, daily)** | in prod — the baseline everything else is judged against |
| Tradestie | 200 | **200 (prod, daily)** | in prod |
| EDGAR FTS `efts.sec.gov` | 200 | **200 (prod, fleet)** | in prod — accepts any `forms=` code |
| SEC `data.sec.gov` submissions | 200 | 200 (prod) | in prod |
| FINRA Reg SHO | — | 200 (prod) | in prod |
| CBOE chains | — | 200 (prod) | in prod |
| **StockTwits** stream + trending | 200, CF-fronted like ApeWisdom | **200 ✅** (70.9 KB / 86.0 KB, real JSON) | **E3 UNBLOCKED** |
| **reddit.com `/*.rss`** | 200, 1 req/60s per IP | **429 ❌** (`x-ratelimit-remaining: 0.0` on the *first* request; retried 65 s later, 429 again) | **dead from CI** — see below |
| reddit.com `/*.json` | — | **403** (confirmed again) | dead, do not retry |
| Wikimedia pageviews | 200 | **200 ✅** | E2 clear |
| Nasdaq short-interest | 200 | **200 ✅** (`server: Kestrel`, no CF) | E2 clear |
| FINRA consolidated short interest | 200 (CSV, keyless) | **200 ✅** | E2 clear |
| SEC FTD zip | 200 **only with a contact UA** (403 without) | **200 ✅** (1.65 MB) | context only |
| Polymarket Gamma / Kalshi | 200 / 200 | — | recorded, not recommended — ticker mapping unsolved |
| Bluesky `public.api.bsky.app` | **403** (needs free auth) | — | deferred |
| 4chan `/biz/` | 200 | — | **skip** — GME/BBBY/crypto zombies |
| Hacker News (Algolia) | 200 | — | **skip** as a ticker source |

**Probe run 2026-08-17: [`32049892277`](https://github.com/jtur671/reddit-signal-radar/actions/runs/32049892277).**
Two things it settled that were guesses before:

- **StockTwits answers a cloud IP.** Both endpoints returned real JSON payloads, not
  Cloudflare challenge pages (`{"symbol":{"id":2925,"symbol":"NVDA",...`). The
  ApeWisdom-posture argument held. E3 is a build decision now, not a research question.
- **Reddit RSS is dead from CI, and for a *different* reason than the JSON path.** JSON
  gives 403 (blocked); RSS gives **429 with `x-ratelimit-remaining: 0.0` on the very
  first request of the run** — the GitHub Actions IP range shares one Reddit bucket that
  is permanently exhausted by everyone else on it. Waiting 65 s did not help. This is not
  a back-off-harder problem: **do not design anything around reddit RSS from CI.** It
  works fine from a residential host at 1 req/min, so a self-hosted runner is the only
  path that could revive it.

---

## 4. Numbers to check against reality later

Every one of these is an estimate that a future session will be tempted to quote as
fact. Replace with a measurement when you can.

| Claim | Value | Basis | Replace when |
|---|---|---|---|
| Catalyst alerts/day, 90-day gate | ~3.2 unique tickers | EDGAR FTS ∩ history, 2026-08-10→14 | 1 week after E1 goes live |
| Catalyst alerts/day, 7-day gate | ~1.2 | same | — (not chosen) |
| Backtest power gate opens | ≈2026-11-01 | 76/150 days at 1/day | every backtest run |
| Board names/day (post-floor) | ~54 | history, 2026-08-08→17 | monthly |
| Reddit RSS budget | 1 req / ~60s / IP | `x-ratelimit-*` headers | if RSS is ever used |
| EFTS page cap | 100 hits | `len(hits)` vs `total` | if paging is added |
| Test suite | **465 passed / 3.7s** | measured 2026-08-17 on `fix/test-hermeticity` after the outsourced-review fix wave (was 446/2.36s after E2a+E2, 353/43.95s before the suite went hermetic, `b6b90ad`); 0 network violations under a socket blocker | every branch |
| Ticker-map coverage | 80.3% of the 330-equity universe (est.) | Wikidata US-scoped + 30 overrides; **never run live** | first live run |
| Catalyst/attention sources contacted live | **none yet** | the suite is hermetic by design, so no code path here has met the real APIs | first live run |
| Wikimedia D-1 availability at board time | ~02:30 UTC on D+1 (7.5 h before publish) | **inferred** from `dumps.wikimedia.org` rollup timestamps, 13/13 days 02:14–02:49 — *not* observed on the AQS API at 10:17 UTC | one fetch of D-1 at board time closes it. **Blast radius now bounded**: a board-wide stale tail costs the attention signal for that day but no longer trips the breaker or reds the `wikimedia` LED (see §5, 2026-08-17 fix wave) |
| Short-interest staleness | 11–24 days, sawtooth | measured 2026-08-17: latest settlement 2026-07-31, next (08-14) publishes 08-25 | every FINRA schedule change |
| `about.py` ticker→article wrong-entity rate | **13.7%** (34 of 249 resolved) | measured 2026-08-17 against `origin/data` `about.json`, 420 tickers | after E2a lands — target 0.4% |
| Ticker→article coverage | 59.3% of 420 → **80.3%** of the 330-equity universe | measured 2026-08-17; the other 90 are ETFs/crypto that cannot carry an exchange ticker statement | after E2a lands |
| `edgar8k` `"bankruptcy"` hits/day vs the 100-hit page cap | **127 / 188 / 197** over the monitor's real 2-day window (2026-08-11→12, 12→13, 13→14) | measured 2026-08-17 against `efts.sec.gov` | if EFTS paging is added or the phrase is narrowed |

**`edgar8k`'s `"bankruptcy"` phrase already exceeds the EFTS page cap every day, and
`parse_hits` only reads page 1.** The other two `edgar8k` phrases stay under the cap
(`"material definitive agreement"` 81/81/85, `"departure of directors"` 71/58/75, same
three windows). This is pre-existing — not caused by this branch — and it means roughly
half of `bankruptcy` 8-Ks are silently unseen by the monitor on a typical day. All four
new catalyst classes are comfortably under the cap (dilution 1, shelf 7, activist 9,
delisting 0, same measurement). See the follow-up in §2 and [[ROADMAP]] Phase E.

---

## 5. Landed (newest first)

Move completed checklist blocks here with the date and commit SHA. Keep it short — the
decision log in [[ROADMAP]] is where *why* lives; this is just *what*, so a future
session can tell "not done yet" from "done and reverted".

- **2026-08-17** — **Outsourced-review fix wave** on `fix/test-hermeticity`; **465 tests
  passing, 0 network violations**. Five findings, all verified against the code first:
  - `radar/pageviews.py` collapsed three outcomes into `None` — transport failure, a
    404, and the fail-closed stale-tail refusal — so all three fed one 3-strike breaker.
    Because D-1 availability at board time is *inferred* (see §4), an unpublished D-1
    would have refused on EVERY ticker, tripped the breaker on the third, dropped
    attention for the whole board, and lit `wikimedia` red for an outage that never
    happened. `_get_series` now returns a `MISS` sentinel (same shape as
    `options.py`'s `"missing"`); only transport failures count, and the LED keys on
    those rather than on `raw_views` being empty.
  - `radar/tickermap.py` tested an end-date for PRESENCE where the spec and its own
    docstring say *in the past*. A planned future delisting therefore read as ended, and
    where that statement was the correct current listing the ticker resolved cleanly to
    the WRONG article. `parse_rows` now takes `run_day`; an unparseable date fails
    toward omission, never toward a guess.
  - `radar/short_interest.py` skipped its truncation guard entirely when FINRA omitted
    the `record-total` header, vendoring a partial universe under the correct settlement
    date — which then matches the refresh gate and is served for up to two weeks.
    `_fetch_all_pages` now reports completeness explicitly instead of leaving the caller
    to infer it from `total is not None`; that inference *was* the bug.
  - Still Running names never got attention, though the E2 spec costs the ingest as
    "board plus Still Running" and the detail modal already renders `wiki views` for
    them. They are exactly the names where "is the wider world still looking?" carries
    information.

- **2026-08-17** — **E2a + E2 built.** Twelve fleet-facing commits on
  `fix/test-hermeticity`; **446 tests passing, 0 DNS lookups** under a socket blocker.
  New modules: `radar/tickermap.py`, `radar/pageviews.py`, `radar/short_interest.py`,
  `radar/ticker_overrides.yml`. `radar/about.py` no longer guesses titles from company
  names. `attention` joins `components` **with no weight**, so the composite value is
  unchanged and **this is not a regime boundary**.
  **What review caught that would otherwise have shipped** — recorded because each was a
  defect in the spec or plan, not in the implementation, and the same mistake is easy to
  repeat:
  - `radar/short_interest.py` would have shipped **inert**. Its discovery call returns
    HTTP 400 (FINRA rejects sorting without partition keys in an EQUAL filter), and its
    paging call omitted the settlement filter entirely, walking a >3M-row multi-year
    archive instead of the 22,341-row settlement.
  - The tickermap truncation guard could be bypassed: WDQS returning 200 with **zero**
    rows while `COUNT(*)` agreed at zero passed an equality-only check, overwriting the
    healthy snapshot with an empty map and serving it for 30 days with no warning.
  - Adding `attention: 0.10` to `config.yaml` while cutting `velocity` to 0.20 kept the
    weight sum at 1.0 and passed **all 392 tests**, silently re-pricing every composite.
    The guard had been aimed at `DEFAULT_WEIGHTS`, which production only reads as a
    fallback.
  - A test read **production cache state**: `daily.yml` restores `data/` before the pytest
    gate, so the first day a real ticker landed in `about.json` the gate would fail and
    **halt the daily publish** — no board, no email — until someone hand-edited the data
    branch.
  - An empty cache entry was a permanent hit, which made the entire 30-entry override
    file **inert** for any ticker cached before its override existed.
  - Two health LEDs could not tell the truth: `tickermap` could never read `down` (the
    overrides kept the map non-empty), and `wikimedia` read `down` when nothing had been
    *asked*, not when Wikimedia had failed.
  - Two tests were **tautological** — one compared a value against a string built from
    that same value, and one asserted nothing at all.
- **2026-08-17** — **E2 weighting decided: published-but-unweighted.** Recording the
  reasoning because the checklist warned this one gets re-litigated.
  **Short interest is excluded permanently** — measured 11–24 days stale, twice monthly
  (latest available on 2026-08-17 is the 2026-07-31 settlement; 2026-08-14 publishes
  2026-08-25). Inside a daily composite that is a fortnightly step function, and the
  backtest would misattribute each step to whichever day it landed on. It ships as an
  `as_of`-stamped context field.
  **`attention` (pageviews) is unweighted for now**, for two reasons — the second is the
  one that actually decides it:
  1. The power gate needs 150 days and has 76 (≈2026-11-01), so no measured weight exists.
  2. **The recalibration story this project has assumed since 2026-08-07 is false.**
     `radar/backtest.py`'s `_frames()` (`backtest.py:117`) emits the raw velocity engine
     score, not composite components; grepping that module for `components`,
     `short_ratio`, `cramer` or `composite` returns only the `REGIME_NOTES` strings.
     **Per-component ICs are computed nowhere in this repo.** So "recalibrate from
     measured ICs — a config change, not a code change" (stated in `radar/composite.py:5`,
     `config.yaml:111`, `README.md:66`) is wrong as written: changing a weight's *number*
     is config-only, but producing the measurement that justifies it does not exist and
     is a code change nobody has scoped.
  Mechanically this costs nothing: `composite.py:54` filters on `weights.get(k, 0) > 0`,
  so a component with no weight publishes in `data.json` and is dropped from the blend —
  no rebalance of the existing seven (`tests/test_run_smoke.py:51` pins the sum to 1.0),
  and **no regime boundary**, since the composite value is unchanged.
  **↪ follow-up:** building the per-component IC estimator is the prerequisite for ever
  weighting `attention`, and should correct that claim in all three files. The inputs are
  already persisted (`history.annotate` writes `ts_bull`, `short_ratio`, `pc_ratio`,
  `uoa`, `cramer` per ticker-day) — this is an estimator, not an ingest.
- **2026-08-17** — **E2 + E2a specs approved.** Research measured two things the roadmap
  had wrong. (a) Pageviews and short interest are **not peers** — 7.5 h fresh vs 11–24
  days stale — so they are specced as separate tiers, not one slot.
  (b) A prerequisite the roadmap did not see: `radar/about.py` maps ticker→article by
  guessing from ApeWisdom's company name, and the live cache on `origin/data` is 59.3%
  populated and **13.7% wrong-entity** — `AAPL`→the fruit, `ADBE`→a building material,
  `HTZ`→the SI unit, `SDGR`→a dead physicist, `ID`→Mount Everest. Cosmetic on the About
  modal today; a silent permanent signal inversion the moment pageviews consume it
  (`SDGR` would feed ~988 physics pageviews/day into a biotech score whose real value is
  41). Fixed by a Wikidata-derived exact-title map: precision 13.7% → 0.4% wrong, and it
  **fails closed** — `MVIS` resolves to nothing rather than a 1979 game console. Specs:
  [[2026-08-17-ticker-article-mapping-design]], [[2026-08-17-non-social-attention-design]].
- **2026-08-17** — **Test suite made hermetic** (`b6b90ad`, branch `fix/test-hermeticity`).
  353 passed 43.95 s → 0.95 s; 0 DNS lookups under a socket blocker. Guarded
  `radar.enrich._yf_quote` and `radar.about.fetch_summary` in a second autouse
  `tests/conftest.py` fixture, and stubbed FINRA + CBOE in
  `test_run_smoke.py::test_dry_run_writes_dashboard`. `tests/test_enrich.py` needed the
  real `_yf_quote` restored in four tests (a `sys.modules` fake does not undo a
  `setattr` on the module-level name); one of those four had been passing **vacuously**
  — it asserts `(None, None)`, exactly what the stub returned for any input, so it had
  silently stopped guarding the camelCase/snake_case distinction it exists for. See §6
  for the three false claims this replaced.
- **2026-08-17** — **E1 done.** Signed the `events` composite component (`bearish 0 /
  neutral 50 / bullish 100`, `None` when no fresh alert covers the ticker — was `100`/`0`
  with `0` doing double duty as both "bearish" and "no alert"), generalized the EDGAR
  full-text monitor to take `forms=`/`q=` from config instead of hardcoding `8-K`, and
  wired four new classes watching the full 90-day history: `dilution` (424B5, "at the
  market offering", bearish), `shelf` (S-3/S-3ASR, "offering", neutral), `activist`
  (SCHEDULE 13D, "common stock", bullish), `delisting` (25-NSE, "delisting", bearish);
  `edgar8k` keeps its own 7-day gate. Fleet: five monitors → nine (`trump, edgar, fed,
  congress, edgar8k, dilution, shelf, activist, delisting`). `radar/backtest.py`
  `REGIME_NOTES` stamped 2026-08-17 — every composite before/after is incomparable.
  Tests: 351 passing (was 327). Commits: `c85e5a0` (monitor direction), `e602bce`
  (signed events component), `68897a7` (accession dedup), `d46ce3c` + `c8f094e`
  (form-parameterize + fix round), `de2456b` (wire the four classes). Spec:
  [[2026-08-17-catalyst-layer-design]]. Not landed yet: measuring real alert volume
  after 1 week live (§2, §4).
- **2026-08-17** — **Open defect (blocked E1) resolved**, commit `e602bce`.
  `radar/composite.py:43` previously read `"events": 100.0 if s.ticker in alert_tickers
  else 0.0`, and `radar/run.py:154` built `alert_tickers` as a flat set across all
  monitors, discarding which monitor fired — so a 424B5 dilution or a 25-NSE delisting
  would have scored **+100**, the same as a bullish insider buy, and the catalyst layer
  would have ranked a diluting company *higher* for diluting. Fixed by signing `events`
  per monitor direction (see the E1 entry above). Struck from §1.

- **2026-08-17** — **E0 done.** Probe run
  [`32049892277`](https://github.com/jtur671/reddit-signal-radar/actions/runs/32049892277)
  settled the cloud-IP question (§3): StockTwits ✅, reddit RSS ❌, E2 sources ✅.
  Throwaway workflow then deleted — **recover it with
  `git show eea74f0:.github/workflows/probe-sources.yml`** if you need to re-probe.
- **2026-08-17** — Community-mining research pass; [[2026-08-17-community-mining]],
  Phase E added to [[ROADMAP]], this doc created (`849134c`).
- **2026-08-17** — Security-audit fixes (`f5fae9e`): URL scheme allowlist, CI secret
  blast radius, SHA-pinned actions.

---

## 6. House rules a new session will otherwise violate

- **Accepted risks on the three new E2 sources** — measured 2026-08-18 during the QA
  game-day pass. None is a defect; all are things a future session would otherwise
  rediscover the hard way.
  - **Wikimedia D-1 unpublished at board time ⇒ attention blank BOARD-WIDE, LED stays
    GREEN**, one warn, status `degraded`, **no email**. §4 records the *cause* as
    inferred; this is the *consequence*. The board looks entirely normal with an empty
    attn column. Traced end-to-end, not guessed.
  - **No outage of the three new sources can ever reach `severe`**, and only `severe`
    emails. All three could be dark for a month with `health.json` and a footer LED as
    the sole surface. Consistent with `finra`/`cboe`/`cramer` — a deliberate policy,
    recorded as one.
  - **`spike_score` uses 28 *consecutive calendar* days** while the board runs 7 days a
    week, so weekend attention is systematically depressed against a weekday-dominated
    median. Cosmetic while `attention` is unweighted; **a real bias the moment the IC
    follow-up weights it.** Magnitude unmeasured.
  - **Day 1 after merge shrinks `data/about.json` from 420 entries to ~15–20**, because
    only board + Still Running names get described. Correct by design (the schema bump
    discards a cache that was 13.7% wrong-entity *hits*), invisible to users — but a 20×
    file shrink on the data branch will look like data loss to whoever sees it first.
  - **`_latest_settlement` trusts `availablePartitions[0]` to be newest-first** with no
    bound. If FINRA reorders, the job vendors an old settlement and the short-circuit
    serves it indefinitely. Fails *visibly* (`as_of` always renders), so a risk, not a
    defect. `latest <= run_day` is one line if it ever bites.
  - **`days_to_cover` is set only for board names, never for Still Running**, while
    `attention` covers both — so the Still Running modal can never show days-to-cover.
  - **The gate has never run on Python 3.11**, which is what CI pins; only 3.12 exists
    locally. `ast.parse(feature_version=(3,11))` is clean across every file and no
    3.12-only stdlib API is used — **syntax closed, semantics not.**
  - **Disk is a non-issue, measured:** the whole `data` branch packs to **0.7 MB from
    29.2 MB raw** (git deltas `history.json` to ~12 KB/version); both new snapshots add
    **≤6.8 MB/yr** worst case. Recorded so it stops being re-litigated.

- **Six production-state readers are still unguarded, and the guard is enumerated rather
  than enforced.** `tests/conftest.py`'s `_no_production_state` names its readers one by
  one. The same Critical has now landed **twice** on this branch — once for `about.json`,
  once for the two new snapshots — so a seventh reader arriving uncovered is a demonstrated
  risk, not a hypothetical one.
  Measured 2026-08-17 by instrumenting `Path.read_text` and `open` across the whole suite
  with CI-restored `data/`, the currently-unguarded reads are:
  `data/history.json` (`run.py` `History.load`, 46 reads) and the five
  `data/*_alert.json` files via `_load_alerts`' glob (23 reads each).
  They do **not** break the gate today — 453 passed with all of it present — because alert
  cards are age-gated by `alert_is_fresh` and nothing asserts on sparkline content. That is
  a property of today's assertions, not a guarantee.
  `data/cramer_snapshot.json` is a declared `snapshot_path` with no guard too; it escapes
  only because `fetch_cramer` is skipped under `--dry-run`.
  **↪ the fix, and why the obvious version is too weak:** a session-scoped plugin that wraps
  `Path.read_text`/`open`, derives the production-state set from **`.gitignore`'s `data/`
  entries** (the maintained source of truth for generated state), and asserts the observed
  reads are within an explicit allowlist. Deriving from `config.yaml`'s `snapshot_path`
  values instead is ~6 lines but strictly weaker — it would have missed `about.json`, the
  *first* occurrence of this bug, because `run.py` hardcodes that path and config never
  declares it. Measured against today's suite the interceptor gives zero false positives
  and six true positives.

- **Bot state lives on the orphan `data` branch, not `main`.** Local `data/` is stale.
  `git fetch origin data && git checkout origin/data -- data/` before reasoning about
  real state. Committing state to `main` is a regression.
- **Every source fails soft and reports itself** in `health.json`'s `sources` block
  (`ok`/`down`/`fallback`/`unused`) plus a footer LED. A new source that can take the
  run down, or that fails silently, is not finished.
- **Third-party GitHub JSON feeds get vendored** to the data branch with a dated
  snapshot (see `cramer_snapshot.json`) so the signal survives upstream deletion.
  Both feeds already in prod (`cramer`, `congress`) follow this.
- **GitHub Actions are pinned to commit SHAs, not tags** — those runners hold every
  repo secret.
- **Anything that changes a composite component is a backtest regime boundary.** Add a
  dated `regime_notes` entry, or the backtest silently compares incomparable periods.
- **Never quote a test count, ticker count, or date you did not run a command for.**
  This project's docs have been wrong that way before; the tables above exist so the
  next session measures instead of remembering.
- ~~**The test suite makes live network calls, and it gates the daily publish.**~~
  **FIXED 2026-08-17, `b6b90ad`** — and the entry that stood here was wrong in three
  ways, which is worth recording because a future session would have built on it:
  - It said the **Cramer feed** was live. It was not. `radar/run.py:138` reads
    `fetch_cramer(cfg, run_day) if not args.dry_run else {}` and every test passes
    `--dry-run`, so it was never reachable.
  - It **missed Wikipedia entirely** — `run.py:79/81` → `about.describe` →
    `en.wikipedia.org`, and `data/about.json` is gitignored so the cache is always
    empty and every board ticker was a live fetch. This was the larger of the two
    real callers.
  - It named only `tests/test_run_cboe.py`. `tests/test_run_smoke.py::test_dry_run_writes_dashboard`
    was worse, leaving **FINRA and CBOE** live too — while its own inline comment
    claimed "no live network in tests".

  Measured before/after: **353 passed 43.95 s → 353 passed 0.95 s**, and a socket
  blocker now reports **0 DNS lookups** (validated against the pristine tree as a
  control, where the same blocker fails the smoke test). The guard is a second autouse
  fixture in `tests/conftest.py`.

  **Still true, still unfixed** — these are production stall risks, not test ones, and
  they are what could actually delay the 6:17 AM publish. `daily.yml` runs pytest as a
  gate with no `timeout:`, so a hung suite hangs the job. **Nine** modules (not five)
  use real `time.sleep` exponential backoff: `apewisdom`, `fetch`, `shorts`, `cramer`,
  `news`, `tradestie`, `options`, `trump`, `monitors/edgar`. Of those, `shorts`,
  `cramer`, `news` and `trump` **discard the `sleep_s`/`retries` knobs their own helpers
  expose** (the callers never pass them), so they have no config-side brake at all. And
  `radar/enrich.py:7` calls yfinance with **no timeout whatsoever** — that, not backoff,
  is the likeliest cause of the 786 s window recorded earlier.
