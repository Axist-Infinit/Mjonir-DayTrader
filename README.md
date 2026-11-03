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
| 1 | Data layer on Massive: a stdlib `mjonir/` package (client, market calendar, bar cache, read-only local stores, Yahoo-shaped output), `--source massive` on each script, a bridge CLI, years of history instead of 60 days | planned |
| 2 | Costs and intervals: slippage, spread and commission in every R; Wilson and bootstrap intervals; verdicts that say "cannot judge" below 40 fires | planned |
| 2 | Random-entry control: every replay compared with random entries on the same sessions | planned |
| 3 | Forward record and gate: `/trader-record` logs every trigger, taken or skipped, scores it after the close and prints the money gate | planned |
| 3 | Risk in percent of a $100,000 notional; a relative-volume opening-range hypothesis, preregistered before any code | planned |
| 4 | Human E*TRADE ticket: `/trader-broker` prints the order for the owner to type by hand | planned |
| 4 | The desk: `/trader-desk` runs the daily routine as one command | planned |

The two new skill folders, `/trader-record` and `/trader-desk`, are stubs
today: each SKILL.md says what it will do and points to docs/RUNBOOK.md.

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

## A note on the numbers

The TSLA example in the Upstream section below is upstream's arithmetic:
gross, with no transaction costs, no confidence interval and no random-entry
control. Chunk 2 recomputes it net of costs, and once it lands the numbers in
that example will change (the history's average R, the verdict line, and
whether the 1R plan clears reward to risk). Until then they stand as upstream
published them.

## Layout

```
.claude-plugin/   plugin mjonir-daytrader in marketplace mjonir, "skills": "./"
trader-*/         upstream's eleven skills, plus trader-record and trader-desk (stubs)
mjonir/           the stdlib data and measurement layer (chunk 1 onward)
docs/             RUNBOOK.md, reviews/
record/           the forward record: tracked, append-only (chunk 3)
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
   midpoint, 358.32, so 5.86 a share at risk; target one times that risk,
   370.04; flat by 3:55 PM either way.
5. **`/trader-timemachine`** replayed the rest of the day 10,000 times, each
   5-minute candle drawn from TSLA's own candles at that time of day over the
   previous 59 sessions (seed 19, so anyone can repeat it): target first
   29.4 %, stop first 25.5 %, still open at the close 45.1 %. It also re-ran
   the same rule on those 59 real sessions: it fired 33 times, 13 hit the
   target, 15 the stop, 5 neither. Its verdict: close to a coin flip. That is
   the point of looking before you risk a dollar.
6. **`/trader-budget`** with a $5,000 account and a $50 max loss per trade:
   50 / 5.86 = 8 shares ($2,913.44). If the stop fills at 358.32, the loss is
   $46.88. It writes one bracket order: buy 8 TSLA, stop-loss 358.32,
   take-profit 370.04.
7. **`/trader-risk`** checks it against your limits: the max loss, the daily
   loss limit, trades per day, reward to risk, the entry window, position
   size and cash. PASS or BLOCK, with the reason.
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
python3 trader-exit/exit.py plan --stop or-mid --target 1R --write     # -> trader/plan.json
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

**This fork.** Under `--source massive` (chunk 1) the scripts read the
Massive API with the owner's own key from the environment; the key is never
printed or written to a file. The owner places every order by hand at
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
