# Chunk 3b review: the RVOL hypothesis (prereg DRAFT, live scanner, study runner in counts-only mode)

Builder: Opus (claude-opus-5-5). Written Tue 2026-11-03, about 00:45 to 04:00 EST. Branch `feat/c3b-rvol`,
worktree `.claude/worktrees/c3b-rvol`, off `feat/c3-record` = `1475ce3` (589 OK). Market closed throughout. Plan
steps 3.3 to 3.5 only. The preregistration is a DRAFT: nothing was scored on real data, and no fire, first-bar
direction, price, volume or outcome of the flat files was printed or written to any output (the gitignored
first-bar store caches the vendor's own 9:30 bars, as section 12 asks: section 6). Every number below was printed
by Python.

## 0. Read first: the paper check found a different entry (the owner's call before the freeze)

D1 reached the paper's text (section 2 below). Most of section 2.1's recollection holds, but two points the
PRIMARY rule rests on do not, and changing either would change section 4 (the entry rule, and parameters of the
4.1 table), so per the brief I did not edit them; D1 corrected section 2.1's description only and lists the
departures there:

1. **The entry.** The paper buys with a STOP order at the first five-minute candle's HIGH (sells at its low),
   so a trade starts only when the range breaks, at any time of the session (its own example triggers half an
   hour after the open). The draft's PRIMARY buys at the close of the 9:30 bar, at 9:35, on every up first bar
   of the list, whether or not the high is ever broken. These are different trades: the paper's is a breakout of
   the five-minute range, the draft's a continuation entry at 9:35. Arm B and the live record's 9:35 trigger
   follow the draft.
2. **The filters.** The paper's universe is: the day's OPENING price above $5, the average share volume over the
   previous 14 days at least 1,000,000, the 14-day ATR above $0.50, and a relative volume of at least 100 percent
   (then the top 20). The draft reads the price on the prior close, both liquidity floors over 20 sessions, adds
   the $20M dollar floor, and has no ATR or relative-volume floor.

Also from the paper, not in the draft's rule: a 4x leverage cap, 1 percent of capital at risk, exit at 16:00,
$0.0035 a share commission only. The code follows the draft as written; if the owner adopts the paper's entry
or floors, the change lands in `mjonir/rvol.py` (floors), `tools/rvol_study.py` (PARAMS, the entry) and
`trader-scanner/scan.py` (the record's trigger), and the counts below need a re-run (minutes: the first-bar
store and the caches stay valid).

## 1. Commits

| step | commit | on origin |
| --- | --- | --- |
| D0, the prereg as a DRAFT, alone, byte for byte (sha256 `74b1ffb2...`) | `9fba2be` | yes |
| D1, the paper details (section 2.1 only) | `2c4e422` | yes |
| 3.4, `scan.py rvol`, `mjonir/rvol.py`, record's `SETUP_PLANS`, `floors.min_avg_volume` | `e3bc4ac` | yes |
| 3.5, `tools/rvol_study.py` and its tests | `90178bc` | yes |
| D2, the availability counts pasted into section 10 | `66babe0` | yes |
| docs: README roadmap, RUNBOOK 09:35, scanner SKILL.md, CLAUDE.md, this review | the commit that adds this file | pushed with it |

D0 predates every commit that adds or changes `tools/rvol_study.py` or the `rvol` subcommand (`git log --reverse`
from `1475ce3`: D0, D1, scanner, runner, D2, docs). Explicit `git add` paths; no force-push, no amend; every
message ends with the Co-Authored-By line. The status line still reads `Status: DRAFT (awaiting the owner's
freeze)`.

## 2. Tests

Each commit re-run in a throwaway detached worktree (`python3 -m unittest discover -s tests`):

| tree | result | runtime |
| --- | --- | --- |
| `1475ce3` (base) | 589 OK (the brief's count) | |
| `9fba2be` (D0) | 589 OK | 13.3 s |
| `2c4e422` (D1) | 589 OK | 13.7 s |
| `e3bc4ac` (scanner) | 603 OK (+14) | 13.5 s |
| `90178bc` (runner) | 618 OK (+15) | 16.8 s |
| `66babe0` (D2) | 618 OK | 17.9 s |
| docs (this commit, run in the tree before committing) | 618 OK | 17.6 s |

New: `tests/test_scanner_rvol.py` (14: the RVOL arithmetic on a synthetic store; a name with 13 prior 9:30 bars
excluded and counted, and a zero volume the same; the floors never read the day itself (a huge planted D volume
leaves the funnel unchanged and the day is never asked); ties by ticker and the doji; every guard and floor
counted once; the 9:30 bucket from 5-minute rows; refused before 9:35, under Yahoo, on a weekend, for a future
date; the JSON, rvol.json and the watchlist; the watchlist keeps the daily hits and drops stale rvol tags; a
replay has no stage 1 and records nothing; a scan after 9:45 records nothing; the record rows' shape (trigger
9:35, bar 0, the 9:30 close, the 9:30 high and low as a 5-minute range, rvol and volume_x, stop_rule datr,
stop_param 0.1, no target, exit close, flat-by 15:55, the datr stop equal to a tenth of exit.py's mean of 14
true ranges floored to the cent), scored after the close from bar 0 to bar 76 with a control whose n_or is 1; a
plan trader-exit refuses recorded with no plan and the reason; the floors from the config) and
`tests/test_rvol_study.py` (15: the DRAFT refusal in a fresh interpreter: exit 1, the check named, pandas never
imported, the planted unreadable flat-file folder never touched, the data folder still empty; the FROZEN check
against a throwaway repo with D0, F1 and F2: passes and names F1; an altered body (uncommitted, then committed),
a planted hash, a commit that never touched the document, a dirty file each refused by name, a section 13
postscript accepted; the holdout refusals (no flag, no development sidecar, a sidecar with one criterion short of
pass, a second holdout); the first-bar fold from three minute rows equal to `fold_minutes_to_5m`; the store
round-trips unrounded values; SPY's 42 buckets on an early close with its 13:00:00 print and 78 on a full day;
ties and the doji through `mjonir.rvol`; the ATR equal to `exit.py daily_atr` on the same rows; the risk floor
widening (bound, 0.05 percent, its controls drawn where the plain arithmetic loses them, in about half of 600
entries); the control pinned to bar 0 gives a delta of 0; the PARAMS table against the document's section 4.1
and against mjonir's constants; counts-only on a synthetic window writes only the allowed keys and no direction,
outcome or bar value, counts the split, gap, missing-bar, cheap and late-listed names, the warm-up and the early
close, makes 7 requests once and none on a re-run, and gives the holdout no warm-up; a short reference page is a
refusal, not a count; a synthetic window scored end to end writes the sidecar keys, a document free of banned
words, three draws or a counted skip per fire, and the same sidecar byte for byte from a fresh data folder).

**Assertions edited** (this fork's own pins, none upstream's):

| test | old | new | reason |
| --- | --- | --- | --- |
| test_budget `CONTRACT_CFG` | floors without `min_avg_volume` | with `min_avg_volume: 1000000` | the share floor is read from the config (the brief), and the example config ships it |
| test_limits `test_the_example` | `floors` without the key | with `min_avg_volume: 1e6` | the same key, registered in `mjonir.limits.FLOOR_KEYS` so it is not warned as unknown |
| test_repo `FORK_ROOT` | no `tools` | `tools` | the runner's folder at the root |
| test_mjonir_outcomes `OnePlace` | grep over `trader-*` and `mjonir` | also `tools` | the prereg says the grep must still find nothing, the runner included |

`tests/_mj.py` also hides the daily flat-file cache (`MJONIR_DAILY_DIR`) the way it hides the minute files.

## 3. D1: the paper check

SSRN's page answered 403 to WebFetch. One web search found an open copy: the Swiss Finance Institute working
paper in the University of St. Gallen repository (the version dated February 16, 2024; the PDF's footer says
"Electronic copy available at: https://ssrn.com/abstract=4729284"). Its text was extracted with a throwaway stdlib
script (no PDF library on the box) and read in full. A later SSRN revision, if one exists, was not read.

| point (section 2.1 as drafted) | the paper | |
| --- | --- | --- |
| rank by the first five minutes' volume against the same five minutes' mean over the prior 14 days | yes (its section 3 formula) | verified |
| the top 20 | yes, plus a floor: relative volume at least 100 percent | verified; floor missing from the draft |
| direction from the first bar; a doji no trade | yes | verified |
| entered at the start of the second bar | NO: a stop order at the first candle's high (low for a short) | corrected in 2.1 |
| stop at 10 percent of the 14-day ATR | yes, from the executed entry price (ATR attributed to Wilder; averaging not stated) | verified |
| out at the close | yes, 16:00 ET | verified |
| equal risk | 1 percent of capital at the stop, under a 4x leverage cap that can lower it | verified, cap added |
| sample 2016 to 2023 | yes, January 1, 2016 to December 31, 2023; CRSP universe, IQFeed bars unadjusted | verified |
| filters: a price floor, a share-volume floor, an ATR floor | opening price above $5; 14-day average volume at least 1,000,000; 14-day ATR above $0.50 | verified, specifics added |
| costs: a per-share commission, no slippage or spread | $0.0035 a share, nothing else | verified |
| positive net returns, high Sharpe | yes | verified |
| predecessor on an index ETF, SSRN 4416622 | yes (QQQ/TQQQ) | verified |

D1 (`2c4e422`) rewrote section 2.1's paragraph and added a list of the PRIMARY rule's departures; no other
section and no parameter changed. Section 0 above is the decision this leaves to the owner.

## 4. The counts-only run (D2)

Run at `90178bc` (the runner as committed), from the worktree root, in the background:

```text
nice -n 19 python3 tools/rvol_study.py --window dev --counts-only
nice -n 19 python3 tools/rvol_study.py --window holdout --counts-only
```

| window | start (EST) | end | wall | requests | sessions |
| --- | --- | --- | --- | --- | --- |
| dev | 03:22:47 | 03:35:42 | 12 min 55 s | 257: 249 reference pages, 8 splits pages | 753 (739 after the 14 warm-up) |
| holdout | 03:35:42 | 03:47:31 | 11 min 49 s | 224 reference pages (the splits walk cached) | 649 |

Both exit 0: no refusal, no traceback. Every reference walk passed `check_reference` (5 or 6 pages a CS walk, one
an ADRC walk); the splits walk, 2020-12-03 to 2026-08-04, gave 7,359 rows in 8 pages, every page checked. Each of
the 1,402 minute files was read once, about 0.85 s a session; the holdout took the development window's last 14
first bars from the store. The printed and written output (both windows' stdout, stderr and counts files) was
scanned afterwards: the only matches for fire, direction, outcome, price or volume are the cause name
`below_price`. Outputs, gitignored, in this worktree: `trader/data/rvol/counts-dev.json`, `counts-holdout.json`,
the first-bar store (1,402 sessions, `firstbars/<D>.csv` and its meta), `reference/` (136 walk files),
`splits.json`: 277 MB in all.

Section 10 as pasted (D2, `66babe0`; the monthly table of 68 walks follows the list in the document):

- `reference_rows_by_month`: CS and ADRC row counts per monthly walk, and the request count. Filled from the run of 2026-11-03 (the table below): development 36 monthly walks of each type, 2021-01 to 2023-12 (CS 4,778 to 5,844 rows, ADRC 419 to 454), 249 requests; holdout 32 monthly walks of each type, 2024-01 to 2026-08 (CS 5,119 to 5,342 rows, ADRC 376 to 422), 224 requests.
- `splits_rows`: the number of split rows in the splits walk. Filled: 7,359 rows (one walk for both windows, 8 pages).
- `eligible_per_session`: the median and the interquartile range of eligible names per session after sections 3.2 to 3.4 and 4.3. Filled: development median 1,003, interquartile range 959.5 to 1,076 (min 852, max 1,334), over 739 sessions; holdout median 1,223, interquartile range 1,056 to 1,371 (min 919, max 1,600), over 649 sessions.
- `exclusions_by_cause`: name-days removed by `insufficient_history`, `split_guard`, `gap_guard`, `no_first_bar`, `rvol_history_short`, and the `warmup` sessions. Filled (each name-day under the first cause it fails, in the order shown; the three floors of section 3.3 counted beside them; out of 4,417,487 development and 3,647,768 holdout name-days in the type lists): development `insufficient_history` 426,883, `split_guard` 16,958, `below_price` 1,043,541, `below_adv_usd` 1,706,380, `below_adv_shares` 464,791, `no_first_bar` 420, `gap_guard` 19, `rvol_history_short` 2,990; `warmup` 14 sessions; holdout `insufficient_history` 219,143, `split_guard` 29,721, `below_price` 1,041,908, `below_adv_usd` 1,168,156, `below_adv_shares` 391,884, `no_first_bar` 397, `gap_guard` 28, `rvol_history_short` 2,984; `warmup` 0 sessions.
- `first_bar_coverage`: the share of eligible name-days whose full `RVOL_N` first-bar history is present. Filled: development 0.9961; holdout 0.9963.
- `early_close_basis`: verified or contradicted, per rule date. Filled: development 2021-11-26 verified, 2022-11-25 verified, 2023-07-03 verified, 2023-11-24 verified; holdout 2024-07-03 verified, 2024-11-29 verified, 2024-12-24 verified, 2025-07-03 verified, 2025-11-28 verified, 2025-12-24 verified (SPY's buckets from 09:30 to 16:00, the 13:00:00 closing print left out); short sessions that are not a rule date: 0 and 0; refused sessions: none.

## 5. How the brief is met

- **One construction, two users.** `mjonir/rvol.py` (stdlib, Python 3.8 syntax) holds sections 3.3, 3.4, 4.3 and
  4.4 once: `floors_stage` (the 20 sessions strictly before D: prior close, mean of close x volume, mean volume;
  a missing session or a zero volume is `insufficient_history`; a split inside [the window's first session, D]
  is `split_guard`), `bar_stage` (`no_first_bar`, `gap_guard` at 0.4x / 2.5x the prior close,
  `rvol_history_short`), `rank` (top K by RVOL descending, ties by ticker, direction-agnostic, then fire = close
  strictly above open on unrounded values). The scanner and the runner both call it; every exclusion is counted
  under its first failed cause.
- **`scan.py rvol`** (3.8 syntax, through `_mjonir()`): Massive only (refused under Yahoo); refused before 9:35 ET
  (one plain line, like `orb_window()`), on a weekend or holiday, and for a future `--date`. Stage 1, live: one
  full-market snapshot (`snapshot_all`), rows of another day counted and dropped, day volume over the 20-session
  mean volume, the 200 highest past the floors (counted). Stage 2: the 9:30 buckets of D and the 14 sessions
  before from `mjonir.bars.bars_5m` (source api, 8 threads, paced by the client), then `bar_stage` and `rank`.
  The type list is `trader/universe.txt` (`scan.py universe --source massive`: CS and ADRC, the ticker rule) or
  `--symbols`. Floors from `floors.min_price`, `floors.min_adv_usd`, `floors.min_avg_volume` (the universe block
  as a fallback for the first two, then mjonir's defaults, each source printed). Rows are `{symbol, rvol, rank,
  first_bar {o,h,l,c,v}, direction, adv_usd, price, fire, volume_x}`; `trader/rvol.json` holds them with the
  counts; the fires join `trader/watchlist.json` as setup `rvol_orb5` beside the other hits (an earlier rvol tag
  is dropped first). The output says the live list may differ from the study's (section 11) and that the list is
  a hypothesis under test, not a signal.
- **The record.** `--record` (default) calls `record_trigger` once per fire with an entry-shaped doc (status
  triggered, setup `rvol_orb5`, time 09:35, bar_index 0, price the 9:30 close, interval 5m, opening_range
  {high, low, minutes 5}, source, checked_at) and `extra={"rvol", "volume_x"}`. The plan comes from
  `trader-record`'s new `SETUP_PLANS` table: `rule_plan` builds trader-exit's plan with `--stop datr:0.10
  --target none --exit close` and the config's flat-by. exit.py's datr label begins "0.1 x the 14-day daily
  ATR" (its `num()` drops the trailing zero), so `rule_of` reads `stop_param` 0.1, which is 0.10; `or_minutes` 5
  gives `n_or` 1 at scoring. Tested end to end (record, then `score_day` from bar 0 to bar 76, the control's
  n_or 1).
- **The runner.** The five freeze checks of section 1 run first, stdlib and git only, before pandas or any data
  file; `--counts-only` is the one mode exempt. The holdout adds the flag, the development sidecar and the
  second-run refusal. The scoring path exists and is tested only on synthetic folders: `score_trade` for every
  outcome (primary, arm B, the slippage and one-tick re-scores, the baselines, arm A after
  `timemachine.rule_trade`), `trade_cost_r` with the section 4.5 model (the name's own tier plus the 3 bp half
  spread, $1 a side over floor($1,000 / risk) shares), `draw_controls` with section 6.1's arguments (n_or 1, the
  whole post-range session, target none, seed 19, three draws), `expectancy_ci` and `paired_delta_ci` (sessions
  resampled), `verdict_history` and `verdict_control`. Criterion 4 is its own line; `criteria_counted` reads the
  frozen text, so a struck criterion 4 is not counted. One JSON line per fire, draw, arm trade and baseline trade
  per session, replaced on a re-run; the report and its sidecar in section 12's order; banned words checked before
  writing; no clock in the sidecar.
- **The grep.** `>= target` / `<= stop` still finds nothing outside `mjonir/outcomes.py`, now over `tools/` too.

## 6. Decisions, deviations, owed and uncertain

- **The reviewer's notes did not arrive.** The brief points to "What chunk 3b's builder must know" in reviewer's
  notes below it; none came with the brief. I worked from the prereg, the plan and docs/reviews/chunk3a.md as
  committed.
- **The paper's entry and filters** (section 0): the owner's call before the freeze. Built to the draft.
- **Criterion 3 with no year at the floor.** "In every development calendar year with at least N_FLOOR fires" is
  vacuous when no year has 40 fires; the runner reads that as unverified (`no_year_at_floor`), never as a pass.
  Worth one sentence in section 8.1 before the freeze.
- **Criterion 4's text.** It reuses `verdict_history` on the session means (the one estimator, the one state
  rule); the template says "fires" where it counts sessions, and the report says so on the line.
- **The result word** is `pass` when every counted criterion passes, else `closed` (section 8.3).
- **Two readings of the text,** in the runner's docstring: SPY's bucket count drops a 13:00:00 print that is
  its last before 16:00 (every rule date reads 42 buckets, that print, then nothing until 16:00; a literal
  [09:30, 16:00) count reads 43 and would contradict every early close); and a floor-bound stop moves down a few
  ulps so that `mjonir.control`'s own 0.05 percent check sees 0.05 (without it about half of the floor-bound
  fires lose their controls to float rounding: measured, and pinned by a test).
- **The funnel order** is insufficient_history, split_guard, the three floors, no_first_bar, gap_guard,
  rvol_history_short (the first cause wins; gap_guard needs the first bar, so it follows no_first_bar). The three
  floor causes are counted beside the six section 10 names. B1 and B2 use the same eligibility as the list
  (after section 4.3). Arm A needs buckets 0 to 2 present (else `or_incomplete`) and skips a range-midpoint stop
  under 0.05 percent (exit.py refuses one), both counted.
- **The fold** is `mjonir.localstores.fold_minutes_to_5m` itself, per ticker, as section 4.2 says; it is pure
  Python, so the scoring run (never run) will spend most of its time folding the eligible names for B1. Estimate:
  a few seconds a session, a few hours a window; not measured.
- **The first-bar store** holds the vendor's own 9:30 open, close and volume per ticker (section 12 asks for
  it); a direction is derivable from it, but nothing reads one before the freeze, and it stays gitignored under
  this worktree's `trader/data/rvol/` (about 277 MB for both windows). If the worktree is removed, the store
  goes with it; a later run rebuilds it from the day files (about 20 minutes).
- **Live scanner choices, not in the brief:** a live scan records only when made by 9:45 ET (a 9:35 entry
  recorded at noon would let hindsight into the paper record), and a `--date` replay never records; a replay has
  no snapshot, so every name past the floors goes to stage 2 (about 2,000 bar requests the first time, cached
  after); `volume_x` is the stage-1 ratio; the live split guard asks Massive's splits since the window's first
  session, mirroring the study's guard on adjusted data; the type list is the weekly universe file, not the
  monthly as-of walk (the live list can differ from the study's: section 11).
- **Live hazard:** Massive may publish the 9:30 bar a few seconds after 9:35; a scan at 9:35:00 can count names
  as `no_first_bar`. Run it at 9:36 (RUNBOOK says "after the 9:30 bar closes").
- **Not run:** `scan.py rvol` on live data (the market was closed throughout); its first live use is the next
  session's 9:35 step. No replay on real data either, to print no first-bar direction before the freeze. The
  scoring path was never run on the flat files.
- **Touched outside the two named files:** `trader-record/record.py` (`SETUP_PLANS`, 10 lines; other setups
  unchanged, their messages byte for byte), `mjonir/limits.py` and the example config (`floors.min_avg_volume`),
  `mjonir/yahoo_shape.py` (the adapter's `rvol_scan`), CLAUDE.md (one line: `tools/` and the DRAFT rule).
- **Holdout counts-only** runs without `--i-have-read-the-prereg` (it reads no outcome); it builds the
  development window's last 14 first bars when they are not in the store (inputs, never outcomes).
- **Not checked by the runner:** the owner's word in the holdout review's header (the lead writes it).

## 7. Review fixes (3b review: APPROVE WITH SHOULDs, no MUST)

Two commits on `feat/c3b-rvol`: `58bc153` (the code, 625 OK, 17.1 s) and `0b9adcb` (D3, every prereg text item, 625
OK, 17.3 s). The owner kept criterion 4; the entry rule was not decided at the time, so neither commit touched the
PRIMARY entry, the 4.1 table or the paper's ATR and RVOL floors. Status still DRAFT; counts-only not re-run.

| item | change | pinned by |
| --- | --- | --- |
| S1 freeze re-pointing | a sixth check, `freeze commit`: the named commit reads `Status: FROZEN (commit pending)`, its parent `Status: DRAFT (awaiting the owner's freeze)`, and no earlier version reads FROZEN (the last clause is mine: it also refuses a return to DRAFT followed by a second freeze); section 1 says so (D3) | test_rvol_study `Freeze.test_a_retune_repointed_at_a_later_pending_commit_is_refused` (C3 pending after F2 plus C4 pointing at it: refused, "parent"; a re-DRAFT then re-freeze: refused, "frozen before"; a status naming D0: refused; the honest D0, F1, F2 path passes) |
| S2 self-check | reads the document's own status line: DRAFT or pending, Refused "status"; FROZEN (commit h), returns h | `Freeze.test_this_documents_own_status_gives_the_matching_outcome` |
| S3 section 12 text | counts-only "writes only counts, the two reference caches and the first-bar store (ticker, open, close, volume per session: inputs the scoring run reuses; no direction, no outcome)" (D3) | the document |
| S4 holdout criteria | `holdout_check` reads `criteria_counted` from the frozen text and requires pass on those keys; the sidecar's own list is ignored | `Freeze.test_the_holdout_refusals` (a sidecar that counts 1 to 3 with 4 unverified is refused while the text counts 4; accepted once the text strikes 4) |
| S5 holdout --out | `holdout_out_check`: a holdout `--out` must be `docs/reviews/rvol_holdout_*.md`, refused otherwise before any data | `Freeze.test_the_holdout_refusals` (three bad paths, the good one, `main` refused with "check holdout out") |
| S6 resume | each session file's head and end rows carry `stamp` {runner_commit, code_sha256 over PARAMS, tools/rvol_study.py and mjonir/rvol.py}; `read_day` returns None (score again) on any mismatch | `Pieces.test_a_session_scored_with_other_code_is_scored_again` |
| N1 section 4.5 | the at-most-eight `nextafter` steps sentence (D3) | `Pieces.test_the_risk_floor_widens_and_keeps_its_controls` (the code it describes) |
| N2 counts-only computes nothing per name | `bar_stage(rows=False)` returns names only; the runner's `funnel(rows=False)` in counts-only | test_scanner_rvol `Rules.test_rows_false_counts_the_same_and_computes_nothing_per_name`; `Window.test_counts_only_writes_counts_and_nothing_else` (every `bar_stage` call in counts-only had rows=False) |
| N3 section 6.1 | eligible control bars, `last` and every index are positions in the present-bucket list (D3) | the document |
| N4 section 9 | the record takes a fire only from a live scan made by 09:45 ET; a `--date` replay never records (D3) | test_scanner_rvol `Cli.test_a_late_live_scan_records_nothing`, `Cli.test_a_replay_has_no_stage_one_and_records_nothing` |
| N5 templates | `mjonir.stats.verdict_years` and `sign_flip_note` with fixed templates `Y_NONE`, `Y_ABOVE`, `Y_BELOW`, `Y_FLIP` (in `all_templates`, so the banned-words test covers them); the runner uses both | test_mjonir_stats `Years` (three states, a year under the floor not read, the note's text) and `Verdicts.test_banned_words` |
| N6 replay cost | `scan.py rvol` prints the stage-2 request count before stage 2 (stderr, so `--json` stays clean; silenced by `--quiet` only); `--shortlist N` on a `--date` replay ranks stage 1 by the day's whole-session volume over the mean (labelled a replay-only proxy; the floors still read only the sessions before the day) | `Rules.test_a_replay_shortlist_reads_the_days_volume_for_stage_one_only`, `Cli.test_a_replay_has_no_stage_one_and_records_nothing` |
| N7 no snapshot | stage 1 counts `no_snapshot` (no row) and `zero_volume` | `Rules.test_names_with_no_snapshot_row_are_counted` |
| criterion 3 text | section 8.1: unverified (`no_year_at_floor`) when no year reaches 40 fires, never pass (D3) | `Years.test_the_year_criterion_has_three_states` |
| SPY 13:00:00 reading | section 4.2: one sentence (D3) | `Pieces.test_the_store_and_the_spy_count` |

## 8. The owner's choice: the paper's breakout (D4, code, D5)

The owner chose the paper's breakout as the PRIMARY entry, with its ATR and RVOL floors (2026-11-03); the lead
adopted the reviewer's recommendations for the rest. Status still DRAFT; nothing scored on real data.

| commit | what | suite |
| --- | --- | --- |
| `90497a7` | D4, prereg text only (below) | 625 OK, 17.5 s |
| `00e25c8` | the breakout code | 630 OK, 16.3 s |
| `bb87bb8` | D5, section 10's counts refreshed for the two floors | 630 OK, 16.2 s |

**D4 diff summary.** 2.1: the departures list drops the Entry bullet; Floors reads prior close not open, 20
sessions not 14, the dollar floor added, the ATR a simple mean of 14 true ranges. 3.3: the range bullet
(`below_atr`). 4.1: rows `RVOL_MIN` 1.0, `ATR_MIN` 0.50 USD, `ENTRY_LEVEL` (the first bar's high plus `TICK`, a
buy-stop placed at 09:35), `ENTRY_UNTIL` (the `NO_ENTRIES_AFTER` bucket, 71 or 35); `NO_ENTRIES_AFTER` acts on the
entry window of the primary and arm A, and the control. 4.3: the `RVOL_MIN` bullet (`below_rvol`). 4.4: F(D) are
orders, trades are the fills, every verdict is over fills. 4.5: the Entry bullet and the Exit call
(`check_entry_bar=True`). 5: arm E (the former primary), arm B on the fills. 6.1: a control per fill,
`entry_until=u`, eligible bars 1 through min(u, last - 1), the "So:" sentence. 9: the live record stores the armed
order at 09:35. 11: the buy-stop fill-bias bullet. 17 insertions, 11 deletions, one file.

**The code** (`00e25c8`), with its pins:

| item | change | pinned by |
| --- | --- | --- |
| `check_entry_bar` | `score_trade(..., check_entry_bar=False)`; True checks the fill bucket's own low first: a touch is the stop at the stop, exit bar k, no gap, MFE 0; the default path unchanged | test_mjonir_outcomes `EntryBar` (a touch, an untouched fill bar equal to the default, a short); the SIM_* pin and every chunk 2 test unchanged |
| `stop_fill` | `mjonir.rvol.stop_fill(bars, level, first, until)` -> (k, max(level, open)) or None | test_scanner_rvol `Rules.test_stop_fill` (a touch, a gap-through open, never reached, the cancel bar, the level exactly, tuples) |
| the floors | `ATR_MIN` (`below_atr`, `floors.min_atr_usd`, after the share floor) and `RVOL_MIN` (`below_rvol`, after the RVOL history); `atr_of` is one definition (trader-exit's arithmetic) | `Rules.test_the_guards_and_the_floors` (FLAT below_atr, QUIET below_rvol, the ATR floor off without the key); `Pieces.test_the_atr_is_trader_exits` |
| the runner | the order at the 9:30 high plus `TICK`, live to the `ENTRY_UNTIL` bucket; a fill scored from k with `check_entry_bar`, its control inside 1..min(until, last - 1); arm B, slip-x2 and the one-tick (the level a tick away, refilled) on the fills; `no_fill` counted, never scored; arm E = the old 09:35 entry; orders, fills, `no_fill` by session in the report | `Window.test_a_synthetic_window_scores_and_writes_the_sidecar` (fills and no_fills both present, every fill in 1..until at or above its level, every primary control inside its order's window, arm E on every order, arm B on every fill); `test_the_parameters_are_the_documents` (ATR_MIN, RVOL_MIN, ENTRY_LEVEL, ENTRY_UNTIL rows) |
| the scanner | rows carry `level`; floors gain `floors.min_atr_usd` (example config, `limits.FLOOR_KEYS`) and the RVOL floor; the record doc is `status "armed"`, `level`, `bar_index None`, `time "09:35"`, `cancel_at` = no_entries_after; watchlist hits carry `trigger {level, until}` | `Cli.test_the_record_rows_and_n_or`, `Cli.test_floors_come_from_the_config`, `Rules.test_the_rvol_arithmetic` |
| the record | an armed trigger stores its order; `score_day` resolves the fill with `stop_fill` (None -> `no_fill`, scored once, no control, outside the gate; the report line names it only when present), else entry = the fill, stop = the fill minus the plan's risk, `score_trade` from k with `check_entry_bar`, the control inside 1..entry_until | `Cli.test_the_record_rows_and_n_or` (a fill on bar 5 at its level, the stop from the plan's risk, the control in 1..71), `Cli.test_an_order_no_bar_reaches_is_no_fill_once` |

Pins edited (this fork's): test_budget `CONTRACT_CFG` and test_limits `test_the_example` gain `min_atr_usd`.

**Readings I made where the message did not carry the text.**
- 4.4: "the last two sentences of the first paragraph" taken literally would leave F(D) defined twice (fires,
  then orders); I replaced the sentence that defined F(D) as fires and the paragraph's last sentence, and kept
  "The paper ranks first ..." and "The alternative ...".
- The four new 4.1 rows, 6.1's "So:" sentence and section 11's buy-stop bullet were not quoted in the message; I
  wrote them to the stated content (same session, name, risk fraction, window, exit and costs for 6.1).
- Left as written because "nothing else in the file changes": section 5's one-tick line still says "the entry
  shifted `TICK`" (the code shifts the level and refills); 6.2 still says B2 differs from the primary only by the
  `TOP_K` selection (it now also differs by the entry: the baselines enter at the 9:30 close, as 6.2 itself says);
  6.1's delta paragraph and 8.1 still say "fires" (4.4's "every verdict of section 8 is over fills" governs); 2.1
  does not list the tick above the high as a departure (the paper's stop is at the high).
- `bar_stage(rows=False)` must now make the `RVOL_MIN` comparison to count `below_rvol`; it keeps and returns no
  value. `first_bar_coverage` counts the names that reached the RVOL check (eligible plus `below_rvol`).
- The live record's plan is trader-exit's at the order's level (cent prices, the ATR from Massive's adjusted daily
  bars); at scoring the fill is unrounded and the stop is the fill minus that plan's risk.

**D5: the counts re-run** at `00e25c8`, `nice -n 19`, from the worktree root: development 04:21:31 to 04:22:21
EST (50 s), holdout to 04:23:07 (46 s); no request (the walks, the splits and the first-bar store were cached); exit
0, no traceback. Unchanged from D2: the 68 reference walks (249 + 224 pages), 7,359 split rows, the sessions, every
early close verified. Changed, as pasted into section 10:

| | development | holdout |
| --- | --- | --- |
| eligible per session | median 251, IQR 194 to 323 (min 34, max 851) | median 296, IQR 219 to 395 (min 37, max 1,053) |
| `insufficient_history` | 426,883 | 219,143 |
| `split_guard` | 16,958 | 29,721 |
| `below_price` | 1,043,541 | 1,041,908 |
| `below_adv_usd` | 1,706,380 | 1,168,156 |
| `below_adv_shares` | 464,791 | 391,884 |
| `below_atr` | 99,302 | 115,988 |
| `no_first_bar` | 253 | 236 |
| `gap_guard` | 17 | 25 |
| `rvol_history_short` | 2,684 | 2,786 |
| `below_rvol` | 452,286 | 466,865 |
| warmup sessions | 14 | 0 |
| first_bar_coverage | 0.9959 | 0.9959 |

The two new causes are the table's `below_atr` and `below_rvol` rows (a first bar under its own 14-session mean is
the usual case); the median eligible names a session move from 1,003 and 1,223 (D2) to the medians above.
