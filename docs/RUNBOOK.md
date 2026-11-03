# Runbook: the trading day (ET)

Status: stub, written in chunk 0. Steps marked "(chunk N)" are not built yet;
their commands will not run until that chunk lands. Everything unmarked is
upstream's tooling as it ships today, on Yahoo data.

Every time below is New York time. The box clock is Mountain, so read times
from the scripts' output or from `TZ=America/New_York date`, never from the
bare system clock. Run every command from the repo root (`cd
/home/axis/Mjonir-DayTrader`): each script resolves `trader/` from the cwd.
The full hazard list is in CLAUDE.md.

## Weekly, Sunday evening

- `desk.py weekly` (chunk 4): calendar from Massive market-status (chunk 1),
  the universe rebuilt at the $5 price and $20M ADV floors (chunk 1), store
  status (chunk 1).
- `record.py journal` (chunk 3), and read the gate.

## 08:00 to 08:30, premarket

- `desk.py premarket` (chunk 4):
  - daily bundle from grouped-daily bars, real highs and lows (chunk 1);
  - daily scan on the universe to a watchlist of at most 30
    (`python3 trader-scanner/scan.py daily` today; `--source massive` in chunk 1);
  - news on the watchlist: Yahoo RSS and EDGAR 8-K today, Massive news added in chunk 1
    (`python3 trader-news/news.py --tickers SYM --hours 12`);
  - SEC facts only for names reporting this week (`python3 trader-analyst/facts.py SYM`).
- Optional context, in chat: the catalyst-rotation-scout regime dashboard,
  the qqq-overnight-move-scout 09:31 gap update, the elite-day-trader-manager
  pretrade gates on the one name picked. These narrate; they never replace
  the scripts' numbers.

## 09:35, relative volume

- `scan.py rvol` writes the top-20 relative-volume list (chunk 3).

## 09:45 to 10:15, the opening range

- `python3 trader-scanner/scan.py orb --at 10:15` on the watchlist union the
  RVOL list (the union arrives in chunk 3).
- The owner picks ONE name.

## On the pick: arm

- `python3 trader-entry/entry.py watch SYM` (`--source massive` in chunk 1),
  or `/loop 5m` over `entry.py check SYM`.
- On a trigger the desk (chunk 4) chains:
  - exit plan, default `--stop or-mid --target 2R`
    (`python3 trader-exit/exit.py plan --stop or-mid --target 2R --write`); the
    Zarattini form `--target none --exit close --stop datr:0.10` is chunk 2;
  - time machine with `--years 2 --control-draws 3` (chunk 2): the verdict
    reads the history, net of costs, with its interval and the control delta;
  - size: shares from the $100,000 notional capped by a 1% max loss (chunk 3);
  - risk check, every check pass, block or unverified (chunk 3);
  - the human ticket (chunk 4). The owner places the bracket by hand at
    E*TRADE and types the fills into `ticket.py fill`.
- Every trigger, taken or skipped, lands in `record/triggers.jsonl` (chunk 3).

## During the trade: manage

- `python3 trader-alerts/alerts.py add --from-plan` (`--source massive` in
  chunk 1), then `/loop 5m` over `alerts.py check`.
- Flat by 15:55 (12:55 on early-close days).
- No adds, no averaging down, no chasing past 0.5% over the trigger (the
  risk check blocks all three in chunk 3).

## 16:30, close

- `desk.py close` (chunk 4): `record.py score --date today` (chunk 3) fills
  outcomes from the session's 5-minute bars (and the hand-entered fills where
  they exist), writes the matched control rows, prints the report and the
  gate, and commits `record/`.

## The money gate

At least 40 resolved trades AND at least 180 days, with the net expectancy
interval above zero AND beating the matched random-entry control. Until then
the record is the paper account, and the $100,000 notional is a unit of
account, not an instruction to trade it. The gate is not a forecast.

Not financial advice. Most people who day trade lose money.
