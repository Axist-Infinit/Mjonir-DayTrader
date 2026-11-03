---
name: trader-record
description: >-
  Forward Record. Keeps the append-only paper record of every opening-range
  trigger the entry timer sees, taken or skipped, scores each one once after
  the close from that session's 5-minute bars net of costs (the same way the
  time machine scores its history), pairs it with a random-entry control,
  and prints the money gate with its three outcomes: PASSES, FAILS or NOT
  YET. The journal sets the taken trades (from the hand-entered fills) beside
  the skipped ones. Use when the user asks about "the record", "the gate",
  "score today's triggers", "how many trades so far", "is it time to trade
  money", "show my journal", or at the 16:30 close routine.
argument-hint: "[report | journal | score --date D]"
---

# trader-record

The forward record is the paper account that decides whether this pack ever
trades money. Every trigger the entry timer sees lands in it once, whether
the owner takes it or skips it. After the close each trigger is scored once,
from the bars strictly after its trigger bar, and a random-entry control is
drawn on the same session. The report reads the record and prints the money
gate. A past record is not a forecast, and the gate is not one either.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).
Run every command from the repo root: the record lives in `record/` under the
current directory (or wherever `TRADER_RECORD_DIR` points).

```bash
python3 "${CLAUDE_SKILL_DIR}/record.py" score --date 2026-10-19 --source massive   # after the close
python3 "${CLAUDE_SKILL_DIR}/record.py" report                    # counts, intervals, control, gate
python3 "${CLAUDE_SKILL_DIR}/record.py" report --setup orb --since 2026-11-01 --json
python3 "${CLAUDE_SKILL_DIR}/record.py" journal --json            # taken beside skipped
python3 "${CLAUDE_SKILL_DIR}/record.py" add --from trader/entry.json --plan trader/plan.json --skipped "late"
```

`--now "2026-10-19 16:30"` pins the clock (New York time). `--offline PATH`
scores from a saved chart file or a folder of `<SYM>.json` instead of asking
a data source.

## What it reads and writes

| file | who writes it | what it holds |
| --- | --- | --- |
| `record/triggers.jsonl` | `entry.py check` and `watch` (on by default, `--no-record` off), `ticket.py approve` and `decline`, `record.py add` and `score` | one trigger row per trigger, one control row per scored trigger, one decision row per later yes or no |
| `record/scores.jsonl` | `record.py score` | one score line per trigger or control id, written once |
| `trader/state/broker.json` | `ticket.py fill` | the hand-entered fills `score` reads for a taken trade |

Both record files are tracked in git and append-only: they are opened with
mode `a` and never rewritten. A line that is not valid JSON stops every
command with the file and the line number; a person fixes it by hand.

## How a trigger is scored

- The plan is the one recorded with the trigger: the plan file when one was
  given, else trader-exit's own defaults for the setup (an opening-range
  breakout: the opening-range midpoint stop and a 2R target).
- From the trigger bar's close, through the bars after it, to the plan's
  flat-by bar (moved up three hours on an early close): the stop is checked
  first in every bar, a bar opening through the stop fills at its open, and
  a trade still open at the flat-by bar goes out at that bar's close.
- One round trip is charged once, from the plan's cost card.
- These are the time machine's own rules (mjonir/outcomes.py). Prices are the
  plan's cent order prices; the time machine's history enters at the
  unrounded bar close, so a history target can sit a fraction of a cent away.
- A taken trade with both fills entered also gets its realized result from the
  broker log (`fill_basis` broker). The paper score stays the rule's score.
- Bars not all in yet: nothing is written, the trigger is listed as
  unverified, and `score` can be run again.

## The money gate (three outcomes, never two)

The report reads the same statistics as the time machine's verdict: the net
expectancy interval over every scored paper trigger, taken or not, and the
delta against the random-entry control over the paired sessions.

- **PASSES** when at least 40 triggers are scored, at least 180 days have
  passed since the first trigger, the net expectancy interval sits wholly
  above zero, and the control delta interval sits wholly above zero over at
  least 40 paired sessions.
- **FAILS** when the count and the days are met and the net expectancy
  interval sits wholly below zero, or the control delta interval sits wholly
  below zero over at least 40 paired sessions.
- **NOT YET** otherwise, with every reason (the count, the days, an interval
  that holds zero, too few paired sessions).

Every report ends with: "Money only past the gate; the gate is not a
forecast." The taken trades are reported beside the paper rows, never
instead of them.

## What to show the user (JSON keys; Python computed every number)

From `report --json`, narrate these keys and do no arithmetic in prose:

- `counts.triggers`, `counts.outcomes`, `counts.decisions`, `counts.controls`
- `paper.n`, `paper.expectancy` (mean, lo, hi, n), `paper.decided` (k, n, p,
  lo, hi), `paper.net_break_even`, `paper.cost_r_mean`
- `control.delta` (delta, lo, hi, n_sessions), `control.expectancy`
- `taken.n`, `taken.realized` (mean, lo, hi, n), `taken.broker_basis`
- `days`, `first_trigger`, `gate.state`, `gate.reasons`, `gate.text`, `footer`

From `journal --json`: `blocks.taken`, `blocks.skipped`, `blocks.undecided`
(n, total_r, expectancy, win_rate, wilson, profit_factor, avg_winner_r,
avg_loser_r, largest_loss_r, mae_mean_r, mfe_mean_r), then `by_setup` and
`by_month`. `profit_factor` is null when there is no losing trade: say "n/a".

Quote `gate.text` and `footer` word for word. Never round, add or compare
numbers yourself.

## Rules

- Append-only. A trigger id is written once; `score` skips ids already scored.
- Every check has three outcomes: pass, fail, unverified. Bars that could not
  be read are unverified, never a zero.
- Python computes every number; this skill narrates the JSON keys it prints.
- The record measures the rule on every trigger. Skipping a trigger does not
  remove it; taking one does not replace its paper score.
- No sentence here or in the output promises a gain. A past sample is not a
  forward result.

## What it never does

- It never places, changes or cancels an order.
- It never edits or deletes a line of the record.
- It never reads the Monte Carlo replays: the gate reads the record only.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Paper first: until the gate passes, the record is the paper account and the
  $100,000 notional is a unit of account, not an instruction to trade it.
- Nothing in this pack places an order. In this fork every order is typed by
  the owner at the broker by hand, and only after trader-risk passed that
  exact order and the owner said yes to it.
- No options, margin, short selling or leverage.
