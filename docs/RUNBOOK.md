# Runbook: the trading day (ET)

Status: chunk 1 built the data layer, chunk 2 the measurement (costs,
intervals, the random-entry control; on `feat/c2-measure`) and chunk 3 the
forward record and the risk in percent of the trade notional (on
`feat/c3-record`) and the relative-volume list (on `feat/c3b-rvol`; its
preregistration, docs/PREREG_RVOL_ORB.md, is a DRAFT until the owner freezes
it, and its study has not been scored). Steps marked
"(chunk N)" are not built yet; their commands will not run until that chunk
lands. Everything unmarked runs today.

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
- `python3 trader-record/record.py journal`, then `record.py report`: read
  the gate (PASSES, FAILS or NOT YET, with the reasons).

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

- `python3 trader-scanner/scan.py rvol --source massive`, after the 9:30 bar
  closes (refused before 9:35): the top 20 names by first-bar relative volume,
  the list of docs/PREREG_RVOL_ORB.md. It writes `trader/rvol.json`, puts the
  fires (the names whose 9:30 bar closed above its open) into
  `trader/watchlist.json` as setup `rvol_orb5` beside the premarket hits, and
  records each fire in the forward record with the prereg's plan (a tenth of
  the 14-day daily ATR under the entry, no target, out at the flat-by). A scan
  made after 9:45, or a `--date` replay, records nothing. The list is a
  hypothesis under test, not a signal, and the live list can differ from the
  study's on a few names a day.

## 09:45 to 10:15, the opening range

- `python3 trader-scanner/scan.py orb --at 10:15 --source massive
  --watchlist trader/watchlist.json` (the watchlist holds the premarket hits
  and the RVOL fires).
- The owner picks ONE name.

## On the pick: arm

- `python3 trader-entry/entry.py watch SYM --source massive`, or `/loop 5m`
  over `entry.py check SYM --source massive`.
- On a trigger the desk (chunk 4) chains:
  - exit plan, default `--stop or-mid --target 2R`
    (`python3 trader-exit/exit.py plan --stop or-mid --target 2R --source
    massive --write`): gross and net reward:risk, the cost card (the ADV$ tier
    from Massive), refused under `min_reward_risk` on the net basis; the
    Zarattini form is `--target none --exit close --stop datr:0.10` (the stop
    from Massive's daily ATR; trader-budget writes an OTO order and the
    ticket says to flatten by the flat-by);
  - time machine: `python3 trader-timemachine/timemachine.py run --source
    massive --years 2 --control-draws 3 --until 15:55 --write` (`--until`
    the plan's flat-by; the entry window is the config's no_entries_after,
    as the record's): the verdict reads the history, net of costs, with its
    interval, and the control delta; the Monte Carlo is a shape diagnostic
    only;
  - size: `python3 trader-budget/size.py --write` sizes net of costs from the
    `sizing` block: shares from the $100,000 trade notional capped by the 1%
    max loss (the round trip and both commissions included); it prints the
    notional and the risk in dollars and as a percent of the notional;
  - risk check: `python3 trader-risk/check.py --source massive` checks loss
    and reward:risk net of costs, the spread (live NBBO) and a no-target plan
    (`allow_no_target`), the price and ADV floors, the chase (live ask),
    averaging down, the daily and weekly loss REALIZED from the record, and
    the losing-streak pause, each pass, block or unverified; with
    `block_on_unverified` (the example config) an unverified check blocks;
  - the human ticket (chunk 4). The owner places the bracket by hand at
    E*TRADE and types the fills into `ticket.py fill`.
- Every trigger, taken or skipped, lands in `record/triggers.jsonl`:
  `entry.py check` and `watch` append it (`--record` is on by default), with
  trader-exit's default plan for the setup unless `--plan` names one;
  `ticket.py approve` and `decline` append the decision; `ticket.py fill`
  holds the fills `record.py score` reads for a taken trade. Enter the fills
  before the 16:30 score: fills typed after it do not reach the record yet (a
  score line is written once). A `fill` row kind (append-only, paired to the
  trigger, preferred over the score's broker block) is chunk 4's. Never edit a
  score line by hand.

## During the trade: manage

- `python3 trader-alerts/alerts.py add --from-plan`, then `/loop 5m` over
  `alerts.py check --source massive` (one snapshot request for every ticker).
- Flat by 15:55 (12:55 on early-close days).
- No adds, no averaging down, no chasing past 0.5% over the trigger (the
  risk check blocks all three: a second buy of the name today is a
  duplicate, `averaging_down` and `chase`).

## 16:30, close

- `desk.py close` (chunk 4) will chain these; today run them by hand:
  `python3 trader-record/record.py score --date <today> --source massive`
  fills outcomes from the session's 5-minute bars (and the hand-entered fills
  where they exist) and writes the matched control rows, once; then
  `record.py report` prints the report and the gate; then commit `record/`
  (`git add record/ && git commit`).

## The money gate

At least 40 resolved trades AND at least 180 days, with the net expectancy
interval above zero AND beating the matched random-entry control. Until then
the record is the paper account, and the $100,000 notional is a unit of
account, not an instruction to trade it. The gate is not a forecast.

Not financial advice. Most people who day trade lose money.
