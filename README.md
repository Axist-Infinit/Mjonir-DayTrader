# The Day Trader skill pack, Massive edition

Jake Schincariol's 11 Claude skills for day trading, forked to read the Massive market-data API, to score every setup net of costs against a random-entry control, and to keep a forward record of every trigger before any money. Work in progress.

This is Mjonir-DayTrader, a fork of
[Jake Schincariol's Day Trader skill](https://github.com/Jakeschincariol/day-trader-skill)
(MIT, forked at `3d0f4ef`; see NOTICE). Upstream's eleven skills are kept.
This fork moves their data onto Massive, measures every result net of costs
with an interval and a random-entry control, and adds a forward record with a
money gate. Orders stay manual: the owner types every ticket at E*TRADE by
hand, and nothing here talks to a broker.

Nothing here promises a profit. Most people who day trade lose money. The
forward record exists to find out, on paper and slowly, whether these setups
beat costs and chance at all. Until its gate passes, this is a paper account.

## Install (this fork)

In Claude Code:

```
/plugin marketplace add Axist-Infinit/Mjonir-DayTrader
/plugin install mjonir-daytrader@mjonir
```

On the owner's box, with the working tree as the marketplace (how this was
verified: docs/reviews/chunk0.md):

```bash
claude plugin marketplace add /home/axis/Mjonir-DayTrader
claude plugin install mjonir-daytrader@mjonir
```

A local folder install reads the skills live from the working tree: whatever
is checked out in `/home/axis/Mjonir-DayTrader` is what loads, at the next
session start or after `/reload-plugins`, and `claude plugin update` has
nothing to do. For a one-off session without installing, `claude --plugin-dir
/home/axis/Mjonir-DayTrader` is accepted. An install from GitHub is fetched
from the remote instead and was not tested here.

Installed as a plugin, the skills show up as `/mjonir-daytrader:trader-scanner`
and so on. Run every command from the repo root: the scripts keep their state
in `trader/` under the current directory.

## What changed from upstream: the roadmap

| chunk | change | status |
| --- | --- | --- |
| 0 | Bootstrap: NOTICE, CLAUDE.md, the plugin renamed `mjonir-daytrader` in marketplace `mjonir`, stub folders for the two new skills, a runbook stub | done |
| 1 | Data layer on Massive: a stdlib `mjonir/` package (client, market calendar, bar cache, read-only local stores, Yahoo-shaped output), `--source massive` on each script, a bridge CLI, years of history instead of 60 days | done on `feat/c1-data` (not merged yet) |
| 2 | Costs and intervals: slippage, spread and commission in every R; Wilson and bootstrap intervals; verdicts that say "cannot judge" below 40 fires | built on `feat/c2-measure` (not merged yet) |
| 2 | Random-entry control: every replay compared with random entries on the same sessions | built on `feat/c2-measure` (not merged yet) |
| 3 | Forward record and gate: `/trader-record` logs every trigger, taken or skipped, scores it after the close and prints the money gate | built on `feat/c3-record` (not merged) |
| 3 | Risk in percent of a $100,000 trade notional: sizing, daily and weekly loss realized from the record, the loss-streak pause, the price, ADV, chase and averaging-down floors | built on `feat/c3-record` (not merged) |
| 3 | A relative-volume opening-range hypothesis, preregistered before any code: docs/PREREG_RVOL_ORB.md, `scan.py rvol` (the live list), `tools/rvol_study.py` (the study's runner), on `feat/c3b-rvol` | prereg DRAFT committed; scanner and runner built; awaiting the owner's freeze |
| 4 | Human E*TRADE ticket: `/trader-broker` prints the order for the owner to type by hand | planned |
| 4 | The desk: `/trader-desk` runs the daily routine as one command | planned |

`/trader-desk` is a stub today: its SKILL.md says what it will do and
points to docs/RUNBOOK.md. `/trader-record` is built (chunk 3).
Built and not merged means the commands run on that branch only.

## The daily routine (ET)

A summary. The full timetable, with each step's build status, is
docs/RUNBOOK.md. Every time is New York time.

- **Sunday evening:** weekly prep (market calendar, universe rebuilt at the
  $5 price and $20M ADV floors, store status); read the journal and the gate.
- **08:00 to 08:30:** premarket. Daily scan to a watchlist of at most 30,
  news on the watchlist, earnings facts only for names reporting this week.
- **09:35:** the top-20 relative-volume list.
- **09:45 to 10:15:** the opening-range scan on the watchlist plus the
  relative-volume list. The owner picks ONE name.
- **On the pick:** watch for the trigger. On it: the exit plan, the time
  machine (net of costs, with its interval and the control), the size from
  the $100,000 notional capped by a 1% max loss, the risk check, then a ticket
  the owner types at E*TRADE by hand. Every trigger, taken or skipped, goes
  into the record.
- **During the trade:** alerts on the stop, the target and the flat-by time,
  15:55 (12:55 on early-close days). No adds, no averaging down, no chasing.
- **16:30:** score the record, print the report and the gate, commit `record/`.
- **The money gate:** at least 40 resolved trades and at least 180 days, with
  the net expectancy interval above zero and beating the random-entry
  control. Until then the record is the paper account, and the $100,000 is a
  unit of account, not an instruction to trade it. The gate is not a forecast.

## The TSLA example, net of costs

The example in the Upstream section below is the reel's trade (TSLA, Monday
2026-10-19, entry 364.18 at 10:15 AM, stop 358.32, risk 5.86 a share).
Upstream scored it gross: no costs, no interval, no control. Chunk 2 (built on
`feat/c2-measure`) scores it net. Every number here was printed by the
scripts; docs/reviews/chunk2.md has the commands and the full output.

- **Costs.** TSLA's ADV$ over the 20 sessions before that day (Massive) is
  about $12.7 billion: the 4 bp slippage tier. With the default 3 bp half
  spread (no live quote for a past day, so the spread check is unverified)
  and $1 commission on each order over 8 shares, the round trip is $0.76 a
  share, 0.130 R.
- **The 1R plan is refused.** Net reward:risk is (5.86 - 0.76) / (5.86 +
  0.76) = 0.77, under the 1.0 minimum, so trader-exit refuses it. trader-risk
  also blocks upstream's 8-share order file: $59.37 at the stop net of costs,
  over the $50 limit; that order carries no cost card, so trader-risk prices
  it at the config's most expensive tier (15 bp plus the 3 bp half spread),
  not TSLA's 4 bp. The example moves to `--target 2R` (375.90): 2.0 gross,
  1.66 net. trader-budget sizes it at 7 shares, because the $50 max loss now
  includes the round trip and both commissions ($46.59 at the stop), and
  trader-risk passes it, with the spread unverified.
- **How the verdict reads.** One statistic sets it, the money gate's own:
  the 95 % bootstrap interval of the net R over every fire, against 0, with
  a 40-fire floor. The decided rate (target or stop) and its Wilson interval
  follow as a diagnostic, against the net break-even at the history's own
  mean round trip; it never sets the verdict. The control verdict needs 40
  paired sessions.
- **The 60-day reading cannot judge.** On upstream's 60 days of Yahoo bars,
  with ADV from Massive (the 4 bp tier), the 1R rule fired 33 times:
  "Cannot judge: 33 fires, net average -0.261 R a trade (95% bootstrap
  [-0.592, +0.074]); n is below the 40-fire floor." Gross it is -0.062. 13
  of 28 decided fires hit the target (46.4 %, Wilson 29.5 % to 64.2 %)
  against a net break-even of 59.9 % (the history's own mean round trip,
  0.199 R: its trades risk less than the reel's 5.86, so each pays more R).
  11 of those 28 decisions cleared their level by under 0.05 R, and the
  entry one cent higher flips one outcome (2026-08-06). The control cannot
  judge either: 33 paired sessions is under the 40-session floor. Without
  Massive (the default Yahoo path) the ADV is unverified, every trade is
  charged the most expensive tier (0.445 R on average), and the same 33
  fires print -0.508. The 2R rule on the same 60 days, ADV from Massive:
  net average -0.352 (-0.678 to +0.017, n 33), cannot judge; 3 of 20
  decided against a 40.0 % net break-even.
- **The two-year reading.** `timemachine.py run --source massive --years 2
  --control-draws 3 --until 15:55` under the example config (each past
  trade's commission spread over the shares its 1 % of $100,000 max loss
  buys; the rule fires and a control enters by 15:30, the config's
  no_entries_after; 499 sessions, 2024-10-21 to 2026-10-16, five early
  closes scored to 12:55): "Edge not distinguishable from zero: 281 fires,
  net average -0.088 R a trade (95% bootstrap [-0.193, +0.023]); the
  interval includes 0. Decided: 127 of 243 hit the target (52.3%, 95% Wilson
  [46.0%, 58.5%]) against a net break-even of 57.1% at 1R after costs (the
  history's own mean round trip, 0.142 R)." Gross it is +0.054 (-0.052 to
  +0.166). Against random entries on the same 281 sessions: "Not
  distinguishable from the random-entry control: net delta -0.061 R a trade
  (95% bootstrap [-0.172, +0.056]) over 281 paired sessions; the interval
  includes 0." The 2R rule over the same two years: "Edge not
  distinguishable from zero: 281 fires, net average -0.054 R a trade (95%
  bootstrap [-0.188, +0.092]); the interval includes 0. Decided: 59 of 190
  hit the target (31.1%, 95% Wilson [24.9%, 38.0%]) against a net
  break-even of 38.1% at 2R after costs (the history's own mean round trip,
  0.142 R)." Its control: net delta -0.074 R a trade (-0.215 to +0.078) over
  281 paired sessions, the interval includes 0. Chunk 2 read the same two
  years with a $50 share basis (8 TSLA shares), the 16:00 last bar and no
  entry window: the 1R rule "Below zero", -0.125 (-0.235 to -0.016, n 285),
  at a 0.181 R mean round trip. docs/reviews/chunk3a.md has both runs.

That is one stock and one rule, measured on past sessions; it is not a
forward result and it promises nothing.

Sized on the fork's example config (chunk 3, built on `feat/c3-record`): a
$100,000 trade notional with a 1 % max loss, net of costs, makes the 2R plan
156 shares ($56,812.08, 56.81 % of the notional); the risk at the stop is
$914.16 before costs and $995.70 net, under the $1,000 cap, and the net
reward:risk at that size is 1.75. The plan's estimate of about 170 shares
was gross (1,000 / 5.86); the 0.51 a share round trip and the two
commissions bring it to 156. The example config's risk check then wants a
live spread and a fresh price before it passes the order; on a past day
both are unverified, so it blocks. docs/reviews/chunk3a.md has the output.

## Layout

```
.claude-plugin/   plugin mjonir-daytrader in marketplace mjonir, "skills": "./"
trader-*/         upstream's eleven skills, plus trader-record (built) and trader-desk (a stub)
mjonir/           the stdlib data and measurement layer (chunk 1 onward)
docs/             RUNBOOK.md, reviews/
record/           the forward record: tracked, append-only (trader-record)
trader/           runtime state and caches: gitignored, created in the cwd
tests/            upstream's suite plus the fork's tests
NOTICE            attribution; LICENSE is upstream's MIT license, unchanged
```

```bash
python3 -m unittest discover -s tests
```

## Upstream: the Day Trader skill v2

Everything from here to the end is upstream's README as published at
`3d0f4ef`, with its headings moved down one level, "Files" moved ahead of
"Fine print", and one paragraph for this fork at the top of "Fine print". Its
install lines install upstream's original plugin, not this fork.

11 Claude skills for day trading: scan thousands of charts, track breaking news, time every entry and exit, and replay every outcome before you risk a dollar.

Free, MIT, no signup, no API key. The tools are plain Python that read free
public data: Yahoo Finance charts, Nasdaq Trader's symbol lists, SEC EDGAR
and the House Clerk.

One scans thousands of charts for setups. Another tracks breaking news on
every stock you watch. One watches a setup bar by bar and tells you the moment
to get in, and another sets your stop and your target before you do. And the
craziest one is the Time Machine: before you risk a dollar, it replays the
rest of the session 10,000 times from the stock's own recent bars, plus every
past day the same setup fired, and tells you the honest odds.

And no trade goes through until you say yes. Nothing in this pack can place
an order on its own. Paper trading is the default.

> **Looking for the original Trader skill?** Copy an investor's 13F, the
> stock screener, tax lots and rebalancing live in
> [github.com/Jakeschincariol/trader-skill](https://github.com/Jakeschincariol/trader-skill).
> This repo is its day-trading sequel: the Trader skill v2.

### Install

Paste this into Claude:

```
https://github.com/Jakeschincariol/day-trader-skill

install skill
```

Or as a plugin, in Claude Code:

```
/plugin marketplace add Jakeschincariol/day-trader-skill
/plugin install day-trader-skill@day-trader-skill
```

Claude Code namespaces plugin skills, so installed as a plugin they show up as
`/day-trader-skill:trader-scanner` and so on. Copy the folders instead if you want
plain `/trader-scanner`:

```bash
git clone https://github.com/Jakeschincariol/day-trader-skill.git
cp -r day-trader-skill/trader-* ~/.claude/skills/
```

Project-local instead of global: copy the same folders into your repo's
`.claude/skills/`. No Claude Code at all? Paste any single `SKILL.md` at the
top of a chat and it runs as a mode. You lose the Python tools, but the method
works.

The tools need Python 3.8 or newer. Nothing to pip install. The SEC tools
(news filings, the analyst) ask you to identify yourself: put your name and
email in `trader/config.json` (`"sec_user_agent": "Your Name you@example.com"`)
or in the `SEC_USER_AGENT` environment variable.

### The eleven

| command | job | what it does |
| --- | --- | --- |
| `/trader-scanner` | Chart Scanner | Scans thousands of charts for setups: opening-range breakouts, flags, oversold bounces. |
| `/trader-news` | News Monitor | Tracks breaking news on every stock you watch and flags what moves it. |
| `/trader-entry` | Entry Timer | Watches a setup bar by bar and tells you the moment to get in. |
| `/trader-exit` | Exit Planner | Sets your stop and your target before you enter, so you know when to get out. |
| `/trader-timemachine` | Time Machine | Replays every possible outcome of a trade before you risk a dollar: 10,000 simulated sessions plus every past time the setup fired. |
| `/trader-risk` | Risk Manager | Checks every trade against your limits and stops anything over them. |
| `/trader-budget` | Budget Manager | Sizes every position to your budget and your max loss per trade. |
| `/trader-broker` | Order Executor | Sends approved orders to your broker, paper trading by default, never without your yes. |
| `/trader-alerts` | Price Alerts | Rings when a price, a stop or the opening bell hits. |
| `/trader-analyst` | Earnings Analyst | Reads earnings reports and sums up what changed. |
| `/trader-pelosi` | Pelosi Tracker | Reads Congress's stock-trade disclosures the minute they are filed. |

### How to use it

Everything lands in a `trader/` folder in your project, and each skill reads
what the last one wrote:

```
scanner -> news -> entry -> exit -> timemachine -> budget -> risk -> broker   (one trade)
alerts: stop, target, flat by the close                                       (while it is open)
news / analyst / pelosi                                                        (on a schedule)
```

An example, the trade in the reel: Tesla, Monday October 19 2026, real data.

1. **`/trader-scanner`** at 10:15 AM ET: of the 231 charts in the reel's
   scan, 42 had closed above their 15-minute opening range. TSLA is one: range 354.47 to 362.18,
   the 10:10 candle closed at 364.18, 0.55 % over the top.
2. **`/trader-news`**: the morning's TSLA headlines, in New York time
   ("Tesla-SpaceX Merger Mania Strikes Wall Street Ahead of Earnings", 8:04,
   tagged earnings and deal). Tesla reports this week: a day trade is out
   before the close, so it is not exposed to the report.
3. **`/trader-entry`** watched TSLA bar by bar. At 10:12 it said waiting (the
   10:10 bar was still forming). At 10:15 it said triggered: the first
   5-minute close above the range, 364.18.
4. **`/trader-exit`** set the plan before the entry: stop at the range's
   midpoint, 358.32, so 5.86 a share at risk; flat by 3:55 PM either way.
   Upstream's target was one times that risk, 370.04; net of a $0.76 a share
   round trip that is 0.77 reward to risk, and this fork refuses it. The
   target here is two times the risk, 375.90: 2.0 gross, 1.66 net.
5. **`/trader-timemachine`** re-ran the same rule on the previous 59 real
   sessions, net of costs (ADV from Massive): the 1R rule fired 33 times, 13
   hit the target, 15 the stop, 5 neither. Its verdict: "Cannot judge: 33
   fires, net average -0.261 R a trade (95% bootstrap [-0.592, +0.074]); n is
   below the 40-fire floor." The 2R plan's 60 days cannot judge either (net
   -0.352, n 33). On two years of Massive bars under the example config both
   rules' net intervals hold zero (1R -0.088, -0.193 to +0.023; 2R -0.054,
   -0.188 to +0.092; n 281) and neither is distinguishable from random
   entries (above, "The TSLA example, net of costs"). Its 10,000 replays of the rest of the
   day (seed 19) are a shape diagnostic only: target first 29.4 %, stop
   first 25.5 %, still open at the close 45.1 %. That is the point of
   looking before you risk a dollar.
6. **`/trader-budget`** with a $5,000 account and a $50 max loss per trade,
   net of costs: (50 - 2 commissions) / (5.86 + 0.51 round trip) = 7 shares
   ($2,549.26). If the stop fills at 358.32, the loss is $46.59 with costs.
   It writes one bracket order: buy 7 TSLA, stop-loss 358.32, take-profit
   375.90. (Upstream sized 8 shares, $46.88, at 1R with no costs. The fork's
   example config sizes against a $100,000 trade notional instead: 156
   shares, above.)
7. **`/trader-risk`** checks it against your limits: the max loss and
   reward to risk net of costs, the spread, the daily loss limit, trades per
   day, the entry window, position size and cash. PASS or BLOCK, with the
   reason; an unverified check says so.
8. **`/trader-broker`** shows you the ticket in plain words. You type yes for
   that exact order. Claude calls your brokerage connector (Alpaca's MCP
   server, paper account by default), and Claude's own "Allow once / Deny"
   card asks you one more time.
9. **`/trader-alerts`** rings on the stop, the target and at 3:55 PM to
   flatten whatever is still open.

### The tools

All standard-library Python. The data tools read public endpoints and are
polite about it.

```bash
python3 trader-scanner/scan.py universe                                # ~5,900 US stocks, Nasdaq Trader
python3 trader-scanner/scan.py daily                                   # pre-market setups, whole universe
python3 trader-scanner/scan.py orb --at 10:15                          # opening-range breakouts so far
python3 trader-news/news.py --tickers TSLA --hours 12                  # headlines, 8-Ks, today's move
python3 trader-entry/entry.py check TSLA --setup orb                   # waiting / triggered / expired
python3 trader-entry/entry.py watch TSLA --every 30                    # bar by bar until it triggers
python3 trader-exit/exit.py plan --stop or-mid --target 2R --write     # -> trader/plan.json
python3 trader-timemachine/timemachine.py run --write                  # 10,000 replays + the history
python3 trader-budget/size.py --write                                  # -> trader/orders.json
python3 trader-risk/check.py                                           # PASS / BLOCK per order
python3 trader-broker/ticket.py show                                   # the tickets, READY or not
python3 trader-alerts/alerts.py add --from-plan                        # stop, target, flat by close
python3 trader-alerts/alerts.py check                                  # rings what hit, once
python3 trader-analyst/facts.py TSLA                                   # quarters, growth, EPS
python3 trader-pelosi/ptr.py index --member pelosi                     # her PTRs this year
```

```bash
python3 -m unittest discover -s tests -v
```

The tests run offline, on fixtures cut from real data: TSLA's 5-minute bars
for the 60 days to October 19 2026, the 10:15 AM opening-range scan, Yahoo's
TSLA headlines that morning, the House Clerk's 2026 index, real PTR text and
real XBRL facts. They reproduce every number in the example above.

### Files

```
trader-scanner/     SKILL.md, scan.py
trader-news/        SKILL.md, news.py
trader-entry/       SKILL.md, entry.py
trader-exit/        SKILL.md, exit.py
trader-timemachine/ SKILL.md, timemachine.py
trader-risk/        SKILL.md, check.py
trader-budget/      SKILL.md, size.py, config.example.json, targets.example.json
trader-broker/      SKILL.md, ticket.py, claude_desktop_config.example.json
trader-alerts/      SKILL.md, alerts.py, alerts.example.json
trader-analyst/     SKILL.md, facts.py, metrics.example.json
trader-pelosi/      SKILL.md, ptr.py
tests/              unittest suite + offline fixtures
```

## Fine print

**This fork.** Under `--source massive` (or `TRADER_SOURCE=massive`) the
scripts read the Massive API with the owner's own key from `~/Infinit/.env`;
the key is never printed or written to a file, and never belongs in
`<repo>/.env`. `python3 -m mjonir.bridge status` checks it. The owner places every order by hand at
E*TRADE: upstream's broker connector setup (Alpaca, Interactive Brokers) is
not used here, and chunk 4 rewrites `/trader-broker` to print a human ticket.
The forward record's gate, not any replay, decides whether money is ever used.
Upstream's fine print follows and still applies.

**Not financial advice.** This is software that reads public data and does
arithmetic. It does not know your situation and it cannot see the future.
Most people who day trade lose money. You can lose money. Decide for
yourself, and talk to a licensed professional if you need advice.

**No trade goes through until you say yes.** Only `/trader-broker` can lead to
an order, and only after `/trader-risk` passes that exact order and you type
yes for it in the chat. Set your brokerage tool to "Needs approval" in Claude
(Customize, Connectors, tool permissions), never "Always allow", so Claude's
own "Allow once / Deny" card is a second check. No options, margin, short
selling or leverage unless you turn them on.

**Paper first.** `"paper": true` is the default in `config.example.json`, and
Alpaca's MCP server defaults to its paper account. Keys live in environment
variables, never in the chat.

**The Time Machine is a simulation, not a prediction.** It is built from the
stock's own last 60 days of 5-minute bars. The future can do things those 60
days never did: an earnings report, a halt, a headline. Treat its odds as a
reality check, never as a promise.

**A stop is a plan, not a guarantee.** In a fast market or across a gap, a
stop order can fill well past its price. The max loss shown is the loss at
the stop price.

**The data is free and unofficial.** Yahoo Finance's chart endpoint is not an
official API: it can lag, change or rate-limit you. The scanner and the entry
timer read 1-minute or 5-minute bars, not every tick. Check anything that
matters against your broker before you act on it.

**Day-trading rules.** FINRA removed the $25,000 pattern-day-trader minimum
on June 4, 2026 (Regulatory Notice 26-10), and brokers may phase the change
in until October 20, 2027, so yours may still apply the old rule. If it does,
set `"pdt_guard": true` and `/trader-risk` counts your day trades.

**Congress's trades are public, not inside information.** Members must disclose
trades over $1,000 within 45 days (the STOCK Act). The Pelosi skill reads those
public filings the minute they post.

**Taxes.** Day-trading gains are short-term gains, and frequent trading makes
wash sales likely. Nothing here is tax advice.

MIT. Made by [Jake Schincariol](https://opusjake.ai).
Fork maintained by [Axist-Infinit](https://github.com/Axist-Infinit/Mjonir-DayTrader); see NOTICE.
