# Runbook: the trading day (ET)

Status: chunk 1 built the data layer. Steps marked "(chunk N)" are not built
yet; their commands will not run until that chunk lands. Everything unmarked
runs today.

Every time below is New York time. The box clock is Mountain, so read times
from the scripts' output or from `TZ=America/New_York date`, never from the
bare system clock. Run every command from the repo root (`cd
/home/axis/Mjonir-DayTrader`): each script resolves `trader/` from the cwd.
The full hazard list is in CLAUDE.md.

## Data

- Every fetching script takes `--source massive`; or `export
  TRADER_SOURCE=massive` once per shell and leave the flag off. Without
  either, the scripts read Yahoo as upstream does.
- The key lives in `~/Infinit/.env` (`MASSIVE_API_KEY`). Never create
  `<repo>/.env` with a key. `python3 -m mjonir.bridge status` says which
  variable holds it (never the value), probes it (authenticated, rejected or
  unverified) and warns if `<repo>/.env` holds one.
- Replays and bulk history: `python3 -m mjonir.bridge intraday SYM --day D`
  (`<SYM>.json` for `entry.py --offline DIR`), `... intraday SYMS --day D
  --bundle` (one file for `scan.py orb --offline`), `... history SYM --from D
  --to D` (`<SYM>-60d5m.json.gz` for `timemachine.py --offline DIR`), `...
  quotes SYMS` and `... news SYMS` (for `alerts.py` and `news.py --offline`).
  Exit codes: 0 ok, 1 refused, 2 unverified.
- Options, indices and Benzinga are not entitled on this key: never asked.

## Weekly, Sunday evening

- `python3 -m mjonir.bridge calendar`: `trader/calendar.json` from Massive's
  market status (the scripts' holiday and early-close lists extend from it).
- `python3 -m mjonir.bridge universe`: `trader/universe.txt`, common stocks
  and ADRs over the price and ADV floors in `trader/config.json`
  (`universe.min_price`, `universe.min_adv_usd`), with a funnel record in
  `trader/data/universe/`.
- `python3 -m mjonir.bridge status`: key, probe, calendar, cache, universe,
  the read-only local stores.
- `desk.py weekly` (chunk 4) will chain the three.
- `record.py journal` (chunk 3), and read the gate.

## 08:00 to 08:30, premarket

- `desk.py premarket` (chunk 4) will chain these; today run them by hand:
  - daily scan on the universe, from grouped-daily bars (real highs and
    lows): `python3 trader-scanner/scan.py daily --source massive --universe
    trader/universe.txt` (or `python3 -m mjonir.bridge daily`, then
    `scan.py daily --offline <the file it names>`); the watchlist of at most
    30 is chunk 4's cut;
  - news on the watchlist, Yahoo RSS, EDGAR 8-K and Massive news in one list:
    `python3 trader-news/news.py --tickers SYM --hours 12 --source massive`;
  - SEC facts only for names reporting this week (`python3 trader-analyst/facts.py SYM`).
- Optional context, in chat: the catalyst-rotation-scout regime dashboard,
  the qqq-overnight-move-scout 09:31 gap update, the elite-day-trader-manager
  pretrade gates on the one name picked. These narrate; they never replace
  the scripts' numbers.

## 09:35, relative volume

- `scan.py rvol` writes the top-20 relative-volume list (chunk 3).

## 09:45 to 10:15, the opening range

- `python3 trader-scanner/scan.py orb --at 10:15 --source massive
  --watchlist trader/watchlist.json` (the union with the RVOL list arrives in
  chunk 3).
- The owner picks ONE name.

## On the pick: arm

- `python3 trader-entry/entry.py watch SYM --source massive`, or `/loop 5m`
  over `entry.py check SYM --source massive`.
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

- `python3 trader-alerts/alerts.py add --from-plan`, then `/loop 5m` over
  `alerts.py check --source massive` (one snapshot request for every ticker).
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
