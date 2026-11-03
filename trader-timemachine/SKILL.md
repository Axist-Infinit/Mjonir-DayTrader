---
name: trader-timemachine
description: >-
  Time Machine. Measures a trade before you risk a dollar: the plan's own rule
  on every past session net of costs, beside a random-entry control and a
  buy-any-morning-strength baseline, plus 10,000 simulated sessions as a
  shape diagnostic. Takes the plan from trader-exit (entry, stop, target),
  re-runs the same rule on every past session (60 days from Yahoo, or years
  from Massive), and prints the net average R with its interval, the decided
  count with its Wilson interval, the fragile decisions, a one-tick
  sensitivity, the year table, and one verdict read from the history, then
  hands off to /trader-budget. Use when the user says "run the time machine",
  "replay this trade", "what are the odds", "simulate this trade", "monte
  carlo", "backtest this setup", "how often does this hit the target", "is
  this a coin flip", or after /trader-exit writes a plan, before
  /trader-budget.
argument-hint: "[path to plan.json, or TICKER]"
---

# trader-timemachine

The Time Machine sits between the plan and the money. trader-exit has set
the entry, the stop and the target. Before anything is sized or sent, this
skill asks one question: what did the same rule really do on the stock's own
past sessions, after costs, and did its entry beat a random entry on those
same sessions? It answers with the real record (60 days from Yahoo, or
`--years N` from Massive), its intervals and a random-entry control, and adds
10,000 replays as a shape diagnostic. It is a measurement of the past, not a
prediction. Day trading loses most people money, and a
good-looking replay does not change that.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run                    # trader/plan.json, 10,000 replays, seed 19
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --write            # also save trader/timemachine.json
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --until 15:55      # end each replay at your flat-by time
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --json
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --symbol TSLA --date 2026-10-19 \
    --entry 364.18 --stop 358.32 --target 370.04 --entry-time "10:15 AM"
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" chart --from           # ASCII fan chart of the saved run
```

Other flags: `--replays N`, `--seed N` (default 19), `--window N` (default 2
bars), `--offline FILE` (a saved Yahoo chart JSON, `.json` or `.json.gz`),
`--now "2026-10-19 10:15"` (New York time) to pin the clock,
`--control-draws K` (default 3), `--gap-fill open|stop` (default open),
`--no-costs` (gross only: upstream's mechanics with `--gap-fill stop`).

## What it reads and writes

| file | what |
| --- | --- |
| `trader/plan.json` | the plan from trader-exit: symbol, date, entry, entry_time / entry_bar, stop, stop_rule, target, target_r, opening range |
| Yahoo chart API | one request: 60 days of 5-minute bars (`range=60d&interval=5m`), free and unofficial, can lag |
| `trader/timemachine.json` | with `--write`: `{data, plan, costs, mc, history, verdict_history, verdict_control, mc_shape, mc_notes}`. `history` holds the trades, `net` and `gross` (mean, lo, hi, n), `decided` (k, n, Wilson), `fragile`, `sensitivity`, `by_year`, `control`, `baseline`. `mc` holds the odds, percentiles, the fan-chart bands, 160 sample paths and a 24-bin histogram of the close |

## How it works

1. **The pool.** It keeps only FULL sessions before the plan's date: all 78
   five-minute bars, 9:30 to 4:00 New York time. Half days, gaps and today
   are left out. Every bar becomes four ratios to the bar before it:
   open, high, low and close over the previous close.
2. **One replay.** Start at the entry price. For each bar left in the day,
   pick a past bar from the same time of day (plus or minus 2 bars) at
   random, and scale it to the current price. Bar by bar, it checks the stop
   first, then the target. A bar that touches both counts as the stop.
3. **10,000 replays** give four odds. Target first. Stop first. Neither,
   which means the trade was still open at `--until` (default 4:00 PM, the
   close, or 1:00 PM on an NYSE early-close day). Green, which means target
   first or above the entry at `--until`.
   R is +1 at a 1R target, -1 at the stop, and otherwise the distance from
   the entry at `--until` divided by the risk. A bar that opens through the
   stop fills at its open (worse than -1R; `--gap-fill stop` keeps -1R).
   This block is a SHAPE diagnostic: an unconditional per-slot bootstrap,
   not conditioned on the breakout, volatility regimes mixed. Its line
   (`mc_shape`) states the two shares and no verdict reads it.
4. **The history.** The plan's own rule (the same opening range, stop rule
   and target R) runs again on every past session: the full ones and the
   1:00 p.m. early closes (42 bars, scored to the 1:00 PM close, the flat-by
   moved up three hours). Other short sessions are dropped and listed. The
   entry is the unrounded bar close. Every trade is charged its own round
   trip once (`costs`): slippage by the stock's ADV$ tier, the half spread,
   the commission. That is what really happened, net of costs.
5. **Every average comes with its interval and n**: the net and gross
   average R (95 % bootstrap), the decided count (target or stop) with its
   Wilson interval, the fragile decisions (the deciding touch cleared its
   level by under 0.05 R), the one-tick sensitivity (how many outcomes flip
   with the entry 1 cent higher or lower), and the net average by year with
   a note when its sign flips between years.
6. **The control and the baseline.** On every session where the rule fired,
   K random entries after the opening range, with the rule's risk percent,
   the same target multiple and flat-by: the paired net delta and its
   interval. The baseline buys the close of the last opening-range bar on
   every session: a diagnostic, never a verdict.
7. **The verdicts** are fixed templates (`verdict_history`, `verdict_control`,
   each with `state` pass / fail / unverified). The history verdict reads
   ONE statistic, the money gate's own: the 95 % bootstrap interval of the
   net R over every fire, against 0. Under 40 fires it says "Cannot judge";
   an interval holding 0 is "not distinguishable from zero"; wholly under 0
   is "Below zero", wholly over 0 "Above zero". For a plan with a target the
   decided rate and its Wilson interval follow as a diagnostic, against the
   net break-even (1 + c) / (target R + 1) at the history's own mean round
   trip c; it never sets the state. The control verdict reads the paired net
   delta and needs 40 paired sessions.

**The seed.** The draws come from Python's `random.Random(seed)`, seed 19 by
default. Same plan, same data, same seed: the same numbers, on any machine.
Say the seed with every result so the user can repeat it.

**5-minute bars only.** Yahoo keeps 60 days of 5-min bars but only about 7
days of 1-min bars, too few sessions for a fair pool. It refuses, in one
plain line, when there are fewer than 20 full sessions, when the entry bar is
not in the data (wrong date, not closed yet, a future day), or when the plan
does not make sense (a stop above a buy's entry, an entry off the 5-minute
grid). A live in-progress bar is never used.

## Steps

1. Make sure `trader/plan.json` is today's plan from `/trader-exit` (it
   carries the cost card). If there is none, run that first, or pass the plan
   as flags.
2. Run `timemachine.py run --write`. Add `--until 15:55` when the plan has a
   flat-by time. With a Massive key, `--source massive --years 2` reads two
   years instead of 60 days.
3. Tell the user, in this order: the `verdict_history` text exactly as
   printed (it carries the net average with its interval and n, and the
   decided count with its Wilson interval), the `verdict_control` text
   exactly as printed, the fragile count and the one-tick flips. Then, if asked, the shape diagnostic
   line. Say the seed.
4. If the verdict says "Cannot judge", "not distinguishable" or "Below zero", say so
   plainly. Do not dress it up, and never read the shape diagnostic as odds.
5. Say once that this is a measurement of past sessions, not a prediction.
   Earnings, news and halts can do things those sessions never did. Check
   `/trader-news` for the stock before going on.
6. If the user still wants the trade, hand off to `/trader-budget` to size it.

## Example: the reel

TSLA, Monday 2026-10-19. The 15-minute opening range is 354.47 to 362.18.
The 10:10 bar closes above it: entry 364.18 at 10:15 AM (bar 8), stop 358.32
(the range midpoint, rounded down), target 370.04 (1R, risk 5.86 a share).
Upstream's 60 days of Yahoo bars, the 4 bp tier TSLA's ADV$ clears:

```
Costs: 0.7599 a share round trip = 0.130 R (4 bp slippage tier, ...; 3 bp half spread, the default, unverified; $1 commission a side over 8 shares).
History: the same rule ... on each of those 59 real sessions fired 33 times: 13 target, 15 stop, 5 neither.
Average R, net of costs, -0.261 (95 % bootstrap interval -0.592 to +0.074, n 33).
  Gross average R -0.062 (95 % bootstrap interval -0.392 to +0.263, n 33); costs 0.199 R a trade on average (n 33).
  Decided: 13 of 28 hit the target first (46.4 %, 95 % Wilson 29.5 % to 64.2 %); 11 of the 28 decided by under 0.05 R (fragile).
  One-tick sensitivity: the entry 1 cent higher flips 1 outcome, 1 cent lower flips 0 (of 33).
Cannot judge: 33 fires, net average -0.261 R a trade (95% bootstrap [-0.592, +0.074]); n is below the 40-fire floor. Decided: 13 of 28 hit the target (46.4%, 95% Wilson [29.5%, 64.2%]) against a net break-even of 59.9% at 1R after costs (the history's own mean round trip, 0.199 R).
Cannot judge against the random-entry control: net delta -0.293 R a trade (95% bootstrap [-0.581, -0.013]) over 33 paired sessions; 33 is below the 40-session floor.
Shape diagnostic (unconditional per-slot bootstrap, not conditioned on the breakout, vol regimes mixed): target first 29.4 % vs stop first 25.5 %.
```

Thirty-three fires are under the 40-fire floor, and the net interval runs
from -0.592 to +0.074 R a trade: it cannot judge. That is the honest answer
for this setup, and it is what the user should hear before `/trader-budget`
sizes anything.

## Rules

- Every number comes from the run. Never round "Cannot judge" up into a yes.
- The verdict lines are printed by the tool. Repeat them, do not rewrite
  them. Never read the shape diagnostic (target first vs stop first) as the
  verdict: it is not conditioned on the breakout.
- Never print an average without its interval and n.
- Simulated odds are not predictions and not promises. Say it once, plainly.
- Free Yahoo data is unofficial and can lag. Bars are 5-minute bars, checked
  bar by bar, never tick by tick and never real time.
- Always say the seed, so any run can be repeated.
- One plan per run. A changed entry, stop, target or date is a new run.

## Data from Massive

Pass `--source massive`, or export `TRADER_SOURCE=massive`, to build the history from
the Massive market-data API (or the read-only local stores when they hold the whole
range) instead of Yahoo's 60 days. `--sessions N` takes the N sessions up to the
plan's day (the default matches Yahoo's window); `--years N` takes every session of
the N years before it, through `mjonir.bars.bars_5m` (one store per run). `data.range`
then says how many sessions the file really holds; `data.source` (api, cache, kalex or
flatfile) and `data.adjustment` come from that call, never from the flag. ADV$ for the
slippage tier also comes from Massive; under Yahoo it is unverified (the most
expensive tier). For `--offline`, `python3 -m mjonir.bridge
history SYM --from <date> --to <date>` writes `<SYM>-60d5m.json.gz`. Without the
flag nothing changes. The early-close list extends itself from
`trader/calendar.json` (`python3 -m mjonir.bridge calendar`).

## What it never does

It never places an order, never sizes a position, never changes the plan,
and never calls a result a sure thing. It never prints a P&L or a profit.
It never uses a bar that has not closed yet, and never mixes today's bars
into the pool.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Paper trading by default (`"paper": true`). Going live is the user's own decision, in their own config.
- Nothing in this pack places an order except trader-broker, and only when all three hold: trader-risk
  passed that exact order today, the user typed an explicit yes for that one order in the chat, and the
  user clicked Allow once on Claude's own card because the order tool is set to "Needs approval"
  (Customize > Connectors > tool permissions). Never set an order tool to "Always allow".
- No options, margin, short selling or leverage unless the config allows it and the user confirms.
- Broker keys live in environment variables or the Claude Desktop config, never in the chat.
