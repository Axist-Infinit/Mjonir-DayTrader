# Chunk 2 review: measurement honesty

Builder: Opus (claude-opus-5-5). Written Tue 2026-11-03 between 01:00 and 02:00 EST. Branch
`feat/c2-measure`, worktree `.claude/worktrees/c2-measure`, off `feat/c1-data` = `311d840`. Market
closed throughout. Every number below was printed by Python; nothing was computed by hand.

## 1. Commits

| step | commit | on origin |
| --- | --- | --- |
| 2.1 + 2.2, `mjonir/stats.py`, `mjonir/costs.py`, the costs block | `33cd744` | yes |
| 2.3, `mjonir/outcomes.py` (`score_trade`), `tests/synth.py` | `45ca2bf` | yes |
| 2.4 + 2.5, the time machine net of costs, `mjonir/control.py` | `ded7306` | yes |
| 2.6, exit / size / check / ticket | `9e22c04` | yes |
| docs: README, RUNBOOK, this review | the commit that adds this file; see `git log` | pushed with it |

Explicit `git add` paths only; no force-push, no amend; each message ends with the Co-Authored-By line.

## 2. Tests

Each commit re-run in a throwaway detached worktree (`python3 -m unittest discover -s tests`):

| tree | result | runtime |
| --- | --- | --- |
| `311d840` (base, chunk 1 + 1c) | 432 OK | 10.4 s |
| `33cd744` (2.1, 2.2) | 457 OK (+25) | 9.8 s |
| `45ca2bf` (2.3) | 466 OK (+9) | 10.6 s |
| `ded7306` (2.4, 2.5) | 490 OK (+24) | 14.0 s |
| `9e22c04` (2.6) | 508 OK (+18) | 13.7 s |
| docs commit | 508 OK | about 14 s |

New test files: `test_mjonir_stats` (the Wilson pin 13/28 -> [0.2953, 0.6419], decided rate, net
break-even, seeded bootstraps, every verdict class, the banned words, the four modules parse as Python
3.8), `test_mjonir_costs` (tier edges, half spread, the TSLA worked check, the gate, the card, the
per-trade share basis, settings refusals, the example config), `test_mjonir_outcomes` (gap through the
stop, both touched, no target, the early close scored to bar 41, fragile margins, tuples and dicts, a
sell, the one-place grep), `test_mjonir_control` (eligible bars, identifier seeds order-free, a deleted
session changes nothing else, skips counted, the geometry, the delta-0 pin), `test_timemachine_measure`
(the SIM pin through the CLI, the reel net of costs, fragile and the one-tick flip, no average without
its interval, control and baseline, data.source from the document, synthetic outcomes, gap fills,
early closes used and scored to bar 41 or 40, a short day dropped, the year table and its sign-flip
note, no-target plans, the bars_5m path) and `test_measure_scripts` (exit, size, check, ticket with
costs on). `tests/synth.py` holds the synthetic sessions and the bars_5m stand-in.

The runtime grew by about 3.5 s: every upstream `machine()` call now also computes the intervals,
the control, the sensitivity and the baseline.

## 3. Every edited upstream assertion

Rule followed: no upstream test deleted; where a pin encodes upstream's mechanics it now runs under
those mechanics (costs off, gap fill at the stop) with the assertion unchanged; where the chunk changes
behaviour on purpose, the assertion is edited and listed here.

**Helpers (assertions unchanged, run under upstream's mechanics):**

| file | old | new | reason |
| --- | --- | --- | --- |
| tests/test_timemachine.py `machine()` | `tm.time_machine(text, plan, now, **kw)` | `**dict(UPSTREAM, **kw)` with `UPSTREAM = {"costs": None, "gap_fill": "stop"}` | costs are on and the gap fill is "open" by default; every Reel / Seeds / Bars / Plans pin (the SIM_* hashes, p_target 0.2938, avg_R 0.034, history -0.062, ...) keeps its value under the upstream mechanics |
| tests/test_exit.py `Cli.plan()` | `["plan", "--now", ...]` | adds `--no-costs` | the 1R reel is refused net of costs (0.77); the plan pins (REEL_PLAN key for key, the warning under min_reward_risk 1.5) are upstream's mechanics |
| tests/test_budget.py `cfg()` | the example config | the example config with `costs = {"slippage_tiers_bps": [[0, 0]], "commission_usd": 0, "spread_source": "none"}` | 8 shares, $46.88, the bracket fixture equality are gross numbers |
| tests/test_budget.py CLI calls | `test_cli_writes_one_bracket_order`, `test_cli_json_and_limit`, `test_prices_file_is_used_only_when_fresh`, `test_the_portfolio_cash_caps_the_size` argv | adds `--no-costs` | same |
| tests/test_risk.py `cfg()` | the example config | the same zero costs block | the PASS of the 8-share reel order and its $46.88 are gross |
| tests/test_risk.py CLI calls | `TheReel.test_cli`, `Cli.test_prices_file_freshness` argv | adds `--no-costs` | same |
| tests/test_broker.py `Flow.setUp` | `shutil.copy(CFG_PATH, self.cfg)` | writes the example config with the zero costs block | the two-yes flow needs the reel order to PASS trader-risk |

**Assertions edited because the behaviour changes on purpose:**

| test | old | new | reason |
| --- | --- | --- | --- |
| test_budget `TheReel.test_config_example_is_the_contract` (`CONTRACT_CFG`) | the 23 upstream keys | plus `"costs": {...}` (the mjonir/costs.py DEFAULTS) | the example config ships the costs block (2.2) |
| test_timemachine `Reel.test_the_verdict_says_coin_flip` | `doc["verdict"] == "Close to a coin flip: target first 29.4 % vs stop first 25.5 %."`; `doc["verdict_notes"] == [...]` | `doc["mc_shape"] == SHAPE + "target first 29.4 % vs stop first 25.5 %."`; `"verdict" not in doc`; `doc["verdict_history"]["text"] == "Cannot judge: 13 of 28 ... Net break-even at 1R with costs off is 50.0%."`; `doc["mc_notes"] == [...]` (same note); the `lean()` 0.536 / 0.5 assertion kept | no verdict reads the Monte Carlo; the verdict reads the history (2.4) |
| test_timemachine `Reel.test_the_text_report` | the substring `"Close to a coin flip: target first 29.4 % ...\n45.1 % of the replays ..."` | `SHAPE + "target first 29.4 % vs stop first 25.5 %.\n45.1 % of the replays ..."`; every other substring unchanged, including `"fired 33 times: 13 target, 15 stop, 5 neither. Average R -0.062"` | same |
| test_timemachine `Bars.test_a_half_day_is_left_out` | `doc["data"]["short_sessions_left_out"] == [{"date": "2026-09-04", "bars": 42}]` | `doc["data"]["incomplete_dropped"] == [...]` (same value) | the key is split into `early_close_used` and `incomplete_dropped`; 2026-09-04 is not an early close on the calendar, so it is dropped (pool 58 and history 58 unchanged) |
| test_timemachine `Plans.test_the_verdict_thresholds_at_1r` | six `tm.verdict(...)` assertions: "Close to a coin flip", "Leans toward the target", "Leans toward the stop", "Strongly toward the target", "Strongly toward the stop: target first 10.0 % vs stop first 60.0 %.", "No replay reached ... decides every one." | `tm.mc_shape_line(...)` equals `SHAPE + "target first 30.0 % vs stop first 26.0 %."`, `SHAPE + "target first 10.0 % vs stop first 60.0 %."`, `SHAPE + "no replay reached the target or the stop by 3:55 PM; the price at 3:55 PM decides every one."`; and for the four upstream (p_target, p_stop) pairs none of "coin flip", "Leans", "Strongly" appears | the MC line has no thresholds and no lean words (banned) |
| test_timemachine `Plans.test_a_2r_target_is_judged_against_its_break_even` | `tm.verdict(mc) == "Close to break-even: at 2R ... it did in 32 % (...)."`; `startswith("Leans toward the stop: at 2R ... 21 %")`; `startswith("Leans toward the target")`; `startswith("Strongly toward the target")`; `"at 1.5R ... 40 %" in tm.verdict(...)` | `tm.mc_shape_line(mc) == SHAPE + "at 2R ... it did in 32 % (...)."`; `startswith(SHAPE + "at 2R ... 21 %")`; `"it did in 43 %" in ...`; `"it did in 50 %" in ...`; `"at 1.5R ... 40 %" in tm.mc_shape_line(...)`; the two `verdict_notes` assertions unchanged | same |
| test_timemachine `Plans.test_2r_on_the_fixture_near_break_even` | `doc["verdict"] == "Close to break-even: at 2R ..."`, `doc["verdict_notes"] == []` | `doc["mc_shape"] == SHAPE + "at 2R ..."` (same numbers), `doc["mc_notes"] == []` | same |
| test_timemachine `Plans.test_2r_on_the_fixture_a_clear_lean` | `doc["verdict"] == "Strongly toward the stop: at 2R ..."`; `doc["verdict_notes"]`; the report substring `doc["verdict"] + notes` | `doc["mc_shape"] == SHAPE + "at 2R ..."` (same numbers); `doc["mc_notes"]` (same two notes); `doc["mc_shape"] + notes` in the report | same |
| test_timemachine `Cli.test_run_with_the_plan_end_to_end` | `"Close to a coin flip: target first 29.4 % vs stop first 25.5 %." in text` | `SHAPE + "target first 29.4 % vs stop first 25.5 %." in text`; the numeric pins (p_target 0.2938, avg_R 0.034, SIM_PATHS, history 33 / -0.062) unchanged and run under the DEFAULTS (costs on, gap fill open) | same |
| test_timemachine `Cli.test_json_output` | `doc["verdict"][:20] == "Close to a coin flip"` | `doc["verdict_history"]["text"][:13] == "Cannot judge:"` and `doc["mc_shape"][:17] == "Shape diagnostic "` | same |
| test_timemachine `Cli.test_chart` | `lines[-2:] == ["Close to a coin flip: ...", "45.1 % of the replays ..."]` | `lines[-2:] == [SHAPE + "target first 29.4 % vs stop first 25.5 %.", "45.1 % of the replays ..."]` (the chart now prints the history verdict, then the shape line and its notes) | same |

**Test helpers outside upstream's assertions:** `tests/_load.py` (upstream's helper, already changed in
chunk 1) now hides the Massive key from every test (`INFINIT_ROOT=/dev/null`, the four key variables
popped, kept in `HIDDEN` for the one fixture test that checks the key is in no fixture). Chunk 1's own
tests changed: `test_source_wiring` (serves `fetch_history_bars` and `fetch_adv_usd`; the exit and time
machine equalities run with `--no-costs`, the costs path is checked separately) and
`test_mjonir_fixtures` (reads the hidden key through `_load.HIDDEN`).

## 4. Acceptance

### 4.1 Suite

508 OK in 13.7 s at `9e22c04` (table in section 2).

### 4.2 The SIM_* pin

`tests/test_timemachine_measure.py::SimPin::test_no_costs_gap_fill_stop_sessions_60_is_upstream_bit_for_bit`
runs `timemachine.py run --plan plan-tsla.json --offline TSLA-60d5m.json.gz --now "2026-10-19 10:50"
--no-costs --gap-fill stop --sessions 60 --write` through `main()` and checks SIM_BANDS, SIM_PATHS,
SIM_HIST and SIM_TRADES. Upstream's own `Reel.test_bit_for_bit_with_the_reel_sim` and
`Reel.test_the_history_replay` hold under the same mechanics.

```text
$ cd tests && python3 -m unittest -v test_timemachine_measure.SimPin test_timemachine.Reel.test_bit_for_bit_with_the_reel_sim test_timemachine.Reel.test_the_history_replay
test_no_costs_gap_fill_stop_sessions_60_is_upstream_bit_for_bit (test_timemachine_measure.SimPin...) ... ok
test_bit_for_bit_with_the_reel_sim (test_timemachine.Reel.test_bit_for_bit_with_the_reel_sim) ... ok
test_the_history_replay (test_timemachine.Reel.test_the_history_replay) ... ok
Ran 3 tests in 1.071s
OK

$ python3 trader-timemachine/timemachine.py run ... --no-costs --gap-fill stop --sessions 60 --write <scratch>/pin.json   # hashes recomputed from the file
SIM_BANDS  b9b7c006a733c68b want b9b7c006a733c68b
SIM_PATHS  90f313ef40c576a0 want 90f313ef40c576a0
SIM_TRADES 0058bef72b0dcdee want 0058bef72b0dcdee
SIM_HIST   True
p_target, p_stop, mc avg_R, history avg_R: 0.2938 0.2548 0.034 -0.062
```

The history entry is the unrounded bar close (amendment e) and the hash still matches: the trade list
stores the entry rounded for display, and with the stop kept at its cent order price (or_mid floored)
no outcome or 2-decimal R moves on this fixture. With the stop unrounded too, one R moves (2026-09-30,
close outcome, 0.73 -> 0.74); that variant was measured and not used (section 6).

### 4.3 The TSLA reel net of costs (live ADV from Massive, upstream's Yahoo fixture for the bars)

The cost card (1R refused, 2R passes):

```text
$ python3 trader-exit/exit.py plan --symbol TSLA --entry 364.18 --or-high 362.18 --or-low 354.47 --time 10:15 --entry-bar 8 --date 2026-10-19 --now "2026-10-19 10:16" --source massive --target 1R
exit.py: net reward:risk 0.77 (gross 1.0, after a 0.7599 a share round trip, 0.130 R) is under your min_reward_risk 1: refused. A farther target (--target 2R) or a closer stop changes it.
(exit 1)

$ ... --target 2R --write <scratch>/plan-2r.json
Exit plan: TSLA long, Mon 2026-10-19, opening-range breakout on 5-minute bars
  Entry         $364.18 at 10:15 AM (bar 8)
  Stop          $358.32  opening-range midpoint: ($362.18 + $354.47) / 2 = $358.325, rounded down
  Target        $375.90  2R (two times the risk)
  Risk a share  $5.86 (1.61% of the entry)
  Reward:risk   2.0 gross, 1.66 net
  Costs: 0.7599 a share round trip = 0.130 R (4 bp slippage tier, ADV $12,729,948,354; 3 bp half spread, the default, unverified; $1 commission a side over 8 shares).
  Flat by       15:55 ET, win or lose: no overnight hold
(exit 0)
card: adv_usd 12729948354 (Massive: mean close x volume over the 20 sessions before 2026-10-19), slippage 4 bp,
half spread 3.0 bp (default), 7 bp a side, 8 shares, round trip 0.759852 a share ($6.08), cost_r 0.129668,
reward_risk gross 2.0, net 1.6556; spread gate unverified (no live quote for a past day)
```

trader-budget and trader-risk on the 2R plan (7 shares: the commission a share is $2/7, so net 1.64):

```text
$ python3 trader-budget/size.py --plan <scratch>/plan-2r.json --config trader-budget/config.example.json --portfolio /nonexistent --now "2026-10-19 10:16" --write <scratch>/orders-2r.json
  max loss      ($50 - $2 commissions) / (5.86 risk + 0.5099 round trip) a share   7 shares  <- binds
Size: 7 shares of TSLA = $2,549.26 at 364.18. Max loss at the stop, net of costs: 7 x (5.86 + 0.5099) + $2 = $46.59 ($41.02 before costs).
  buy 7 TSLA, market, day, take-profit 375.90, stop-loss 358.32
$ python3 trader-risk/check.py --orders <scratch>/orders-2r.json --config trader-budget/config.example.json ... --no-write
PASS  #1 buy TSLA 7 shares, entry
          max loss $46.59 net of costs ($41.02 gross) (limit $50), reward:risk 1.64 net (2.00 gross) (min 1, net)
        ~ spread unverified: spread not measured live (missing): the 0.59 limit cannot be checked
$ python3 trader-risk/check.py --orders tests/fixtures/trader-risk/orders-tsla.json --config trader-budget/config.example.json ... --no-write
BLOCK #1 buy TSLA 8 shares, entry
        - loss: 8 shares x (5.86 risk + 1.3110 round trip) + $2 commissions = $59.37 at the stop, net of costs, over your $50 max loss per trade
        - reward:risk: net 0.58 (gross 1.00; target 370.04, entry 364.18, stop 358.32, a 1.5610 a share round trip) is under your minimum 1
```

(Upstream's order file has no cost card, so trader-risk prices it at the config's most expensive tier,
15 bp plus 3: that is the 1.3110.)

The time machine, the 1R reel plan, 60 days of upstream's Yahoo bars, ADV from Massive:

```text
$ python3 trader-timemachine/timemachine.py run --plan tests/fixtures/trader-budget/plan-tsla.json --offline tests/fixtures/trader-timemachine/TSLA-60d5m.json.gz --source massive --now "2026-10-19 10:50" --write <scratch>/tm-reel.json
TSLA buy, Monday 2026-10-19: entry 364.18 at 10:15 AM (bar 8), stop 358.32, target 370.04 (1R, risk 5.86 a share).
Costs: 0.7599 a share round trip = 0.130 R (4 bp slippage tier, ADV $12,729,948,354; 3 bp half spread, the default, unverified; $1 commission a side over 8 shares).

History: the same rule (15-min opening range, stop at the opening-range midpoint, 1R target) on each of those 59 real sessions fired 33 times: 13 target, 15 stop, 5 neither. Average R, net of costs, -0.261 (95 % bootstrap interval -0.592 to +0.074, n 33).
  Gross average R -0.062 (95 % bootstrap interval -0.392 to +0.263, n 33); costs 0.199 R a trade on average.
  Decided: 13 of 28 hit the target first (46.4 %, 95 % Wilson 29.5 % to 64.2 %); 11 of the 28 decided by under 0.05 R (fragile).
  One-tick sensitivity: the entry 1 cent higher flips 1 outcome, 1 cent lower flips 0 (of 33).
  By year, net R a trade: 2026 -0.261 (95 % bootstrap interval -0.592 to +0.074, n 33).
  Random-entry control (3 draws a firing session, the rule's risk percent, target multiple and flat-by): 99 trades, net average R +0.032 (95 % bootstrap interval -0.118 to +0.181, n 99); 35 of 51 hit the target first (68.6 %, 95 % Wilson 55.0 % to 79.7 %).
  Baseline, buy any morning strength (the last opening-range bar's close, every session; a diagnostic, not a verdict): 35 trades, net average R -0.317 (95 % bootstrap interval -0.740 to +0.059, n 35); 21 of 35 hit the target first (60.0 %, 95 % Wilson 43.6 % to 74.4 %).
  Data: yahoo (Yahoo v8 chart: the adjustment is not stated by the source); 0 early-close session(s) used, 0 incomplete dropped.

Cannot judge: 13 of 28 decided fires hit the target (46.4%, 95% Wilson [29.5%, 64.2%]); n is below the 40-fire floor. Net break-even at 1R after costs is 56.5%.
Behind the random-entry control: net delta -0.293 R a trade (95% bootstrap [-0.581, -0.013]) over 33 paired sessions.

10,000 replays of the rest of the session, 10:15 AM to 4:00 PM (69 five-minute bars), seed 19.
Each bar is drawn whole from TSLA's own 5-min bars at the same time of day (+-2 bars) over its last 59 full sessions (2026-07-27 to 2026-10-16).

  target first   29.4 %
  stop first     25.5 %
  neither        45.1 %   still open at 4:00 PM
  green          51.7 %   target first, or above the entry at 4:00 PM

  Price at 4:00 PM: median 364.36, 90 % of replays between 355.54 and 373.54.
  Average R: +0.034 (R = the 5.86 risk: +1R at the target, -1R at the stop, worse on a gap through it). After the 0.130 R round trip: -0.096.

Shape diagnostic (unconditional per-slot bootstrap, not conditioned on the breakout, vol regimes mixed): target first 29.4 % vs stop first 25.5 %.
45.1 % of the replays hit neither by 4:00 PM; the price at 4:00 PM decides those.

A simulation built from TSLA's own last 59 full sessions. It is not a prediction: earnings, news and halts can do things those sessions never did. Same seed, same numbers. Repeat this run with --seed 19.
Wrote <scratch>/tm-reel.json.
Next: /trader-budget sizes it to your budget and your max loss per trade.
fragile 11 of decided 28 ['2026-07-28', '2026-08-03', '2026-08-06', '2026-08-07', '2026-08-21', '2026-08-27', '2026-08-31', '2026-09-23', '2026-10-01', '2026-10-05', '2026-10-15']
sensitivity {'up': {'flips': 1, 'dates': ['2026-08-06']}, 'down': {'flips': 0, 'dates': []}, 'flips': 1}
```

The one-tick flip is 2026-08-06, the chunk 1 vendor flip: its target was touched by 2 cents (0.0073 R).
The same 60 days with the 2R plan: 3 of 20 decided, average R -0.352 net (-0.678 to +0.017, n 33),
"Cannot judge: 3 of 20 decided fires hit the target (15.0%, 95% Wilson [5.2%, 36.0%]); n is below the
40-fire floor. Net break-even at 2R after costs is 37.7%."; control: "Behind the random-entry control:
net delta -0.394 R a trade (95% bootstrap [-0.661, -0.121]) over 33 paired sessions."

### 4.4 Live: two years, the reel plan

`timemachine.py run --plan tests/fixtures/trader-budget/plan-tsla.json --source massive --years 2
--control-draws 3 --now "2026-10-19 10:15" --json`: 20.5 s cold (the API, 10 pages), then 1.9 s from the
cache. From the JSON:

```text
source massive | data.source api | data.adjustment {'adjusted': True, 'as_of': '2026-11-03', 'basis': 'adjusted as of 2026-11-03'}
range 500d | pool_sessions 494 (2024-10-21 .. 2026-10-16) | history sessions 499
early_close_used [('2024-11-29', 42, 41), ('2024-12-24', 42, 41), ('2025-07-03', 42, 41), ('2025-11-28', 42, 41), ('2025-12-24', 42, 41)]
incomplete_dropped []
triggered 285: target 130, stop 116, close 39; gap fills 0
decided 130 of 246 (p 0.5285, Wilson 0.4661 .. 0.5899)
net expectancy -0.125 [-0.235, -0.016] n 285 | gross +0.056 [-0.055, +0.165] n 285 | mean cost_r 0.1814
fragile 71 of 246 decided
one tick: up 2 ['2025-04-30', '2026-05-22'], down 0 []
by_year 2024: n 31, net -0.080 [-0.395, +0.225] n 31, decided 15 of 26
by_year 2025: n 142, net -0.099 [-0.252, +0.052] n 142, decided 64 of 122
by_year 2026: n 112, net -0.171 [-0.354, +0.004] n 112, decided 51 of 98
by_year_note None
control: 855 trades on 285 sessions, skipped {'risk_floor': 0, 'no_eligible_bar': 0}, net -0.073 [-0.126, -0.016] n 855, decided 307 of 527
control delta -0.052 [-0.165, +0.061] over 285 sessions (rule mean -0.125, control mean -0.073)
baseline: 236 trades, 263 sessions skipped, net -0.486 [-0.634, -0.336] n 236, decided 118 of 233
verdict_history unverified/straddles: Edge not distinguishable from break-even: 130 of 246 decided fires hit the target (52.8%, 95% Wilson [46.6%, 59.0%]); net break-even at 1R after costs is 56.5%, inside that interval.
verdict_control unverified/straddles: Not distinguishable from the random-entry control: net delta -0.052 R a trade (95% bootstrap [-0.165, +0.061]) over 285 paired sessions; the interval includes 0.
cost card: ADV 12,729,948,354, 4 bp tier, 7 bp a side, 8 shares, cost_r 0.1297
```

`data.source` is `api` on the cold run and `cache` on the warm one: both come from `bars_5m(info=...)`,
never from the flag. The human report of the same run (warm cache):

```text
TSLA buy, Monday 2026-10-19: entry 364.18 at 10:15 AM (bar 8), stop 358.32, target 370.04 (1R, risk 5.86 a share).
Costs: 0.7599 a share round trip = 0.130 R (4 bp slippage tier, ADV $12,729,948,354; 3 bp half spread, the default, unverified; $1 commission a side over 8 shares).

History: the same rule (15-min opening range, stop at the opening-range midpoint, 1R target) on each of those 499 real sessions fired 285 times: 130 target, 116 stop, 39 neither. Average R, net of costs, -0.125 (95 % bootstrap interval -0.235 to -0.016, n 285).
  Gross average R +0.056 (95 % bootstrap interval -0.055 to +0.165, n 285); costs 0.181 R a trade on average.
  Decided: 130 of 246 hit the target first (52.8 %, 95 % Wilson 46.6 % to 59.0 %); 71 of the 246 decided by under 0.05 R (fragile).
  One-tick sensitivity: the entry 1 cent higher flips 2 outcomes, 1 cent lower flips 0 (of 285).
  By year, net R a trade: 2024 -0.080 (95 % bootstrap interval -0.395 to +0.225, n 31); 2025 -0.099 (95 % bootstrap interval -0.252 to +0.052, n 142); 2026 -0.171 (95 % bootstrap interval -0.354 to +0.004, n 112).
  Random-entry control (3 draws a firing session, the rule's risk percent, target multiple and flat-by): 855 trades, net average R -0.073 (95 % bootstrap interval -0.126 to -0.016, n 855); 307 of 527 hit the target first (58.3 %, 95 % Wilson 54.0 % to 62.4 %).
  Baseline, buy any morning strength (the last opening-range bar's close, every session; a diagnostic, not a verdict): 236 trades, net average R -0.486 (95 % bootstrap interval -0.634 to -0.336, n 236); 118 of 233 hit the target first (50.6 %, 95 % Wilson 44.3 % to 57.0 %).
  Data: cache (adjusted as of 2026-11-03); 5 early-close session(s) used, 0 incomplete dropped.

Edge not distinguishable from break-even: 130 of 246 decided fires hit the target (52.8%, 95% Wilson [46.6%, 59.0%]); net break-even at 1R after costs is 56.5%, inside that interval.
Not distinguishable from the random-entry control: net delta -0.052 R a trade (95% bootstrap [-0.165, +0.061]) over 285 paired sessions; the interval includes 0.

10,000 replays of the rest of the session, 10:15 AM to 4:00 PM (69 five-minute bars), seed 19.
Each bar is drawn whole from TSLA's own 5-min bars at the same time of day (+-2 bars) over its last 494 full sessions (2024-10-21 to 2026-10-16).

  target first   43.1 %
  stop first     42.2 %
  neither        14.7 %   still open at 4:00 PM
  green          50.5 %   target first, or above the entry at 4:00 PM

  Price at 4:00 PM: median 364.27, 90 % of replays between 351.13 and 377.29.
  Average R: +0.011 (R = the 5.86 risk: +1R at the target, -1R at the stop, worse on a gap through it). After the 0.130 R round trip: -0.119.

Shape diagnostic (unconditional per-slot bootstrap, not conditioned on the breakout, vol regimes mixed): target first 43.1 % vs stop first 42.2 %.

Used 5 early-close session(s) in the history, scored to the 1:00 PM close: 2024-11-29, 2024-12-24, 2025-07-03, 2025-11-28, 2025-12-24.
A simulation built from TSLA's own last 494 full sessions. It is not a prediction: earnings, news and halts can do things those sessions never did. Same seed, same numbers. Repeat this run with --seed 19.
Next: /trader-budget sizes it to your budget and your max loss per trade.
```

The 2R plan over the same two years (warm cache): fired 285 times, 61 target, 131 stop, 93 neither;
average R -0.093 net (-0.231 to +0.044, n 285; gross +0.088, -0.048 to +0.225); "Edge not
distinguishable from break-even: 61 of 192 decided fires hit the target (31.8%, 95% Wilson [25.6%,
38.7%]); net break-even at 2R after costs is 37.7%, inside that interval."; "Not distinguishable from
the random-entry control: net delta -0.071 R a trade (95% bootstrap [-0.216, +0.068]) over 285 paired
sessions; the interval includes 0."; 44 fragile of 192 decided; one-tick flips 0 and 0.

### 4.5 The Zarattini plan, same TSLA day

```text
$ python3 trader-exit/exit.py plan --symbol TSLA --entry 364.18 --or-high 362.18 --or-low 354.47 --time 10:15 --entry-bar 8 --date 2026-10-19 --now "2026-10-19 10:16" --source massive --target none --exit close --stop datr:0.10 --write <scratch>/plan-z.json --json
(the plan JSON as printed, the cost card and the note shown apart)
{
 "created_by": "trader-exit",
 "symbol": "TSLA",
 "side": "buy",
 "date": "2026-10-19",
 "setup": "orb",
 "entry": 364.18,
 "entry_time": "10:15 AM",
 "entry_bar": 8,
 "interval": "5m",
 "opening_range": {
  "high": 362.18,
  "low": 354.47,
  "minutes": 15
 },
 "stop": 363.09,
 "stop_rule": "datr",
 "stop_label": "0.1 x the 14-day daily ATR under the entry",
 "target": null,
 "target_r": null,
 "target_label": "none: out at the stop or at the flat-by close",
 "exit": "close",
 "risk_per_share": 1.09,
 "reward_risk": null,
 "flat_by": "15:55",
 "stop_detail": "daily ATR $10.8571 over the 14 sessions before the plan's day, rounded down",
 "created_at": "2026-10-19T14:16:00Z",
 "atr": 10.8571,
 "atr_bars": 14,
 "reward_risk_gross": null,
 "reward_risk_net": null,
 "warnings": [
  "No target: the plan exits at the stop or at the 15:55 flat-by close; reward:risk is not measured (trader-risk checks allow_no_target)."
 ]
}
costs: {"adv_usd": 12729948354, "slippage_bps": 4.0, "half_spread_bps": 3.0, "spread_basis": "default", "per_side_bps": 7.0, "shares": 45, "shares_basis": "floor(50.00 max loss / 1.09 risk) = 45 shares", "round_trip_per_share": 0.554296, "cost_r": 0.508529, "reward_risk_gross": null, "reward_risk_net": null, "flags": ["spread_missing"]}
(exit 0)

$ python3 trader-budget/size.py --plan <scratch>/plan-z.json --config trader-budget/config.example.json --portfolio /nonexistent --now "2026-10-19 10:16" --write <scratch>/orders-z.json
No target: an OTO order (the entry and its stop-loss); flatten by 15:55. Reward:risk is not measured, so the min_reward_risk refusal is skipped (trader-risk checks allow_no_target).
  max loss      ($50 - $2 commissions) / (1.09 risk + 0.5099 round trip) a share  30 shares
  position cap  75% of $5,000 = $3,750 / 364.18                             10 shares  <- binds
Size: 10 shares of TSLA = $3,641.80 at 364.18. Max loss at the stop, net of costs: 10 x (1.09 + 0.5099) + $2 = $18 ($10.90 before costs).
Proposed OTO order (place_stock_order arguments, nothing has been placed):
  buy 10 TSLA, market, day, stop-loss 363.09, no take-profit
{"symbol": "TSLA", "side": "buy", "qty": "10", "type": "market", "time_in_force": "day", "order_class": "oto",
 "stop_loss_stop_price": "363.09",
 "why": "opening-range breakout on TSLA: 10 shares, bound by your position cap (10 x (1.09 risk + 0.5099 round trip) + $2 commissions = $18 at the stop); no take-profit: flatten by 15:55",
 "plan": {"entry": 364.18, "stop": 363.09, "target": null, "risk_per_share": 1.09, "max_loss": 18.0, "setup": "orb",
          "entry_time": "10:15 AM", "flat_by": "15:55", "max_loss_gross": 10.9, "exit": "close", "costs": {...}}}

== check.py, the example config (allow_no_target unset: false)
verdict BLOCK   checks [('target', 'block'), ('spread', 'unverified')]
  - reward:risk: no target to measure it against (min_reward_risk 1; allow_no_target is false)
  ~ spread unverified: spread not measured live (missing): the 0.11 limit cannot be checked
== check.py, allow_no_target true
verdict PASS    checks [('target', 'pass'), ('spread', 'unverified')]
    target: no target (allow_no_target): out at the stop or flat by 15:55
  ~ spread unverified: spread not measured live (missing): the 0.11 limit cannot be checked
== check.py, allow_no_target true, the order's plan without exit / flat_by
verdict PASS    checks [('target', 'unverified'), ('spread', 'unverified')]
  ~ unverified: no target and no exit rule in the order's plan (exit close with a flat_by): how it exits cannot be checked
  ~ spread unverified: spread not measured live (missing): the 0.11 limit cannot be checked
```

The third state is a warning by default and a block with `"block_on_unverified": true` (tested). The
round trip is 0.509 R of this plan's 1.09 risk.

### 4.6 README and RUNBOOK

`git diff --stat 311d840 -- README.md docs/RUNBOOK.md`: 96 insertions, 36 deletions.

- README roadmap: both chunk 2 rows read "built on `feat/c2-measure` (not merged yet)".
- README "A note on the numbers" is replaced by "The TSLA example, net of costs": the costs (ADV $12.7B,
  4 bp tier, $0.76 a share, 0.130 R), the 1R plan refused (net 0.77) and the move to 2R (1.66 net, 7
  shares, $46.59), the 60-day reading ("Cannot judge", 13 of 28, Wilson 29.5 % to 64.2 %, average R
  -0.261 net with its interval, 11 fragile, one flip; the 2R rule: 3 of 20, cannot judge either), the
  two-year reading (285 fires, -0.125 net, -0.235 to -0.016, 130 of 246, not distinguishable from
  break-even or from the control, delta -0.052; the 2R rule's numbers), and "one stock and one rule,
  measured on past sessions; not a forward result; promises nothing". The $100k notional sizing (8 shares
  -> about 170) is named as chunk 3, not built.
- README upstream walkthrough, steps 4 to 7 and the tools line: 1R refused, 2R 375.90 (2.0 gross, 1.66
  net); the time machine verdict is the "Cannot judge" line with the net average and its interval, the MC
  as a shape diagnostic; 7 shares, $46.59 net (upstream's 8 shares and $46.88 named as gross); the risk
  check names the net checks and the spread. `exit.py plan --target 2R` in the tools block.
- RUNBOOK: the status line names chunk 2; the arm step's "(chunk 2)" markers are dropped and replaced by
  the commands as built (exit with `--source massive`, the Zarattini form, the time machine with
  `--years 2 --control-draws 3`, size net of costs, check with the spread and the no-target check); the
  $100k sizing and the percent limits stay marked chunk 3.

## 5. How the plan and the amendments are met

- **(a) No history average without its interval and n.** Every history, by-year, control and baseline
  average prints as `mean (95 % bootstrap interval lo to hi, n N)` (`_iv()` in the report); a test walks
  every report line with "Average R" outside the MC block. The MC's average is the shape diagnostic.
- **(b) Touch margins and fragile.** `score_trade` returns `margin_target`, `margin_stop` (dollars) and
  `_r` (R) over the bars after the entry up to the exit bar, `decision_margin_r` and `fragile` (< 0.05 R).
  The history counts `fragile` beside the decided count.
- **(c) One-tick sensitivity.** `sensitivity()` re-scores the history with the entry +0.01 and -0.01 and
  prints the flip count and dates.
- **(d) Source and basis from the data.** `data.source` and `data.adjustment` come from the document
  (`meta.mjonir.store` filled from `bars_5m(info=...)`, or `meta.mjonir.source` of a bridged file, or
  "yahoo" for a Yahoo document), never from `--source`. One store per run by construction:
  `compute()` takes exactly one of `--offline`, Massive (`bars_5m`, one source) or Yahoo.
- **(e) Unrounded arithmetic.** The history, control and baseline enter at the raw bar close (364.176 for
  the 10:10 bar) and compute the target from it; rounding is display only. The stop stays the rule's cent
  order price (section 6).
- **One place for outcomes.** `grep -n ">= target\|<= stop\|>= tgt\|<= stp" trader-*/*.py mjonir/*.py`
  finds only `mjonir/outcomes.py:42` and `:44` (pinned by a test). The MC loop keeps its own loop for the
  random draws but asks `outcomes.touch()` for every bar's exit; `score_trade()` uses the same `touch()`.
- **No verdict reads the MC.** `verdict_history` takes the history counts and its net expectancy;
  `verdict_control` the paired delta. The MC prints `mc_shape` and `mc_notes`; the `verdict` key is gone.
- **cost_r once per trade.** `score_trade` returns `net_r = gross_r - cost_r`; the history passes each
  trade's own `cost_r` once (a test checks net = gross - cost_r per trade).
- **Control seeds.** `random.Random("%s:%s:%s" % (seed, symbol, date))`, identifiers only (tested
  order-free, and deleting a session changes no other).
- **Non-empty inputs.** `score_trade`, `expectancy_ci` and `paired_delta_ci` raise on empty input;
  `bars_5m` already did.
- **One clock.** The four measurement modules hold no clock; `fetch_history_bars` uses `K.now_et()`.
- **Python 3.8.** stats, costs, outcomes and control parse with `ast.parse(feature_version=(3, 8))`
  (tested) and import only math, random and re; the trader scripts import them through a `_measure()`
  shim on every run, whatever `--source` is.
- **Kalex store.** sha256 after the live runs (2026-11-03T06:09:24Z):
  `2f5b1750164bd08db49bda4c9a2b2d4d1f24a3b32d5ec055ec1feef0bb39f45b`, size 10,739,052,544, mtime
  2026-07-15: unchanged from chunk 1.

## 6. Decisions, deviations, owed and uncertain

- **A test reached the network once, during development (fixed).** While building 2.4, chunk 1's wiring
  test served the old fetcher name; the renamed `fetch_history_bars` went unserved and, because the
  test process could read `~/Infinit/.env`, built a real client: a handful of paced, read-only requests
  (the split list and the 60-session TSLA 5m range) into the throwaway test cache. No 403, nothing
  written outside the temp folder. Fixed at the root: `tests/_load.py` now hides the key from every test,
  and the wiring test serves the new fetchers. Since then a forgotten path fails as "no key"
  (unverified), as the exit wiring test showed.
- **Amendment (e) and the stop.** Entry and target are unrounded; the stop stays a cent price (the
  rule's `cents_away`, what an order would rest at, and the live plan's 358.32). That keeps SIM_TRADES
  bit for bit. Unrounding the stop too moved one R (2026-09-30, 0.73 -> 0.74); not adopted. The exit
  plan itself is an order and stays in exact cents.
- **The README estimates against what was measured.** The plan expected the 60-day net average "about
  -0.19"; measured -0.261. The history charges each trade its own round trip; those trades' risks are
  smaller than the reel's 5.86, so their mean cost is 0.199 R, not 0.130. The plan expected the 2R net
  reward:risk "about 1.75"; measured 1.66 on exit's 8-share basis and 1.64 on size's 7 shares. 1.75 is
  what the commission a share gives near 170 shares (the chunk 3 notional sizing).
- **Wilson at n = 40.** The plan's parenthesis says the half-width at p = 0.5 is 14.6 points; Wilson
  gives 14.8 (the test pins 14.8).
- **Fixed wording I wrote.** The plan fixed the history templates' heads; the no-target templates (net
  expectancy against 0) and the five control templates are mine, in the same style. "Bare edge" is
  enforced as `\bedge\b` not followed by "not distinguishable from": the plan's own straddle template
  starts "Edge not distinguishable from break-even".
- **The control's fail needs no floor.** As the plan states it, `fail` when `delta.hi < 0` whatever n:
  the 60-day reel reads "Behind the random-entry control" on 28 decided fires. Pass needs n >= 40.
- **Cost model choices.** The history, control and baseline charge every past trade the plan card's
  per-side bps (the plan day's ADV tier and spread) and spread the commission over that trade's own
  floor(max loss / risk) shares (max loss from `trader/config.json`, else upstream's $50). exit.py's
  share basis is the same rule (or `--shares`). Chunk 3's notional sizing will change the share basis.
- **Floors.** The control and the baseline skip a risk under 0.05 % of the entry (trader-exit refuses
  such a stop) and count it; the rule's own history does not filter (upstream's semantics; the SIM pin).
  The baseline also skips sessions where the last opening-range bar closes at or under the stop (263 of
  499 on two years, counted).
- **The fragile window.** Margins are measured from the bar after the entry to the exit bar, not to the
  session's end: after the exit the trade is over.
- **Early closes.** The time machine takes them from its own list (seeds plus the overlay) and from the
  history document's `meta.mjonir.early_closes` (the calendar's rules, verified by the bar count), so the
  Massive path labels 2024 and 2025 early closes; a Yahoo file only knows the overlay's years. A 42-bar
  day not on the calendar is dropped and listed.
- **datr.** Always Massive daily bars (no other daily source exists here), whatever `--source` is;
  without them the plan is refused with "unverified". The time machine's history replays a datr plan
  with the plan day's stop distance as a percent of the entry (upstream's `pct` fallback); a per-session
  daily ATR is not computed. Owed if the Zarattini form is to be measured over years (chunk 3.5's
  runner).
- **Config keys used early.** `allow_no_target` (default false, upstream's block) and
  `block_on_unverified` (default false: a warning) are read by check.py now; chunk 3.2 ships them in the
  example config. `min_reward_risk_basis` defaults to net in code.
- **The spread for a past day.** exit.py asks a quote only for today's plan; a replay's card says "no live
  quote for a past day" and the gate is unverified. check.py asks the live NBBO only under `--source
  massive`; otherwise it uses the plan's quote if under 60 s old.
- **Labels.** `data.source` is api, cache, kalex, flatfile or yahoo; the top-level `source` keeps chunk
  1's meaning (offline, yahoo, massive, kalex, flatfile). `--sessions` and `--years` apply to `--source
  massive` only; an `--offline` file is read whole.
- **Skill docs.** `trader-timemachine/SKILL.md` was rewritten where it narrated the MC verdict ("coin
  flip", "leans"); exit, budget, risk and broker each gained one costs section. The Safety blocks are
  untouched (pinned identical).
- **Not done here:** the $100,000 notional and percent sizing (chunk 3.2), the forward record (3.1), any
  Massive call in a test. No live call answered 403. `~/Odyssey`, `~/Kalex` and `~/Infinit` were only
  read (the two port sources, the key, the Kalex store's coverage and hash).
