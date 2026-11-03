# Chunk 3a review: the forward record and risk in percent of the trade notional

Builder: Opus (claude-opus-5-5). Written Tue 2026-11-03, about 01:00 to 02:30 EST. Branch `feat/c3-record`,
worktree `.claude/worktrees/c3-record`, off `feat/c2-measure` = `8d00640`. Market closed throughout. Plan steps 3.1
(trader-record) and 3.2 (risk in percent) only; 3.3 to 3.5 (the RVOL prereg, scanner and study) were not started.
Every number below was printed by Python.

## 1. Commits

| step | commit | on origin |
| --- | --- | --- |
| 3.1, `trader-record/record.py`, `mjonir/ledger.py`, the entry and ticket hooks, the hermetic record dir | `a7cd801` | yes |
| 3.2, `mjonir/limits.py`, the percent example config, size.py, check.py, ticket.py fill | `d349f14` | yes |
| 3.2 follow-up: the ADV floor's unverified reason, the unused `--budget` note | `8945476` | yes |
| docs: README roadmap, RUNBOOK markers, this review | the commit that adds this file; see `git log` | pushed with it |

Explicit `git add` paths only; no force-push, no amend; each message ends with the Co-Authored-By line.

## 2. Tests

Each commit re-run in a throwaway detached worktree (`python3 -m unittest discover -s tests`):

| tree | result | runtime |
| --- | --- | --- |
| `8d00640` (base, chunks 1 and 2 with 2c) | 514 OK | 13.3 s |
| `a7cd801` (3.1) | 545 OK (+31) | 13.6 s |
| `d349f14` (3.2) | 572 OK (+27) | 14.3 s |
| `8945476` (follow-up) | 572 OK | 14.1 s |
| docs commit | 572 OK | about 13.5 s |

New test files: `tests/test_record.py` (29: the open modes, only the ledger names the files, Python 3.8; corrupt,
cut and not-a-row lines named by line; one score line per id; a trigger appended once and a decision once; a level
setup with no plan recorded and scored no_data; a plan for another day not used; the `add` CLI; score_day equal to
the time machine's `history_replay` on 13 synthetic cent-priced sessions, gap fills and an early close scored to bar
40; `last_bar` and `entry_until`; a planted spike on the trigger bar and the bar before moves nothing; bars not all in
yet are not scored; the control inside the entry window, seeded by identifiers, idempotent; ticket decline appends
the skipped decision; taken with both fills scores `fill_basis` broker, a missing leg stays paper; realized dollars and
the streak; the gate's three outcomes; the footer on every report; the journal's blocks; the entry hook once, `--no-record`
and `--plan`; `today_et` equal to `mjonir.calendar.today_et` across DST), `tests/test_limits.py` (26: the derivation,
the stricter of two with warnings naming both, percent arithmetic, bad configs, the formula on 300 random plans, the
reel's 156 shares and its printed lines, the notional binding, a legacy $50 cap, each new check in its three states,
the streak pause cleared after one session and counted over Thanksgiving, legacy configs untouched, risk.json's
basis, the derived loss cap, the paper portfolio starting at one notional) and `tests/test_zz_record_untouched.py`
(2: discovered last, it compares the repo's `record/` with the snapshot `tests/_load.py` took when the first test
module loaded, byte for byte, and asserts `TRADER_RECORD_DIR` points outside the repo). The +27 of 3.2 is
`test_limits.py` plus the upstream-contract pin in `test_budget.py`.

The runtime grew under a second: the record tests are synthetic and in-process.

## 3. Every edited upstream assertion

Rule followed: no upstream test deleted or loosened. Where a pin encodes upstream's dollar mechanics it now reads
the chunk 2 example config, kept byte for byte as `tests/fixtures/trader-budget/config-upstream.json`, with the
assertion unchanged; the one assertion about the example config itself is edited, because the example changes on
purpose.

**Assertion edited (the behaviour changes on purpose):**

| test | old | new | reason |
| --- | --- | --- | --- |
| test_budget `TheReel.test_config_example_is_the_contract` | `config.example.json == CONTRACT_CFG` (upstream's 23 keys plus the chunk 2 costs block) | `config.example.json == CONTRACT_CFG`, now the percent contract: `sizing`, `limits_pct`, `floors`, `min_reward_risk_basis` net, `allow_no_target` true, `block_on_unverified` true, `pdt_guard` false, the costs block; no `budget`, `cash_buffer_pct`, `max_position_pct` or `max_order_usd`; `max_loss_per_trade_usd`, `max_daily_loss_usd` and `max_trades_per_day` kept, null | the owner's decision (3.2). The old contract is still pinned: new `test_the_upstream_contract_is_kept_as_a_fixture` asserts the fixture equals it key for key (`UPSTREAM_CONTRACT`) |

**Helpers (assertions unchanged, run on the chunk 2 config fixture):**

| file | old | new |
| --- | --- | --- |
| tests/test_budget.py `CFG` (cfg() and every plan-mode CLI call) | `trader-budget/config.example.json` | `tests/fixtures/trader-budget/config-upstream.json` |
| tests/test_risk.py `CFG_PATH` (cfg(), `TheReel.test_cli`, `Cli.test_prices_file_freshness`) | the example | the fixture |
| tests/test_broker.py `CFG_PATH` (`Flow.setUp`) | the example | the fixture |
| tests/test_measure_scripts.py `CFG` (chunk 2's own pins: $50, the budget) | the example | the fixture |

**Not edited:** `tests/test_repo.py`. Its `test_day_trading_limits_ship_in_the_example_config` asserts the keys
`max_loss_per_trade_usd`, `max_daily_loss_usd`, `max_trades_per_day`, `min_reward_risk`, `require_stop`,
`no_entries_after`, `flat_by` are IN the example: they still are. The three dollar keys are null, which
`derive_limits` reads as not set, so they never become a stricter $50 beside the 1 % (a judgment call, named here;
`tests/test_limits.py` asserts the null values and the percent blocks). `test_paper_trading_is_the_default` holds.

**Test helper outside upstream's assertions:** `tests/_load.py` (upstream's helper, changed in chunks 1 and 2)
now points `TRADER_RECORD_DIR` at a throwaway folder (removed at exit) and snapshots the repo's `record/`
(`RECORD_BEFORE`) for the last-run test.

## 4. Acceptance

### 4.1 Suite

572 OK in 14.1 s at `8945476` (section 2); every edited assertion is in section 3.

### 4.2 A scripted offline day on the Yahoo TSLA fixture (2026-10-19)

cwd a scratch folder with `trader/config.json` = the example config, `TRADER_RECORD_DIR=<scratch>/acc2/record`.
The Yahoo fixture holds the session only to 10:49 (it was fetched then), so `score` on it is unverified (exit 2,
nothing written). `TSLA-full-day.json` is the same session's 78 regular-hours bars built OFFLINE from the recorded
Massive fixture `tests/fixtures/mjonir/aggs-TSLA-5m-2026-10-19.json` with `mjonir.yahoo_shape.chart_doc` (no request).
check.py's passing checks are filtered out of this listing (4.3 shows every one).

```text
$ entry.py check TSLA --offline <Yahoo fixture> --now "2026-10-19 10:15" --write
record: recorded TSLA 2026-10-19 10:15 in <scratch>/acc2/record/triggers.jsonl (id 98c293f0b87bda59), the plan from trader-exit defaults for the setup (or_mid stop, 2R target)
TSLA  Mon 2026-10-19 10:15 ET  opening-range breakout (15-minute range) on 5-minute bars (Yahoo, free, can lag)
Opening range 9:30-9:45: high $362.18, low $354.47 (3 of 3 bars).
TRIGGERED 10:15 AM at $364.18: the 10:10 bar (bar 8) closed above the range high $362.18 (+0.55%).
This is the moment to get in, if you take the trade. Nothing was placed.
Next: set the stop and target BEFORE you buy: /trader-exit (exit.py plan --from trader/entry.json).
Wrote trader/entry.json (status triggered).
(exit 0)

$ wc -l record/*
1 record/triggers.jsonl

$ exit.py plan --now "2026-10-19 10:16" --write   (trader-exit defaults: or-mid stop, 2R target)
Exit plan: TSLA long, Mon 2026-10-19, opening-range breakout on 5-minute bars
  Entry         $364.18 at 10:15 AM (bar 8)
  Stop          $358.32  opening-range midpoint: ($362.18 + $354.47) / 2 = $358.325, rounded down
  Target        $375.90  2R (two times the risk)
  Risk a share  $5.86 (1.61% of the entry)
  Reward:risk   2.0 gross, 1.37 net
  Costs: 1.5610 a share round trip = 0.266 R (15 bp slippage tier, ADV unverified; 3 bp half spread, the default, unverified; $1 commission a side over 8 shares).
  Flat by       15:55 ET, win or lose: no overnight hold
Set before the entry. If price hits the stop, you are out; never move it further away.
A stop is a plan, not a guarantee: a gap or a fast market can fill past it.
Wrote trader/plan.json.
Next: /trader-timemachine replays it, then /trader-budget sizes it to your max loss. Nothing was placed.
(exit 0)

$ size.py --now "2026-10-19 10:16" --write
TSLA buy, opening-range breakout, entry 364.18 at 10:15 AM
Stop 358.32: opening-range midpoint. Target 375.90: 2R (two times the risk).
Sized at 364.18 (the plan's entry). Risk 5.86 a share (entry 364.18 minus stop 358.32). Reward:risk 2.00 gross, 1.45 net.
Costs (the plan's cost card): 1.3110 a share round-trip slippage and spread (18 bp a side) plus $1 commission each way.

Limits (whole shares; the smallest one wins):
  notional      the $100,000 trade notional / 364.18                       274 shares
  max loss      ($1,000 - $2 commissions) / (5.86 risk + 1.3110 round trip) a share 139 shares  <- binds

Size: 139 shares of TSLA = $50,621.02 at 364.18, 50.62% of the $100,000 trade notional.
Risk $814.54 at the stop before costs (0.815% of the notional); max loss net of costs $998.78 (0.999% of the notional; the cap is $1,000, 1.000%).
Net max loss: 139 x (5.86 + 1.3110) + $2 = $998.78.
A stop is an order, not a promise: in a fast market it can fill below 358.32.

Proposed bracket order (place_stock_order arguments, nothing has been placed):
  buy 139 TSLA, market, day, take-profit 375.90, stop-loss 358.32
Flat by 15:55 New York: anything still open then gets closed (trader-alerts rings, trader-broker flatten).

Next: trader-risk checks it, then trader-broker asks you yes or no.
Education and tooling, not financial advice.
Wrote 1 proposed bracket order to trader/orders.json
(exit 0)

$ check.py --now "2026-10-19 10:16"   (no prices file, no portfolio)
BLOCK #1 buy TSLA 139 shares, entry
          entry 364.18 (the plan's entry), stop 358.32, target 375.90: risk 5.86 a share
          max loss $998.78 net of costs ($814.54 gross) (limit $1,000), reward:risk 1.45 net (2.00 gross) (min 1, net)
          today before this: 0 of 3 trades; the loss limits are percent of the $100,000 trade notional, realized from the forward record
        - spread: unverified, spread not measured live (missing): the 0.59 limit cannot be checked
        - unverified: adv floor: no ADV$ for TSLA (the plan's cost card has none; --source massive asks Massive): the $20,000,000 floor cannot be checked
        - unverified: chase: no fresh price for TSLA (no trader/prices.json price under 15 minutes old; --source massive asks the live ask) to hold against the trigger 364.18 (the limit is 366.00, 0.5% over)
        every check:
          spread              unverified spread not measured live (missing): the 0.59 limit cannot be checked
          adv_floor           unverified no ADV$ for TSLA (the plan's cost card has none; --source massive asks Massive): the $20,000,000 floor cannot be checked
          chase               unverified no fresh price for TSLA (no trader/prices.json price under 15 minutes old; --source massive asks the live ask) to hold against the trigger 364.18 (the limit is 366.00, 0.5% over)

0 passed, 1 blocked at 2026-10-19 10:16 New York. Cash after the passed orders: $100,000 (paper account).
Blocked orders do not go to the broker. Fix the order or your rules, then check again.
Education and tooling, not financial advice.
(exit 1)

$ ticket.py decline --index 1 --reply "no, skipping: acceptance run" --now "2026-10-19 10:17"
Recorded: you said no to order 1 (BUY 139 TSLA, market, good for today / stop-loss 358.32 / take-profit 375.90 / max loss about $998.78 if the stop fills at 358.32 (it can fill worse in a fast market)). Nothing was sent.
Record: recorded the decision (skipped: no, skipping: acceptance run) for TSLA 2026-10-19 10:15 in <scratch>/acc2/record/triggers.jsonl (id d38d551d4f5d29e9).
(exit 0)

$ wc -l record/*
2 record/triggers.jsonl

$ record.py score --date 2026-10-19 --offline <the Yahoo fixture> --now "2026-10-19 16:30"
TSLA 10:15 orb: unverified, not scored: 61 of the 77 bars through the flat-by bar 76 are not in the data yet (first missing: bar 16)
Appended 0 score line(s) and 0 control row(s); 1 trigger(s) not scored yet (run score again when the bars are in).
(exit 2)

$ record.py score --date 2026-10-19 --offline TSLA-full-day.json --now "2026-10-19 16:30"
TSLA 10:15 orb: close at 15:55 (exit 367.24), net +0.256 R (gross +0.522 R, costs 0.266 R).
  control 0: bar 40 (12:55) at 368.79, close, net -0.527 R.
Appended 2 score line(s) and 1 control row(s).
(exit 0)

$ sha256sum record/*
0d163abe14799066b5b78bdd21c7891069d1e57086475a970476f86ad2df7f24  record/scores.jsonl
42098cf1162dad939bcca87dbd2d5e759bd0f532e545d5824b65f8833cdc6671  record/triggers.jsonl

$ record.py score ... (again)
TSLA 10:15 orb: already scored (close, net +0.256 R); nothing appended.
Appended 0 score line(s) and 0 control row(s).
(exit 0)

$ sha256sum record/*
0d163abe14799066b5b78bdd21c7891069d1e57086475a970476f86ad2df7f24  record/scores.jsonl
42098cf1162dad939bcca87dbd2d5e759bd0f532e545d5824b65f8833cdc6671  record/triggers.jsonl
hashes unchanged: yes

$ record.py report --now "2026-10-19 16:40"
Forward record record/triggers.jsonl: 3 lines, 2 scores, as of 2026-10-19T20:30:00Z. Today 2026-10-19 (New York).
Triggers: 1 recorded; scored 0 target, 0 stop, 1 close; 0 no data; 0 not scored yet.
Decisions: 0 taken, 1 skipped, 0 undecided. Controls: 1 rows.
Paper, every scored trigger (taken or not): net average +0.256 R a trade (95% bootstrap [+0.256, +0.256], n 1).
  Gross +0.522 R a trade (95% bootstrap [+0.522, +0.522], n 1); costs 0.266 R a trade on average.
  Decided: none yet (every scored trigger exited at the flat-by close).
Random-entry control: 1 trades, net average -0.527 R a trade (95% bootstrap [-0.527, -0.527], n 1); delta +0.783 R a trade (95% bootstrap [+0.783, +0.783]) over 1 paired sessions.
Taken subset (beside the paper rows, never instead of them): no taken trade scored yet.
Days: 0 since the first trigger (2026-10-19); the gate needs 180.
Prices are the plan's as written (the cent order prices); the time machine's history enters at the unrounded bar close, so its targets can differ by a fraction of a cent. That is by design.

GATE NOT YET: n 1 of the 40 scored triggers; 0 of the 180 days since the first trigger (2026-10-19); 1 of the 40 paired control sessions.
Money only past the gate; the gate is not a forecast.
(exit 0)

$ record.py report (the real clock)

GATE NOT YET: n 1 of the 40 scored triggers; 15 of the 180 days since the first trigger (2026-10-19); 1 of the 40 paired control sessions.
Money only past the gate; the gate is not a forecast.

$ record.py journal --now "2026-10-19 16:40"
Journal, as of 2026-10-19 (New York). Taken trades are realized (the broker's fills where entered, else paper); skipped and undecided triggers are the rule's paper score.
taken     n 0
skipped   n 1, total +0.256 R, expectancy +0.256 R a trade (95% bootstrap [+0.256, +0.256], n 1); won 1 of 1 (100.0%, 95% Wilson [20.7%, 100.0%]); profit factor n/a (no losing trade); average winner +0.256 R, average loser n/a, largest loss n/a; MAE mean -0.201 R, MFE mean +0.922 R
undecided n 0

By setup:
  orb
    skipped   n 1, total +0.256 R, expectancy +0.256 R a trade (95% bootstrap [+0.256, +0.256], n 1); won 1 of 1 (100.0%, 95% Wilson [20.7%, 100.0%]); profit factor n/a (no losing trade); average winner +0.256 R, average loser n/a, largest loss n/a; MAE mean -0.201 R, MFE mean +0.922 R

By month:
  2026-10
    skipped   n 1, total +0.256 R, expectancy +0.256 R a trade (95% bootstrap [+0.256, +0.256], n 1); won 1 of 1 (100.0%, 95% Wilson [20.7%, 100.0%]); profit factor n/a (no losing trade); average winner +0.256 R, average loser n/a, largest loss n/a; MAE mean -0.201 R, MFE mean +0.922 R

Money only past the gate; the gate is not a forecast.
(exit 0)
```

### 4.3 size.py and check.py on the TSLA reel under the example config

The plan is chunk 2's acceptance plan (`exit.py plan --source massive --target 2R`): its cost card holds the Massive
ADV ($12,729,948,354: the 4 bp tier) and the 3 bp default half spread. The plan's own estimate was "about 170 shares
at a 1 % cap": that is the gross count, floor(1,000 / 5.86) = 170. Net of the 0.5099 a share round trip and the $2 of
commissions the formula gives floor(998 / 6.3699) = 156, and 156 x (5.86 + 0.5099) + 2 = $995.70 stays under the $1,000
cap, so no share is taken off. The record from 4.2 is the record (today's trigger, skipped; its `record_as_of`
is 4.2's 16:30 score, written before this 10:16 replay).

```text
$ the plan: chunk 2 acceptance plan-2r.json (exit.py --source massive --target 2R): entry, stop, target, card
364.18 358.32 375.9 per_side_bps 7.0 adv_usd 12729948354 card shares 8 commission 1.0

$ size.py --plan plan-2r.json --config <config.example.json> --portfolio none --now "2026-10-19 10:16" --write orders.json
TSLA buy, opening-range breakout, entry 364.18 at 10:15 AM
Stop 358.32: opening-range midpoint. Target 375.90: 2R (two times the risk).
Sized at 364.18 (the plan's entry). Risk 5.86 a share (entry 364.18 minus stop 358.32). Reward:risk 2.00 gross, 1.75 net.
Costs (the plan's cost card): 0.5099 a share round-trip slippage and spread (7 bp a side) plus $1 commission each way.

Limits (whole shares; the smallest one wins):
  notional      the $100,000 trade notional / 364.18                       274 shares
  max loss      ($1,000 - $2 commissions) / (5.86 risk + 0.5099 round trip) a share 156 shares  <- binds

Size: 156 shares of TSLA = $56,812.08 at 364.18, 56.81% of the $100,000 trade notional.
Risk $914.16 at the stop before costs (0.914% of the notional); max loss net of costs $995.70 (0.996% of the notional; the cap is $1,000, 1.000%).
Net max loss: 156 x (5.86 + 0.5099) + $2 = $995.70.
A stop is an order, not a promise: in a fast market it can fill below 358.32.

Proposed bracket order (place_stock_order arguments, nothing has been placed):
  buy 156 TSLA, market, day, take-profit 375.90, stop-loss 358.32
Flat by 15:55 New York: anything still open then gets closed (trader-alerts rings, trader-broker flatten).

Next: trader-risk checks it, then trader-broker asks you yes or no.
Education and tooling, not financial advice.
Wrote 1 proposed bracket order to orders.json
(exit 0)

$ size.py ... --json | the sizing block
{"qty": 156, "bound_by": "max loss", "cost": 56812.08, "max_loss": 995.7, "max_loss_gross": 914.16, "reward_risk_net": 1.75}
{"trade_notional_usd": 100000.0, "notional_usd": 56812.08, "notional_pct": 56.81, "risk_usd": 914.16, "risk_pct": 0.914, "max_loss_usd": 995.7, "max_loss_pct": 0.996, "cap_usd": 1000.0, "cap_pct": 1.0}

$ check.py --orders orders.json --config <config.example.json> --portfolio none --prices none --state none --now "2026-10-19 10:16" --out risk.json   (record: the item 2 record)
BLOCK #1 buy TSLA 156 shares, entry
          entry 364.18 (the plan's entry), stop 358.32, target 375.90: risk 5.86 a share
          max loss $995.70 net of costs ($914.16 gross) (limit $1,000), reward:risk 1.75 net (2.00 gross) (min 1, net)
          today before this: 0 of 3 trades; the loss limits are percent of the $100,000 trade notional, realized from the forward record
        - spread: unverified, spread not measured live (missing): the 0.59 limit cannot be checked
        - unverified: chase: no fresh price for TSLA (no trader/prices.json price under 15 minutes old; --source massive asks the live ask) to hold against the trigger 364.18 (the limit is 366.00, 0.5% over)
        every check:
          spread              unverified spread not measured live (missing): the 0.59 limit cannot be checked
          price_floor         pass       TSLA at 364.18, the floor is $5
          adv_floor           pass       TSLA ADV$ $12,729,948,354 (the plan's cost card), the floor is $20,000,000
          chase               unverified no fresh price for TSLA (no trader/prices.json price under 15 minutes old; --source massive asks the live ask) to hold against the trigger 364.18 (the limit is 366.00, 0.5% over)
          averaging_down      pass       no TSLA position on record (no trader/portfolio.json)
          daily_loss          pass       realized $0 net over 0 scored trade(s) since 2026-10-19, $0 planned on 0 open trade(s), $0 passed earlier in this batch, plus $995.70 for this one = $995.70; the limit is $1,000 (1% of the notional)
          weekly_loss         pass       realized $0 net over 0 scored trade(s) since 2026-10-19, $0 planned on 0 open trade(s), $0 passed earlier in this batch, plus $995.70 for this one = $995.70; the limit is $2,000 (2% of the notional)
          loss_streak         pass       no 3 taken trades in a row lost
          format              pass       not blocked
          asset               pass       not blocked
          short               pass       not blocked
          price               pass       not blocked
          blocked             pass       not blocked
          size                pass       not blocked
          cash                pass       not blocked
          position            pass       not blocked
          stop                pass       not blocked
          loss                pass       not blocked
          reward_risk         pass       not blocked
          trades              pass       not blocked
          window              pass       not blocked
          pdt                 pass       off (pdt_guard is false)
          duplicate           pass       not blocked
          daily_limit         pass       not blocked

0 passed, 1 blocked at 2026-10-19 10:16 New York. Cash after the passed orders: $100,000 (paper account).
Blocked orders do not go to the broker. Fix the order or your rules, then check again.
Education and tooling, not financial advice.
(exit 1)

$ the same with a fresh trader/prices.json (TSLA 364.18 at 10:16)
BLOCK #1 buy TSLA 156 shares, entry
          entry 364.18 (the plan's entry), stop 358.32, target 375.90: risk 5.86 a share
          max loss $995.70 net of costs ($914.16 gross) (limit $1,000), reward:risk 1.75 net (2.00 gross) (min 1, net)
          today before this: 0 of 3 trades; the loss limits are percent of the $100,000 trade notional, realized from the forward record
        - spread: unverified, spread not measured live (missing): the 0.59 limit cannot be checked
        every check:
          spread              unverified spread not measured live (missing): the 0.59 limit cannot be checked
          price_floor         pass       TSLA at 364.18, the floor is $5
          adv_floor           pass       TSLA ADV$ $12,729,948,354 (the plan's cost card), the floor is $20,000,000
          chase               pass       TSLA at 364.18 (a fresh price in trader/prices.json), the trigger 364.18, the limit 366.00
(exit 1)

$ risk.json basis
fingerprint 75ff382d895304d7
{"trade_notional_usd": 100000.0, "record_as_of": "2026-10-19T20:30:00Z", "limits": {"mode": "notional", "max_loss_usd": 1000.0, "daily_loss_usd": 1000.0, "weekly_loss_usd": 2000.0, "max_trades_per_day": 3, "max_consecutive_losses": 3, "pause_sessions_after_streak": 1, "max_order_usd": 100000.0, "floors": {"min_price": 5.0, "min_adv_usd": 20000000.0, "max_chase_pct": 0.5, "no_averaging_down": true}, "warnings": []}}

$ the offline default plan (ADV unverified, 18 bp a side) for comparison: see item 2, 139 shares
```

The order BLOCKS under the example config, for unverified checks only: `block_on_unverified` is true and on a past
day there is no live NBBO (the spread) and, without a prices file, no fresh price (the chase). With a fresh price the
chase passes and only the spread is left. Live, `check.py --source massive` asks the NBBO for both.

### 4.4 Live: the same day on 2026-10-30 from Massive (paced, read-only, through mjonir)

A separate scratch folder (its own `trader/data` cache and record). `entry.py check --source massive` built the
default plan with exit.py's Massive ADV card; `record.py score --source massive` read the session through
trader-entry's reader (`chart_text`, a past day, not live). A handful of requests (the session's 5-minute bars, the
daily bars for the ADV, the split list); no 403, nothing outside the scratch folder written.

```text
$ entry.py check TSLA --source massive --now "2026-10-30 10:30" --write
record: recorded TSLA 2026-10-30 09:55 in record/triggers.jsonl (id 16f42531d76000ee), the plan from trader-exit defaults for the setup (or_mid stop, 2R target)
TSLA  Fri 2026-10-30 10:30 ET  opening-range breakout (15-minute range) on 5-minute bars (Massive)
Opening range 9:30-9:45: high $393.46, low $387.52 (3 of 3 bars).
TRIGGERED 9:55 AM at $394.12: the 9:50 bar (bar 4) closed above the range high $393.46 (+0.17%).
That was 35 minutes ago; the last close is $398.26 (10:25 bar). A late entry is a different trade: the price, the stop distance and the odds have moved.
Nothing was placed.
Next: set the stop and target BEFORE you buy: /trader-exit (exit.py plan --from trader/entry.json).
Wrote trader/entry.json (status triggered).
(exit 0)

$ the recorded trigger row: trigger, plan, costs
{
 "id": "16f42531d76000ee",
 "trigger": {
  "bar_index": 4,
  "level": 393.46,
  "or_high": 393.46,
  "or_low": 387.52,
  "price": 394.12,
  "rvol": null,
  "time": "09:55",
  "volume_x": 0.41
 },
 "plan": {
  "entry": 394.12,
  "stop": 390.49,
  "target": 401.38,
  "risk_per_share": 3.63,
  "risk_pct": 0.921,
  "target_r": 2.0,
  "flat_by": "15:55",
  "basis": "trader-exit defaults for the setup (or_mid stop, 2R target)"
 },
 "costs": {
  "adv_usd": 14012407191,
  "adv_note": "Massive: mean close x volume over the 20 sessions before 2026-10-30",
  "slippage_bps": 4.0,
  "half_spread_bps": 3.0,
  "per_side_bps": 7.0,
  "shares": 13,
  "cost_r": 0.194384
 },
 "source": {
  "as_of": "2026-10-30T14:30:00Z",
  "bars": "massive"
 }
}

$ record.py score --date 2026-10-30 --source massive --now "2026-10-30 16:30"
TSLA 09:55 orb: target at 10:45 (exit 401.38), net +1.806 R (gross +2.000 R, costs 0.194 R).
  control 0: bar 38 (12:45) at 400.82, stop, net -1.194 R.
Appended 2 score line(s) and 1 control row(s).
(exit 0)

$ record.py score ... again
TSLA 09:55 orb: already scored (target, net +1.806 R); nothing appended.
Appended 0 score line(s) and 0 control row(s).
(exit 0)
hashes unchanged: yes

$ the score lines
{'kind': 'trigger', 'outcome': 'target', 'entry_bar': 4, 'exit_bar': 14, 'exit_time': '10:45', 'exit_price': 401.38, 'gross_r': 2.0, 'net_r': 1.805616, 'cost_r': 0.194384, 'mfe_r': 2.30854, 'mae_r': -0.18719, 'last_bar': 76, 'fill_basis': 'paper', 'source': {'bars': 'massive', 'data': 'massive', 'early_close': False}}
{'kind': 'control', 'outcome': 'stop', 'entry_bar': 38, 'exit_bar': 52, 'exit_time': '13:55', 'exit_price': 397.12829, 'gross_r': -1.0, 'net_r': -1.193676, 'cost_r': 0.193676, 'mfe_r': 0.008804, 'mae_r': -1.21353, 'last_bar': 76, 'fill_basis': 'paper', 'source': {'bars': 'massive', 'data': 'massive', 'early_close': False}}

$ record.py report --now "2026-10-30 16:40" | tail -3

GATE NOT YET: n 1 of the 40 scored triggers; 0 of the 180 days since the first trigger (2026-10-30); 1 of the 40 paired control sessions.
Money only past the gate; the gate is not a forecast.
```

## 5. How the brief is met

- **Location and hermeticity.** `${TRADER_RECORD_DIR:-record}`, cwd-relative (`mjonir/ledger.py record_dir`).
  `tests/_load.py` points it at a throwaway folder; `tests/test_zz_record_untouched.py` (discovered last) proves the
  repo's `record/` is byte for byte what it was; `record/` stays tracked with `.gitkeep` only.
- **Append-only.** `mjonir/ledger.py` is the only module that opens the two files: `read_rows` with mode `"r"` and
  `append_rows` with mode `"a"`. A test parses `ledger.py` and `record.py` and asserts the open modes are exactly
  `{"a", "r"}` with the one `"a"` in the ledger, no `os.replace`, `rename`, `truncate`, `shutil` or write mode, and that
  no other script names `triggers.jsonl` or `scores.jsonl` outside a docstring. A line that is not a JSON object with an
  id, or a last line with no newline (a cut write), raises `RecordError` naming the file and the line; nothing
  rewrites it.
- **Scoring consistency.** `score` scores the plan as written (cent prices) through `outcomes.score_trade` from the
  trigger bar's close, the bars after it, to the plan's flat-by bar (`last_bar` mirrors trader-exit's
  `resolve_flat_by` and the time machine's `early_last`), fill at that bar's close, gap fill at the open, one cost_r
  from `costs.trade_cost_r(entry, risk, costs.model_of(card))`. The card is the plan's, or, for a plan without one,
  the time machine's own default card (tested equal to `timemachine.cost_card_for`). Tested equal to
  `timemachine.history_replay` on 13 synthetic sessions and an early close (outcome, gross and net R, last bar, cost).
  The report says the cent prices differ from the time machine's sub-cent history targets by design (note 11).
- **Control rows.** One a scored trigger (`--control-draws`, default 1) through `control.draw_controls(...,
  entry_until=<the plan's no-entries-after bar>)`: 15:30 is bar 71, an early close's 12:30 bar 35 (note 12); seed
  `19:symbol:date`; written as `kind: control` with `paired_id`, then scored once. The tests assert the drawn bar is
  `session_rng(19, symbol, date).choice(eligible_bars(n_or, last, 71))`.
- **The gate.** `expectancy_ci` over the net R of every scored paper trigger (target, stop or close; taken or not)
  and `paired_delta_ci` keyed by trigger; floors on those n's (`stats.N_FLOOR`); days from the first trigger's date to
  today in New York. PASSES / FAILS / NOT YET exactly as briefed (`gate_of`, tested at (39, 200), (40, 179), (40, 180,
  lo > 0), hi < 0, a delta below its floor, straddles); the taken subset is printed beside the paper rows; every
  report ends with the footer; no gate text has a banned word.
- **Hooks.** `entry.py check` and `watch`: `--record` (default on), `--no-record`, `--plan`, `--record-dir`; the
  note goes to stderr so stdout (and `--json`) is unchanged; a failure prints "NOT RECORDED" and never stops the
  timer. `ticket.py approve` writes the decision taken (risk and broker fingerprints, the risk verdict, the shares,
  the planned net max loss, the order class); `decline` writes it skipped with the reply as the reason. ticket.py
  already had a hand-entered fill path (`ticket.py fill --symbol --side --qty --price`), so no new fill command was
  added; `score` reads those fills for `fill_basis` broker.
- **Journal.** Python computes realized R, expectancy with its interval, the win rate with Wilson, the profit factor
  (n/a with no loser), average winner and loser, the largest loss, MAE and MFE means, by setup and by month, taken
  beside skipped (and undecided). The SKILL.md narrates the JSON keys only.
- **3.2.** `derive_limits(cfg)` lives in `mjonir/limits.py`, imported by size.py and check.py. size.py's formula is
  the brief's, with the decrement guard (a 300-plan property test). check.py: every new check is `{name, state,
  reason}`; BLOCK on any block, or on any unverified with `block_on_unverified`; risk.json keeps the fingerprint and
  adds `basis {trade_notional_usd, limits, record_as_of}`. Code defaults without a `sizing` block are chunk 2's.

## 6. Decisions, deviations, owed and uncertain

- **OWED (outside this chunk's paths): the cost card's share basis.** trader-exit and the time machine spread the
  commission over floor(max_loss_per_trade_usd / risk) shares, falling back to upstream's $50 when the key is absent or
  null. Under the percent config that is 8 TSLA shares, so the plan card (and with it the time machine's history and
  the record's score) charges $2 / 8 a share: cost_r 0.130 at the 4 bp tier, where the 156 shares the order really
  has would be 0.089 (and 0.266 against 0.226 at the 18 bp tier of an ADV-unverified plan). The record matches the
  time machine, as briefed, so both overstate the commission until `exit.py build_plan` and
  `timemachine.cost_card_for` read `derive_limits(cfg)["max_loss_usd"]` (two lines each). Not touched: trader-exit/
  and trader-timemachine/ are outside this chunk's paths.
- **A third row kind, `decision`.** The trigger is appended when the entry timer sees it, before anyone decides; the
  file is append-only, so ticket.py's yes or no is appended as `kind: decision` with `paired_id` = the trigger, and
  the last decision row wins (an inline decision is written when `add` gets one with a new trigger). A repeated
  identical decision appends nothing. The decision attaches by (symbol, day, setup, trigger time) to the trigger row
  whose plan matches the order's stop and target (else the first); `plan_matches_record` says which.
- **The trigger's plan at trigger time.** The entry timer has no plan yet, so `--record` builds trader-exit's own
  plan for the setup in-process (`exit.build_plan` with its defaults: or-mid stop, 2R target, the config's flat-by
  and minimum reward:risk, the cost card) unless `--plan` names a plan. A level setup has no default stop: the
  trigger is recorded with no plan and scored `no_data` ("no plan"). A plan trader-exit refuses (net reward:risk
  under the minimum) is recorded the same way: the rule did not trade it.
- **The rule hash.** sha256 over setup, interval, opening-range minutes, min volume, stop rule and parameter, target
  R and exit; the flat-by and the entry window are recorded beside it, not hashed (an early close moves them).
- **The time machine's `last`.** It ends at `--until` (default the 16:00 close), not at the plan's flat-by; the record
  uses the plan's flat-by as briefed. They agree with `timemachine.py run --until <flat_by>` (tested that way).
- **Realized losses.** daily and weekly: max(0, minus the realized net dollars of the taken, scored trades in the
  window) plus the planned net max loss of the taken ones not scored yet, plus the orders passed earlier in the batch,
  plus this one. A gain offsets a loss but never makes room past zero. Net dollars come from the broker's fills when
  the score has them, else paper net R x shares x risk a share. A record that does not exist yet, or cannot be read,
  makes all three record checks unverified, so under `block_on_unverified` check.py blocks until entry.py has written
  the day's trigger (the routine's order).
- **The streak.** The last N taken, scored trades all net below zero; blocked on the day of the last one and for the
  next `pause_sessions_after_streak` sessions, counted with check.py's own market calendar (tested over a weekend and
  over Thanksgiving).
- **Fills.** Matched by day and symbol, with the approval's fingerprint present in the broker log; both legs and a
  flat position are needed, and two taken trades in one name on one day are not told apart (paper, with a note).
  Fills entered after the 16:30 score stay out: a score line is written once (RUNBOOK says so).
- **averaging_down with no portfolio file** passes ("no position on record"), as check.py already treats a missing
  portfolio as a fresh account. A stricter reading would call it unverified; not done, named here.
- **Upstream's checks in percent mode** get derived states from their block reasons (pass "not blocked" or block);
  the planned daily loss gives way to the realized one; `pdt` reads "off" when `pdt_guard` is false. Legacy configs
  print exactly what chunk 2 printed (the "every check" listing appears only in percent mode).
- **The example config** keeps `"broker": "alpaca"` and the Alpaca order fields: chunk 4 turns the ticket into a
  human E*TRADE ticket. Its `block_on_unverified` true means a replay without a live quote blocks (4.3).
- **A percent config without a budget** starts ticket.py's paper portfolio at one trade notional.
- **The order's plan now carries the cost card's `adv_usd`** (size.py), so check.py's ADV floor can read it.
- **Clock.** record.py uses the trader scripts' New York rule through trader-entry (no zoneinfo, Python 3.8); a test
  asserts it equals `mjonir.calendar.today_et` across both DST changes.
- **The hermetic proof** relies on unittest discovering files in sorted order, so `test_zz_record_untouched.py` runs
  last in a full run; run alone it compares a snapshot taken a moment earlier.
- **Not done here:** 3.3 to 3.5 (the RVOL prereg, scanner, study); the desk (chunk 4). No Kalex store was opened; the
  two live sessions in `~/Odyssey`, `~/Kalex` and `~/Infinit` were not touched (the key was read from `~/Infinit/.env`
  by mjonir for 4.4 only, never printed).

## 7. Review fixes (3a review: HOLD on two MUSTs, then APPROVE WITH SHOULDs)

Two commits on `feat/c3-record`: `e25464f` (M1, M2: 576 OK, 13.6 s) and the commit that adds this section (the
SHOULDs, the NITs, the docs: 589 OK, about 14.4 s). The lead authorised edits to `trader-exit/exit.py` (M2) and
`trader-timemachine/timemachine.py` (M2, S3) for this round only. Section 6's owed share-basis item is M2, done here;
sections 4 and 6 keep the numbers as first printed (the 8-share card).

| item | change | pinned by |
| --- | --- | --- |
| M1 decision ids | `ledger.decision_id(trigger, taken, reason, fingerprint, at, seq)`: the record time and the decision's place among the trigger's decisions; `append_decision` drops the `did in ids` clause and keeps `same` (a decision equal to the current one appends nothing) | `test_record.Decisions.test_no_then_yes_then_no_ends_skipped` (three rows in one second, distinct ids, ends `taken: False`; a re-sent no leaves the hash unchanged) |
| M2 share basis | `costs.max_loss_basis(cfg)`: a percent config's `derive_limits(cfg)["max_loss_usd"]`, else `max_loss_per_trade_usd`, else $50; called by `exit.py build_plan`, `timemachine.cost_card_for`, `record.card_for`; exit's `read_config` carries `sizing` / `limits_pct` and gives a percent config no $50 default. The reel's card under the example config: 170 shares, cost_r 0.089013, 2R net reward:risk 1.7548 (was 8, 0.1297, 1.66) | `test_limits.ShareBasis` (the basis in every case; exit's 170-share card; the three cards agree on the percent config and give 8 on the legacy one); the SIM_* pin re-run (held) |
| S1 ids and lock | `ledger.load` raises naming both lines when any id in triggers.jsonl repeats; `ledger.locked(d)` holds an `fcntl.flock` on triggers.jsonl (opened to append) around load and append in `record_trigger`, `decide` and `score_day` | `ReviewFixes.test_an_id_written_twice_names_both_lines`, `test_the_lock_excludes_a_second_writer` (a non-blocking flock fails while held), `test_two_writers_at_once_append_one_trigger` (four threads, one row) |
| S2 chase reference | size.py writes `entry_plan` (the trigger) into the order's plan when it sized at another price; check.py measures the chase from `entry_plan`, else `entry`; an order sized at the trigger is unchanged (upstream's bracket pins hold) | `test_limits.Checks.test_the_chase_is_measured_from_the_trigger` (sized at 366.00, fresh 367.00: BLOCK against the 364.18 trigger) |
| S3 windows | timemachine: `--no-entries-after HH:MM` (default the config's no_entries_after, else 15:30; early close moved up three hours, `entry_window_bar` = record's `entry_until`) caps the rule's fire bars and the control's entry bars; the function default stays None (upstream); the history carries `entry_window` and the report prints it; a `--until` later than the plan's flat-by prints a notice on stderr (not in `warnings`, which upstream pins empty); RUNBOOK's command gets `--until 15:55`; the 16:00 default stays | `Windows.test_the_window_bar_is_the_records`, `test_a_fire_after_the_window_is_not_a_trade`, `test_the_cli_default_and_the_until_notice`; `SimPin` now passes `--no-entries-after 16:00` (the session's last bar) and is bit for bit |
| S4 default source | `record.py score` defaults to yahoo (or TRADER_SOURCE), like every script | `ReviewFixes.test_score_reads_yahoo_by_default` |
| S5 a finished day | once the session is over (a later New York day, or 30 minutes past the close) a trigger whose bars are missing is scored `no_data` ("bars missing: first missing bar i ..."); while live it stays pending; a source that could not answer stays pending | `ReviewFixes.test_bars_missing_after_the_session_are_no_data` (16:20 pending, 16:30 no_data, a later run appends nothing) |
| S6 empty record | a record folder with no triggers file is an empty record: daily, weekly and streak pass ("no trigger recorded yet in <dir>"); no folder stays unverified | `test_limits.Checks.test_daily_loss_unverified_without_a_record` (both) |
| S7 averaging down | a taken trade in the symbol today in the record and no portfolio file: unverified ("a taken SYM trade today in the record; no portfolio to compare the cost basis") | `Checks.test_averaging_down_with_a_taken_trade_today_and_no_portfolio` |
| S8 exit guard | `tests/_load.py` registers an atexit guard: the repo's `record/` recomputed, on a change "TESTS WROTE record/" and `os._exit(3)` (checked by hand: a probe file gives exit 3); `test_record.Base.tearDown` and `test_limits.Checks.tearDown` assert the snapshot; `test_zz` kept | the guard itself; the two tearDowns |
| S9 one rule per gate | more than one rule hash in the selection: GATE NOT YET "N rules in the record; the gate reads one: use --setup or --rule", each rule's own gate printed beneath (`gate.per_rule`); `--rule HASH` on report and journal | `ReviewFixes.test_one_rule_per_gate` (a 2R default and a 1R plan on one trigger) |
| S10 late fills | RUNBOOK: fills typed after the 16:30 score do not reach the record yet; a `fill` row kind is chunk 4's; never edit a score line by hand | docs |
| NIT line buffering | `append_rows` opens with `buffering=1`: one write a row | |
| NIT unknown keys | `limits.unknown_keys`: an unknown `sizing` / `limits_pct` / `floors` key is a warning in `derive_limits` and on stderr | `Derive.test_unknown_keys_are_warned` |
| NIT test env | `test_record.Base.tearDown` pops `TRADER_RECORD_DIR` when it was unset | |
| NIT load_config | size.py applies DEFAULTS to a percent config too, except the legacy dollar keys (`limits.LEGACY_KEYS`), which come only from the file | `Derive.test_size_loads_defaults_but_no_legacy_dollar_key` |

**Assertions edited in this round** (no upstream assertion):

| test | old | new | reason |
| --- | --- | --- | --- |
| test_mjonir_stats `Verdicts.test_the_two_year_reading` (chunk 2's) | the README quotes the chunk 2 "Below zero: 285 fires, -0.125 ..." text verbatim | the chunk 2 text is still recomputed and asserted; the README must now quote the text recomputed from this round's percent-config run (281 fires, -0.08823, [-0.19327, +0.02325], cost 0.1418: unverified/straddles) | the lead asked the README to carry the new reading |
| test_timemachine_measure `SimPin` (chunk 2's) | argv without a window | adds `--no-entries-after 16:00` (upstream: no cap) | S3: the CLI default is now 15:30; the hashes are bit for bit with 16:00 (they also held at 15:30 on this fixture) |
| test_record `AppendOnly.test_open_modes` (this chunk's) | one `"a"` open, in ledger.py | `"a"` opens only in ledger.py (append and lock) | S1's lock |
| test_limits `test_daily_loss_unverified_without_a_record` (this chunk's) | "no record at" | "no record folder at", plus the empty-folder pass | S6 |

**The two-year TSLA reading under the example (percent) config**, live (paced, read-only; 10 aggregate pages and the
daily bars for the ADV, cold; the second plan from the cache), `timemachine.py run --plan <plan> --source massive
--years 2 --control-draws 3 --until 15:55 --now "2026-10-19 10:15" --json --config <the example>`; the 1R plan is the
reel's plan file, the 2R plan the same with target 375.90. First at `e25464f` (M2 alone: no entry window), then with
this round's code (S3: the config's 15:30 window):

```text
== m2-1r
card: shares 170 (floor(1000.00 max loss / 5.86 risk) = 170 shares), cost_r 0.0890, per_side_bps 7.0, ADV 12729948354
until 15:55 | triggered 284: target 128, stop 116, close 40 | cost_r_mean 0.1417
net -0.082 [-0.193, +0.029] n 284 | gross +0.060 [-0.051, +0.171]
control delta -0.050 [-0.165, +0.064] over 284 sessions (rule -0.082, control -0.032)
verdict_history unverified/straddles: Edge not distinguishable from zero: 284 fires, net average -0.082 R a trade (95% bootstrap [-0.193, +0.029]); the interval includes 0. Decided: 128 of 244 hit the target (52.5%, 95% Wilson [46.2%, 58.6%]) against a net break-even of 57.1% at 1R after costs (the history's own mean round trip, 0.142 R).
verdict_control unverified/straddles: Not distinguishable from the random-entry control: net delta -0.050 R a trade (95% bootstrap [-0.165, +0.064]) over 284 paired sessions; the interval includes 0.
== m2-2r
card: shares 170 (floor(1000.00 max loss / 5.86 risk) = 170 shares), cost_r 0.0890, per_side_bps 7.0, ADV 12729948354
until 15:55 | triggered 284: target 59, stop 131, close 94 | cost_r_mean 0.1417
net -0.048 [-0.188, +0.097] n 284 | gross +0.093 [-0.044, +0.235]
control delta -0.065 [-0.208, +0.081] over 284 sessions (rule -0.048, control +0.017)
verdict_history unverified/straddles: Edge not distinguishable from zero: 284 fires, net average -0.048 R a trade (95% bootstrap [-0.188, +0.097]); the interval includes 0. Decided: 59 of 190 hit the target (31.1%, 95% Wilson [24.9%, 38.0%]) against a net break-even of 38.1% at 2R after costs (the history's own mean round trip, 0.142 R).
verdict_control unverified/straddles: Not distinguishable from the random-entry control: net delta -0.065 R a trade (95% bootstrap [-0.208, +0.081]) over 284 paired sessions; the interval includes 0.
== s3-1r
card: shares 170 (floor(1000.00 max loss / 5.86 risk) = 170 shares), cost_r 0.0890, per_side_bps 7.0, ADV 12729948354
until 15:55 | triggered 281: target 127, stop 116, close 38 | cost_r_mean 0.1418
net -0.088 [-0.193, +0.023] n 281 | gross +0.054 [-0.052, +0.166]
control delta -0.061 [-0.172, +0.056] over 281 sessions (rule -0.088, control -0.027)
verdict_history unverified/straddles: Edge not distinguishable from zero: 281 fires, net average -0.088 R a trade (95% bootstrap [-0.193, +0.023]); the interval includes 0. Decided: 127 of 243 hit the target (52.3%, 95% Wilson [46.0%, 58.5%]) against a net break-even of 57.1% at 1R after costs (the history's own mean round trip, 0.142 R).
verdict_control unverified/straddles: Not distinguishable from the random-entry control: net delta -0.061 R a trade (95% bootstrap [-0.172, +0.056]) over 281 paired sessions; the interval includes 0.
== s3-2r
card: shares 170 (floor(1000.00 max loss / 5.86 risk) = 170 shares), cost_r 0.0890, per_side_bps 7.0, ADV 12729948354
until 15:55 | triggered 281: target 59, stop 131, close 91 | cost_r_mean 0.1418
net -0.054 [-0.188, +0.092] n 281 | gross +0.088 [-0.046, +0.232]
control delta -0.074 [-0.215, +0.078] over 281 sessions (rule -0.054, control +0.020)
verdict_history unverified/straddles: Edge not distinguishable from zero: 281 fires, net average -0.054 R a trade (95% bootstrap [-0.188, +0.092]); the interval includes 0. Decided: 59 of 190 hit the target (31.1%, 95% Wilson [24.9%, 38.0%]) against a net break-even of 38.1% at 2R after costs (the history's own mean round trip, 0.142 R).
verdict_control unverified/straddles: Not distinguishable from the random-entry control: net delta -0.074 R a trade (95% bootstrap [-0.215, +0.078]) over 281 paired sessions; the interval includes 0.
```

With this round's code the 1R reading is unverified/straddles, as is the 2R one, and both control verdicts are
unverified/straddles. For comparison, chunk 2's two-year 1R run (the $50 share basis, so 8 shares; the 16:00 last bar;
no window) read fail/below: 285 fires, -0.125 [-0.235, -0.016], mean round trip 0.181 R. The README quotes the final
texts. The SIM_* pin held bit for bit after M2 and after S3 (`SimPin`, `Reel.test_bit_for_bit_with_the_reel_sim` and
`Reel.test_the_history_replay` pass).
