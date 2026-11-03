# PREREG_RVOL_ORB: the RVOL-ranked five-minute opening-range breakout, long only, on the Massive flat files

Status: DRAFT (awaiting the owner's freeze)
Date: 2026-11-03
Author: drafted by Fable for the owner
Lives at: docs/PREREG_RVOL_ORB.md in /home/axis/Mjonir-DayTrader (plan step 3.3; the runner is step 3.5)

## 1. The freeze

This document is frozen by the owner's word, nothing else. The procedure:

0. Commit D0: this document is committed with the DRAFT status line BEFORE any commit that adds `tools/rvol_study.py` or the `rvol` subcommand of `scan.py`.
1. After D0 the runner and the scanner may be built, but until the freeze the runner runs ONLY in `--counts-only` mode (section 10), which prints counts and never a price, a volume, a first-bar direction or an outcome. The lead pastes those counts into section 10 as the last pre-freeze edit. Then the owner reads the draft and says "freeze" (or edits it first, then says so). Until then the status line reads exactly `Status: DRAFT (awaiting the owner's freeze)`.
2. Commit F1: the lead changes the status line to `Status: FROZEN (commit pending)` and adds one line under it, `Frozen by the owner's word on <date>`. Nothing else in the file changes in F1.
3. Commit F2, immediately after: the status line becomes `Status: FROZEN (commit <hash of F1>)`. Nothing else changes in F2. A commit cannot carry its own hash, so the hash of F1 is the freeze hash and F2 only records it.
4. From F2 on, the only section of this file that may change is section 13 (Postscripts), each entry dated. Any other change makes the runner refuse.

The runner (`tools/rvol_study.py`) refuses to open any data file unless all of these hold: the status line matches `Status: FROZEN (commit [0-9a-f]{7,40})`; `git cat-file -e <hash>` succeeds; the hash is in `git log --format=%H -- docs/PREREG_RVOL_ORB.md`; `git show <hash>:docs/PREREG_RVOL_ORB.md` is identical to the working file once the status line and section 13 are removed from both; and `git status --porcelain docs/PREREG_RVOL_ORB.md` is empty. The refusal names the first failed check and exits 1 before any flat file, cache file or API endpoint is touched; `--counts-only` is the one mode exempt from these checks. The reviewer of chunk 3 checks `git log` order: D0 predates every commit that adds or changes `tools/rvol_study.py` or the `rvol` subcommand of `scan.py`, and no scoring run's report exists before F2.

## 2. Hypothesis and prior

### 2.1 The source

Zarattini, Barbon and Aziz (2024), "A Profitable Day Trading Strategy For The U.S. Equity Market", SSRN 4729284. As this prereg reads the paper (the paper's text governs where a recollection below differs; the builder verifies these points against the paper before the freeze and corrects them here): on every session the authors rank the US equity universe by the relative volume of the first five-minute bar against the same bar's average over the prior fourteen sessions; the twenty highest are the "stocks in play"; each is traded in the direction of its first five-minute bar (close above open: long; close below open: short; a doji: no trade), entered at the start of the second bar; the stop is one tenth of the fourteen-day average true range; the position is closed at the session's close if the stop was not hit; risk is equal per trade; the sample is 2016 to 2023; the paper's filters are a price floor, a share-volume floor and an ATR floor, and its costs are a per-share commission without a slippage or spread model. The paper reports positive net returns and a high Sharpe ratio. Its predecessor on an index ETF is Zarattini and Aziz (2023), SSRN 4416622.

### 2.2 The house's prior reading

What the box holds on this paper, found by grep for "Zarattini", "stocks in play", "4729284" and "4416622" over ~/Odyssey (NewResearch.md, docs/, HANDOFF.md), ~/Infinit/docs, ~/Kalex/docs and the Odyssey memory notes:

- `/home/axis/Odyssey/NewResearch.md:334`: the paper's row, graded C, "day horizon", "not a swing result"; the thirty-minute-bar analogue is listed as unmeasured and needing a coverage audit. Lines 897 to 899 hold the citations. Nothing else in Odyssey names it.
- `/home/axis/.claude/projects/-home-axis-Odyssey/memory/day-trader-skill-review-2026-11-02.md:30`: the review that led to this fork lists the RVOL rank as tailoring 5 and adds, in parentheses, "the index replication read net zero".
- No document, ledger row, artifact or number on disk carries that replication. The phrase is a recollection in a memory note, not a record. This prereg therefore does not cite a house number against the paper; the house prior is unverified on this hypothesis.

What the house does hold, and what this prereg's expectation rests on: the ENTRY-EDGE programme (Odyssey HANDOFF section 7eo; memory note `entry-edge-programme`) found that no daily-bar entry beat a matched random-entry control on its own names and that breakout deficits were "buying strength"; the pack's own TSLA opening-range history, scored net of the house costs in chunk 2 (docs/reviews/chunk2.md), read below zero at a sample under the fire floor, "cannot judge". The expectation going in is a kill with structure. The expectation is not a result and sets no threshold.

### 2.3 H0 and H1, in the machinery's terms

Every outcome in this study is computed by `mjonir.outcomes.score_trade`, every interval by `mjonir.stats.expectancy_ci` or `mjonir.stats.paired_delta_ci`, every state by `mjonir.stats.verdict_history` or `mjonir.stats.verdict_control`, every cost by `mjonir.costs.trade_cost_r`, every control draw by `mjonir.control.draw_controls`. The study adds no new estimator.

- H1: on the development window (section 7), the PRIMARY rule (section 4) yields `verdict_history.state == "pass"` on the net R of all its fires (the interval's `lo` above zero at `n` at or above `N_FLOOR`) and `verdict_control.state == "pass"` on the paired delta against the matched random-entry control (section 6), and the sign conditions of section 8 hold.
- H0: any of those states is not `pass`: the net expectancy interval includes or sits below zero, or the delta against the control includes or sits below zero, or the sample is under the floor.

The test is one-sided in the paper's direction. A result on the other side (a rule that loses to its own control with an interval below zero) is informative and is recorded, but it is post-hoc for any trading use: see section 9.

## 3. Universe and point-in-time construction

### 3.1 Data sources, all read-only

- Minute bars: `/home/axis/Infinit/data/polygon/minute_flatfiles/YYYY-MM-DD.csv.gz`, one file per session, every US ticker, columns `ticker,volume,open,close,high,low,window_start,transactions`, `window_start` in nanoseconds since the epoch (the minute's start), NOT split-adjusted. Verified 2026-11-03 from the first file's header and first row and the directory listing: files from 2021-01-04 to 2026-08-04, 1,402 files, 8.8 to 29.9 MB gzipped each.
- Daily bars: `/home/axis/Infinit/data/polygon/flatfiles_cache/YYYY-MM-DD.csv.gz`, the same columns and the same vendor, one row per ticker per session, `window_start` at midnight ET of the session, NOT split-adjusted. Verified 2026-11-03: 5,823 files from 2003-09-10 to 2026-10-30; every minute-file date has a daily file; the sessions before the development window that the lookbacks need are present.
- The Massive API (the box key in `~/Infinit/.env`, through `mjonir.massive.Client`), for two reference tables only: `/v3/reference/tickers` with `date=` (the as-of list) and `/v3/reference/splits`. No aggregates are fetched: the flat files are the bars. No options, no `I:` indices, no Benzinga. Both endpoint shapes were confirmed on 2026-11-03 through the MCP connector with two-row pages: the as-of list answers `ticker,name,market,locale,primary_exchange,type,active,...`; the splits list answers `execution_date,id,split_from,split_to,ticker`.
- EXCLUDED: the Kalex five-minute store (777 names, survivor-tilted), the Massive aggregates (adjusted, a different basis from the flat files), Yahoo.

### 3.2 The point-in-time list: what counts as a stock on day D

Chosen: one as-of reference walk per calendar month. On the first session of each month M, two walks: `GET /v3/reference/tickers?market=stocks&active=true&type=CS&date=<that session>&limit=1000` and the same with `type=ADRC`, every page followed and checked by `mjonir.massive.check_reference` (P11: a short walk, an overlapped cursor, an ignored filter or a count under the sanity floor is a refusal). The union of the two walks is the type list for every session of month M. Each walk is cached once as `trader/data/rvol/reference/<YYYY-MM>-<type>.json` (gitignored) with the request date and the row count; a re-run reads the cache. Cost: 68 months across both windows, about 7 pages a month (about 5,400 CS rows and about 390 ADRC rows a walk at the current count), about 480 requests in all.

Why monthly, not daily: a daily walk costs about 9,800 requests for a difference the history floors make moot. A name that lists inside the month cannot clear the ADV window (section 3.3) until about the next walk anyway, so at most a few sessions a year are lost; a name that delists inside the month has no rows in the day files after its last print and is never a candidate. Survivorship is handled by the day files' own content: every ticker that printed on a session is in that session's file, whatever happened to it later. The as-of list supplies only the type (common stock or ADR) as the vendor recorded it that month. Residuals accepted and invisible: a symbol reused by a different issuer inside one month; a type change inside one month.

Why not the flat files' ticker set with a current type map: a current map labels a recycled symbol with today's holder's type and misses the names that were delisted before the map was taken unless an `active=false` walk is added; the as-of walk is the vendor's own answer to "what was this symbol on that date".

ADRs: included (type `ADRC`), the same choice as `mjonir.universe.DEFAULT_TYPES`, so the study's universe is the desk's universe. Everything else (ETFs, funds, preferreds, units, rights, warrants, OTC) is out: `market=stocks` excludes OTC, and the two type walks exclude the rest. Also applied: the ticker rule `mjonir.universe.TICKER` (one to five letters, or one to four letters, a dot and one class letter), upstream's own, so a symbol the desk's scanner cannot read never enters the study.

### 3.3 The floors, strictly from data before D

From the daily cache rows of the ADV window (the `ADV_N` sessions strictly before D, section 4.1), all of which must be present with a positive volume, else the name-day is excluded and counted `insufficient_history`:

- price: the close of the session before D at or above `P_MIN`;
- dollar liquidity: the mean of close times volume over the ADV window at or above `ADV_USD_MIN` (this same mean is the ADV used by the cost tier);
- share liquidity: the mean of volume over the ADV window at or above `ADV_SH_MIN` (the paper's own floor, as recalled).

No row of session D is read for eligibility. The day's own first bar enters only the ranking and the trade.

### 3.4 Splits in unadjusted data

Chosen: exclusion, not adjustment. One walk of `/v3/reference/splits?execution_date.gte=<the first session of the pre-window lookback>&execution_date.lte=<the last holdout session>&limit=1000&sort=execution_date&order=asc` (all tickers), every page followed, cached once as `trader/data/rvol/splits.json`; its row count is an availability count (section 10). A name-day is excluded and counted `split_guard` when any split row for that ticker has an execution date inside the window `SPLIT_GUARD` (section 4.1): the ADV window plus the session itself. That window covers every lookback this study uses (the ADV window contains the ATR rows and the RVOL history), so no lookback of a kept name-day spans a split, and no name whose own session is a split day is traded on that day.

Why exclusion: an adjustment needs the ratio applied to prices one way and to volumes the other way, and a decision about the vendor's rounding; a kept name-day with an unadjusted split would print a share volume multiplied by the ratio, which is exactly what a relative-volume rank would mistake for a stock in play (the first row of the splits list on the window's first session is a 170-for-1 reverse split). Exclusion is auditable and counted, and it touches a small share of name-days.

A second, loose guard for splits the reference table missed and for bad prints: a name-day is excluded and counted `gap_guard` when the first bar's open is outside `GAP_GUARD` times the prior session's close. The residual, stated: a missed two-for-one or three-for-two split passes this guard; its effect is a doubled RVOL and a wrong ATR for that name for the ADV window, and nothing in this study can see it. The exclusion counts by cause go in the report.

## 4. The PRIMARY rule, frozen to the parameter

### 4.1 Every parameter, written once

| name | value | where it acts |
| --- | --- | --- |
| `P_MIN` | 5.00 USD (the close of the session before D) | eligibility |
| `ADV_USD_MIN` | 20,000,000 USD (mean of close times volume over the ADV window) | eligibility, cost tier |
| `ADV_SH_MIN` | 1,000,000 shares (mean of volume over the ADV window) | eligibility |
| `ADV_N` (the ADV window) | 20 sessions strictly before D | eligibility, split guard |
| `RVOL_N` | 14 sessions strictly before D | the RVOL denominator |
| `ATR_N` | 14 daily true ranges, from 15 daily rows strictly before D | the stop |
| `TOP_K` | 20 | the ranking |
| `STOP_ATR_FRAC` | 0.10 | the stop |
| `RISK_FLOOR_PCT` | 0.05 percent of the entry | the stop |
| `FLAT_BY` | 15:55 ET; 12:55 ET on a 13:00 early close | the exit |
| `SPLIT_GUARD` | any split executed inside [the first session of the ADV window, D] | eligibility |
| `GAP_GUARD` | the first bar's open under 0.4 or over 2.5 times the prior close | eligibility |
| `COST_TIERS` | [[100,000,000, 4], [30,000,000, 8], [0, 15]] bp a side by ADV in USD (Kalex's tiers, `mjonir.costs.DEFAULTS`) | costs |
| `HALF_SPREAD` | 3.0 bp a side (`default_half_spread_bps`; no NBBO history in this study) | costs |
| `COMMISSION` | 1.00 USD a side, spread over the shares basis | costs |
| `SHARES_BASIS` | floor(1,000 USD / risk a share), at least 1 (`mjonir.costs.shares_basis`: the 100,000 USD notional at a 1 percent max loss) | costs |
| `SLIP_X2` | the tiers doubled: [[100,000,000, 8], [30,000,000, 16], [0, 30]]; spread and commission unchanged | sensitivity only |
| `CONTROL_K` | 3 draws a fire | the control |
| `SEED` | 19 | every bootstrap and every control generator |
| `DRAWS` | 2,000 | every bootstrap |
| `LEVEL` | 95 percent percentile interval (`mjonir.stats.LEVEL`) | every interval |
| `N_FLOOR` | 40 (`mjonir.stats.N_FLOOR`) | every verdict |
| `FRAGILE_R` | 0.05 R (`mjonir.outcomes.FRAGILE_R`) | disclosure |
| `TICK` | 0.01 USD | the one-tick sensitivity |
| `ARM_TARGETS` | 1R and 2R | the exploratory arms |
| `OR15_MIN` | 15 minutes (three five-minute bars) | arm A |
| `NO_ENTRIES_AFTER` | 15:30 ET; 12:30 ET on an early close (upstream's `entry.py` default) | arm A |
| `GATE_N`, `GATE_DAYS` | 40 resolved trades and 180 days (the house money gate) | the forward record |
| `POSTHOC_GATE_DATE` | 2027-02-04 (the holdout's last session plus six months) | section 9 |

Everything below refers to these names. No number in this table changes under this document; a change is a new prereg under a new file name, registered after this one is closed.

### 4.2 The session grid

The session's five-minute bars are folded from the minute rows by `mjonir.localstores.fold_minutes_to_5m` after an ET conversion of `window_start`: a bucket starts on the five-minute grid; its open is the open of the earliest minute present, its close the close of the latest minute present, its high and low the extremes, its volume the sum. Only buckets with a start from 09:30:00 ET up to and including the bucket that ends at `FLAT_BY` are kept, in time order; bar index 0 is the 09:30 bucket. On a full session the `FLAT_BY` bucket is index 76; on an early close it is index 40 (`timemachine.early_last` arithmetic). Early closes are the calendar's rule dates (`mjonir.calendar.rule_early_closes`), confirmed per session from the bar count of SPY in that day's file (an early close is verified when SPY's RTH bucket count is at most `EARLY_BARS`, hazard 3); a contradicted label is a refusal for that session, counted.

A missing bucket (no print in five minutes, a halt) is never padded. The walk uses the buckets present; `last` is the index of the last bucket present whose start is at or before the `FLAT_BY` bucket's start. A fire whose last present bucket ends before `FLAT_BY` exits at that bucket's close and is counted `exit_before_flat_by`; a fire with any missing bucket between index 0 and `last` is counted `missing_buckets`. Both counts go in the report.

### 4.3 The first bar and RVOL

- The first bar is bucket index 0 (09:30:00 to 09:34:59 ET). It must be present with a positive volume and an open and a close, else the name-day is excluded and counted `no_first_bar`.
- RVOL(D) = the first bar's volume on D divided by the mean of the first bar's volume over the `RVOL_N` sessions strictly before D. All `RVOL_N` prior first bars must be present with a positive volume, else excluded and counted `rvol_history_short`. The prior first-bar volumes come from the first-bar store the runner builds as it passes each day file (section 12): every ticker's index-0 bucket, persisted per session.
- The first `RVOL_N` sessions of the development window cannot have a full history (the minute files begin on the window's first session); they are warm-up, counted `warmup`, and no fire is possible on them. The holdout's history comes from the last sessions of the development window: inputs, never outcomes.
- "Up" means the first bar's close strictly above its open on unrounded values. A doji is not up.

### 4.4 Ranking: the paper's construction

Among the eligible names of D (sections 3.2 to 3.4 and 4.3), rank by RVOL descending, ties by ticker ascending, and take the first `TOP_K`: the day's "stocks in play" list L(D), direction-agnostic. The day's fires F(D) are the names in L(D) whose first bar is up. The paper ranks first and reads the direction from the bar second; a long-only arm of that strategy is the up subset of the same list, so the list here is the paper's. The alternative (the top `TOP_K` among up bars only) is a different and longer long list; it is not tested here. F(D) holds between zero and `TOP_K` fires; its distribution by session goes in the report.

One trade per name per day, long only, equal risk per trade: every result is in R (the entry minus the stop is 1 R), never in dollars.

### 4.5 Entry, stop, exit, costs

- Entry: the close of the first bar (index 0), unrounded: in `score_trade` terms, `k = 0`. The fill basis is the close of the latest minute inside the 09:30 bucket; its bias is stated in section 11.
- Stop: entry minus risk, where risk = max(`STOP_ATR_FRAC` times ATR, `RISK_FLOOR_PCT` of the entry), unrounded (chunk 1 amendment e: arithmetic on unrounded values, rounding for display only; the desk's `exit.py` floors its stop to the cent and REFUSES a risk under the floor rather than widening it; the study widens and counts `risk_floor_bound` so that no name is dropped for a quiet ATR).
- ATR: the simple mean of `ATR_N` daily true ranges, TR = max(high minus low, |high minus the prior close|, |low minus the prior close|), over the sessions strictly before D, exactly `exit.py daily_atr`'s arithmetic (the mean of n true ranges from n + 1 rows). Rows come from the daily cache (unadjusted, the same vendor as the minute bars; the split guard protects the lookback), not from the adjusted API. Why simple and not Wilder: it is what the desk's `datr:0.10` stop computes, so the study and the live desk agree, and it is reproducible from exactly `ATR_N` + 1 rows with no warm-up or seed.
- Target: none (`target=None`).
- Exit: `score_trade(bars, 0, entry, stop, None, last, cost_r, fill="close", gap_fill="open", long=True)`. The stop is checked first in every bar; a bar touching both counts as the stop; a bar that opens below the stop fills at its open; otherwise out at the close of bar `last`. `mfe_r`, `mae_r`, the touch margins and `fragile` are kept per fire.
- Costs, charged once per trade: `cost_r = mjonir.costs.trade_cost_r(entry, risk, model)` with `model = {"per_side_bps": tier + HALF_SPREAD, "commission_usd": COMMISSION, "shares": None, "max_loss_usd": the SHARES_BASIS max loss}`, where `tier = mjonir.costs.tier_bps(ADV_USD, COST_TIERS)` on the name's own ADV window mean. The round trip is two sides priced at the entry plus two commissions spread over `SHARES_BASIS`; the notional cap on the live share count is not applied here (it only lowers the share count and raises the commission a share by under 0.01 R at these prices; stated, not modelled). A worked line of the model, not a result: for a name whose ATR is 3 percent of its price, the risk is 0.3 percent of the price, and a round trip of 14 bp (the best tier plus the default spread, twice) is about 0.47 R. Costs are a large fraction of R under a tenth-of-ATR stop; that is the point of a net test.

## 5. Exploratory arms (reported, never promoted)

Each arm runs on the same sessions, the same list L(D) or its up subset as stated, the same cost model, the same control machinery with its own entry window, the same intervals and verdict states. An arm's state is printed; no arm's state can promote it or any parameter of the primary. Promotion of an arm needs a new prereg.

- Arm A, ORB-15 on the paper's list: the opening range is the first `OR15_MIN` of the session (buckets 0 to 2); the entry is the close of the first later bucket that closes above the range's highest high (upstream's ORB rule as `timemachine.rule_trade` applies it), no later than `NO_ENTRIES_AFTER`; the stop is the range midpoint (upstream's `or-mid`); two sub-arms, one per `ARM_TARGETS` multiple, exit at the target, the stop or the `FLAT_BY` close. Run on every name of L(D) regardless of its first bar's direction (the ORB rule supplies its own direction: long only, above the range).
- Arm B, ORB-5 with a target: the primary's fires, entry and stop, with a target of the larger `ARM_TARGETS` multiple above the entry.
- Arm C, the slippage sensitivity on the primary: the primary re-scored with `SLIP_X2`; printed beside the primary, never the headline, never a state.
- Arm D, the by-year table of the primary (and of each arm): for each calendar year, `n`, the net mean, `lo`, `hi`, the stop share, the close share, the fragile count; the sign-flip note `timemachine._history_summary` prints.

Also reported for the primary, per chunk 1 amendments a to e: every average with its interval and `n`; the fragile count (decisions under `FRAGILE_R`); the one-tick sensitivity (the entry shifted `TICK` up and down, the flip count); the data stamp `source: flatfile, adjusted: false`.

## 6. Controls

### 6.1 The matched random-entry control (sets a verdict state)

For every fire: `CONTROL_K` draws from `mjonir.control.draw_controls(bars, symbol, date, seed=SEED, draws=CONTROL_K, n_or=1, last=last, rule_entry=entry, rule_stop=stop, target_r=None, cost_fn=cost_fn, gap_fill="open", long=True, entry_until=None)`. So: eligible bars are index 1 through `last` minus 1 (the 09:35 bucket through the bucket before the `FLAT_BY` bucket: the whole post-range session, because the rule's claim is that this name's 09:35 entry is special, and a control confined to the morning would share part of that claim); the generator is `control.session_rng(SEED, symbol, date)`, seeded by identifiers only; each draw enters at its bar's close with the rule's own risk as a percent of the entry (stop = the rule's stop times the draw's close over the rule's entry), no target, the same `last`, and `cost_fn` is the same cost model evaluated at the draw's entry and risk with the name's own tier. Skips are counted (`risk_floor`, `no_eligible_bar`).

The delta: `paired_delta_ci({date: [net R of the day's fires]}, {date: [net R of the day's draws]}, SEED, DRAWS)`: per session, the mean rule net R minus the mean control net R; SESSIONS resampled, so a day's fires and draws stay paired and the twenty-way correlation of one open is inside the unit. The state: `verdict_control(delta)`, floored on the paired sessions at `N_FLOOR`.

### 6.2 The baselines (diagnostic only, never a state)

Two "buy anything at 09:35" lines, each scored by `score_trade` with the primary's stop rule, no target, the `FLAT_BY` exit and the cost model, reported with `expectancy_ci` and `n`, by year:

- B1: every eligible name of D (section 3), entered at the close of bar 0 (`control.baseline_entry_bar(1)`), whatever its first bar did;
- B2: every eligible name of D whose first bar is up.

B2 differs from the primary only by the `TOP_K` RVOL selection, so it isolates the ranking, the hypothesis's own ingredient; B1 is the base rate of the tape. Neither has a control and neither sets a state.

## 7. Windows

- Development: 2021-01-04 to 2023-12-29 inclusive, every flat-file session; the first `RVOL_N` sessions are warm-up (section 4.3).
- Holdout: 2024-01-02 to 2026-08-04 inclusive, every flat-file session.
- The pre-window lookback (the ADV window before the development window's first session) comes from the daily cache only.

The holdout is read ONCE, after the development verdict is written to its review file, only with the owner's word recorded in the holdout review's header by the lead, and only through `tools/rvol_study.py --window holdout --i-have-read-the-prereg`, which additionally refuses unless a development review file exists whose JSON sidecar carries `pass` on every criterion of section 8.1. A second holdout run under this document is a refusal.

## 8. Success criteria

### 8.1 Development (all four must hold)

1. `verdict_history.state == "pass"` where the history is `expectancy_ci` over the net R of ALL primary fires with `SEED` and `DRAWS`: `n` at or above `N_FLOOR` and `lo` above zero.
2. `verdict_control.state == "pass"`: paired sessions at or above `N_FLOOR` and the delta's `lo` above zero.
3. In every development calendar year with at least `N_FLOOR` fires, the year's net mean is above zero (the same sign as the pooled mean that criterion 1 requires).
4. The session-level interval: `expectancy_ci` over the per-session mean net R (one value per session with at least one fire), `SEED`, `DRAWS`: sessions at or above `N_FLOOR` and `lo` above zero. This re-uses the one estimator on a coarser unit; it is here because up to `TOP_K` longs taken at the same minute of the same open share one market, and a fire-level bootstrap treats them as independent. (The lead may strike this criterion before the freeze; after the freeze it stands.)

### 8.2 Holdout (the same four, read once)

Criteria 1 to 4 on the holdout window, with "calendar year" in criterion 3 counting the holdout's partial last year only if it has at least `N_FLOOR` fires.

### 8.3 Anything else

Any state other than `pass` on any criterion on either window closes the hypothesis by a dated postscript in section 13. No parameter is retuned; no second development run under this document. Arm results, whatever their states, are reported and never promoted.

## 9. Stopping rule and what each outcome triggers

- Development pass on all four: the lead asks the owner; with the owner's word the holdout runs once.
- Development anything else: closed by postscript. An `unverified` by floor (too few fires) is closed as "cannot judge" and may be reopened only by a new prereg with a wider window or universe, never by widening this one.
- Holdout pass on all four after a development pass: the rule enters the FORWARD RECORD as setup `rvol_orb5` through `scan.py rvol` and `trader-record` (plan 3.1, 3.4), paper only, under the house money gate: at least `GATE_N` resolved trades AND at least `GATE_DAYS` days, the record's net expectancy interval above zero and its delta against the record's own matched control above zero. Never to money directly; the gate is not a forecast.
- Holdout anything else after a development pass: a fail; closed by postscript; the development pass is recorded as in-sample and nothing more.
- A strong result on the WRONG side on either window (the rule below zero with the whole interval under zero, or behind its control with the whole interval under zero) is recorded as a kill with structure. Its mirror (fading the list) is post-hoc and is never registered: it gets a dated gate on unseen sessions after the holdout's last session, read no earlier than `POSTHOC_GATE_DATE`, and only under a new prereg.
- Nothing in this document moves money. The forward record is the paper account.

## 10. Availability counts, read before the freeze

Allowed before the freeze: counts only, never a price, a volume or an outcome. Filled here from file listings and the ticker column alone (2026-11-03):

| count | development | holdout | how |
| --- | --- | --- | --- |
| flat-file sessions | 753 | 649 | directory listing of `minute_flatfiles/` |
| sessions by year | 2021: 252, 2022: 251, 2023: 250 | 2024: 252, 2025: 250, 2026 to 08-04: 147 | the same listing |
| weekdays without a file | 27 (2021-01-04 to 2023-12-29) | 28 (2023-12-30 to 2026-08-04) | all 55 are NYSE holidays by `mjonir.calendar.rule_holidays`, checked programmatically (2025-01-09, the Carter day of mourning, included); no session is missing |
| early closes by rule | 4 (2021-11-26, 2022-11-25, 2023-07-03, 2023-11-24) | 6 (2024-07-03, 2024-11-29, 2024-12-24, 2025-07-03, 2025-11-28, 2025-12-24) | `rule_early_closes`; each is confirmed from SPY's bucket count at run time |
| daily-cache files | 753 | 649 | listing of `flatfiles_cache/`; every minute-file date has one; 64 files cover 2020-10-01 to 2020-12-31 for the pre-window lookback |
| tickers in one minute file | 9,251 (1,668,241 rows, 2021-01-04) | 10,181 (1,575,694 rows, 2024-01-02) | the `ticker` column only |
| tickers in one daily file | 9,374 (2021-01-04) | 10,469 (2024-01-02) | the `ticker` column only |
| as-of reference answer | shape confirmed, two rows | the same endpoint | the connector, `date=2021-06-01`, `type=CS`, `limit=2` |
| splits answer | shape confirmed, two rows | the same endpoint | the connector, `execution_date` 2021-01-04 to 2021-01-31, `limit=2` |

To be filled by `tools/rvol_study.py --counts-only` (which scores nothing and prints no price) before the freeze, each for both windows, and pasted here by the lead as the last pre-freeze edit:

- `reference_rows_by_month`: CS and ADRC row counts per monthly walk, and the request count.
- `splits_rows`: the number of split rows in the splits walk.
- `eligible_per_session`: the median and the interquartile range of eligible names per session after sections 3.2 to 3.4 and 4.3.
- `exclusions_by_cause`: name-days removed by `insufficient_history`, `split_guard`, `gap_guard`, `no_first_bar`, `rvol_history_short`, and the `warmup` sessions.
- `first_bar_coverage`: the share of eligible name-days whose full `RVOL_N` first-bar history is present.
- `early_close_basis`: verified or contradicted, per rule date.

Not read before the freeze: fires per session (it depends on the first bar's direction), any outcome, any mean.

## 11. What is NOT claimed

- No profit is claimed or promised, by this document, by the runner's output or by any review that cites it. A pass is a past sample under a stated model; the forward record and its gate are the only path onward, and the gate is not a forecast.
- Shorts are not tested. The paper trades both sides; this pack is long only; the down half of every list is dropped, not scored.
- Results are in R net of the stated cost model (`COST_TIERS`, `HALF_SPREAD`, `COMMISSION`, `SHARES_BASIS`), never in dollars; the spread is a default, not a measured NBBO, and may be low for the thinnest tier; halts, borrow, locates and partial fills are not modelled.
- The fill at the first bar's close is an idealisation with a known direction of bias: a market order sent at 09:35:00 fills at or after the next print, through the spread, in a fast tape; on an up first bar the next print is more often above the close than below it, so the idealised entry flatters a long. The control shares the same fill convention, so the delta is less exposed than the expectancy; the live record (hand-entered fills, `fill_basis = broker`) is the measurement of this bias.
- The `FLAT_BY` exit is five minutes before the official close and uses the last bucket's close, not the closing auction; the paper holds to the close. A difference by design (the desk's own flat-by rule), stated.
- The live list from `scan.py rvol` ranks a snapshot first and exact first bars second; it may differ from the study's list on a few names a day. The forward record tests the live list, not this study.
- The paper's sample, universe, floors, costs and leverage are its own; only the construction of the list and the trade is taken from it. Agreement or disagreement with the paper's numbers is not a claim of replication.
- Twenty simultaneous longs at one open share one market; criterion 4 and the session-paired control address this, the fire-level interval does not.

## 12. Implementation notes for the builder

- Path: `tools/rvol_study.py`, pandas allowed (plan 3.5), Python 3.12 allowed, run from the repo root. Subcommands or flags: `--window dev|holdout`, `--counts-only`, `--i-have-read-the-prereg` (holdout only), `--out docs/reviews/rvol_<window>_<date>.md`. It imports `mjonir.outcomes`, `mjonir.stats`, `mjonir.costs`, `mjonir.control`, `mjonir.localstores`, `mjonir.calendar`, `mjonir.massive`, `mjonir.universe.TICKER`; it defines no estimator, no stop arithmetic beyond section 4.5 and no outcome comparison (the chunk 2 grep for `>= target` / `<= stop` outside `outcomes.py` must still find nothing).
- Refusal first: section 1's checks run before any import of pandas and before any file under `~/Infinit` is opened. `--counts-only` is the one mode allowed on a DRAFT, and it refuses to write anything but counts.
- One pass per day file: read `minute_flatfiles/<D>.csv.gz` once with `pandas.read_csv` (explicit dtypes, `window_start` as int64), convert to ET, keep RTH minutes, fold every ticker's 09:30 bucket into the first-bar store (`trader/data/rvol/firstbars/<D>.csv`: ticker, open, close, volume; about ten thousand rows a session), compute eligibility from a rolling in-memory deque of the last `ADV_N` + 1 daily-cache frames, rank, select, fold the five-minute buckets for L(D) and for the baselines' names, score, draw the controls, append one JSON line per fire, per draw, per arm trade and per baseline trade to `trader/data/rvol/<window>/<D>.jsonl`, then drop the frame. Re-running a session replaces its file, so a crash resumes at the next session and the run is idempotent.
- Bounds: one day frame is about 1.7 million rows by 8 columns; peak memory under about 1 GB; the day pass is dominated by gunzip and parse, so a window takes on the order of hours; run it under `nohup`.
- Determinism: `SEED` everywhere; tickers and dates always iterated sorted; ties by ticker; no wall clock in any computation (the runner never calls `today_et()` except to stamp the report's date); the same inputs give byte-identical sidecars.
- Early closes: the session's bucket count from SPY decides, per section 4.2; the calendar overlay is loaded before the pass.
- Output: `docs/reviews/rvol_<window>_<date>.md`, tracked, plus a JSON sidecar beside it with every number the document prints (P12: Python computes, the document narrates). Sections in order: the freeze hash and the runner's own commit; the command line; the availability funnel of section 10 as measured in the run; fires (`n`, per-session distribution, `fragile`, `missing_buckets`, `exit_before_flat_by`, `risk_floor_bound`); the primary's history verdict text and numbers; the control's verdict text and numbers; the session-level interval; the by-year table; the slippage sensitivity line; the one-tick line; the arms table (A at each target, B) with their verdict texts and controls; the baselines B1 and B2 by year; the data stamp; the four criteria of section 8 each with `pass` or its state, and the one-word result. Every verdict string is the fixed template from `mjonir.stats`; the banned-words test applies to the document.
- Tests (offline, in `tests/test_rvol_study.py`): the DRAFT refusal exits 1 without opening a file (a planted unreadable flat-file dir proves it); the FROZEN check against a planted hash and an altered body; the first-bar fold from three minute rows; the ranking tie rule; the up test on a doji; the split and gap guards; the warm-up count; the ATR arithmetic against `exit.py daily_atr` on the same rows; the risk floor widening and its count; a synthetic window through `tests/synth.make_session` producing the sidecar keys; the control pinned to bar 0 giving a delta of zero; the holdout refusal without the development sidecar.
- Reviewer's checks for chunk 3 (from the plan): the freeze commits predate every `rvol` code commit; `score_trade` is the only outcome computation; `cost_r` once per trade; control seeds use identifiers only; no verdict reads anything but the templates; no sentence promises profit.

## 13. Postscripts

(None. Entries here are dated and signed; this is the only section that may change after the freeze.)

## 14. References

- Zarattini, C., Barbon, A., Aziz, A. (2024). A Profitable Day Trading Strategy For The U.S. Equity Market. SSRN 4729284.
- Zarattini, C., Aziz, A. (2023). Can Day Trading Really Be Profitable? SSRN 4416622.
- /home/axis/Odyssey/NewResearch.md lines 334 and 897 to 899 (the house's only written notes on the paper).
- /home/axis/.claude/projects/-home-axis-Odyssey/memory/day-trader-skill-review-2026-11-02.md line 30 (the "index replication read net zero" recollection; no record on disk).
- /home/axis/.claude/plans/build-off-of-the-quirky-piglet.md (the plan; steps 2.1 to 2.6, the chunk 1 and chunk 2 amendments, step 3.3 and 3.5).
- /home/axis/Mjonir-DayTrader: mjonir/outcomes.py, mjonir/stats.py, mjonir/costs.py, mjonir/control.py, mjonir/localstores.py, mjonir/calendar.py, mjonir/universe.py, trader-exit/exit.py (`daily_atr`), trader-timemachine/timemachine.py (`history_replay`, `early_last`), docs/reviews/chunk2.md.
