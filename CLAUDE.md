# Mjonir-DayTrader

A fork of Jake Schincariol's Day Trader skill pack (MIT, upstream `3d0f4ef`, see NOTICE): 11 stdlib Python skills
for a long-only opening-range-breakout day, plus `trader-record` and `trader-desk`. The fork adds a Massive data
layer (`mjonir/`), honest measurement (costs, intervals, a random-entry control) and a forward record with a money
gate. Plan and chunk status: README.md. Daily routine: docs/RUNBOOK.md. Reviews: docs/reviews/.

## Principles
- P2: every check has three outcomes, pass / fail / unverified. Never two. Could-not-ask is unverified, never 0.
- P7: records are append-only (`record/*.jsonl` opened with mode `a` only; never rewrite a line).
- P9: one clock, `mjonir.calendar.today_et()` / `now_et()`. No other `date.today()` in `mjonir/`.
- P10: assert non-empty inputs; an empty bar list raises, it is never scored.
- P11: always send the max `limit` (50000 on aggs); a `next_url` past the page cap or a count mismatch is a refusal,
  never a partial answer.
- P12: Python computes every number; the model narrates JSON keys and never does arithmetic in prose.

## Rules
- No U+2014 em dash in any file outside `tests/fixtures/` (tests/test_repo.py enforces it).
- Python 3.8 syntax inside `trader-*/` (no `zoneinfo`, no `list[`/`dict[`/`tuple[`, no `match`). `mjonir/` may use 3.12.
- Stdlib only in `trader-*/` and `mjonir/`.
- Always run from the repo root: every script resolves `trader/` relative to the cwd. Never run from `~/Odyssey`.
- Never print or log the API key; redact by name and by value. The key lives in `~/Infinit/.env`; never create
  `<repo>/.env` with a key (a local plugin install copies gitignored files into the plugin cache).
  `python3 -m mjonir.bridge status` names the variable that holds it and warns on a key in `<repo>/.env`.
- Data: `--source massive` (or `export TRADER_SOURCE=massive`) on scan, entry, exit, timemachine, alerts,
  news; the default stays Yahoo. `python3 -m mjonir.bridge <verb>` writes the same Yahoo-shaped files for
  `--offline` replays. The test suite ignores a local `trader/calendar.json` and `TRADER_SOURCE`.
- The box clock is Mountain; print ET via `TZ=America/New_York date` or the scripts' own output.
- Never write under `~/Odyssey`, `~/Kalex` or `~/Infinit`; their stores are read-only inputs (`?mode=ro`).
- `git add <explicit paths>`, never `-A` or `.`; never force-push; never amend a pushed commit.
- Tests: `python3 -m unittest discover -s tests` from the repo root.
- Never promise profit in README, SKILL.md or verdict text.

## Hazards
1. Mountain box clock: every `now` via `mjonir.calendar.now_et()`; `--now` pins replays.
2. Massive aggs and the Kalex store carry 04:00-19:55 rows; filter RTH per session; `regularMarketVolume` is RTH only.
3. Early closes are 42 bars, not 78; load the calendar overlay before an early-close replay.
4. The 15:55 bar close is not the official close; EOD exits and scoring use the daily bar `c`.
5. Snapshot clears at 03:30 ET; premarket prints are withheld; `lastTrade.t` is ns, `min.t` is ms.
6. The forming bar is live only, labelled, never cached.
7. `next_url` past 50 pages or a count mismatch is a refusal; `limit=50000` on every aggs request.
8. Flat files are unadjusted, Kalex is adjusted as of 2026-07-15; one chart file, one source.
9. Non-session dates are refused with the reason.
10. Pace 1,200 req/min, at most 8 threads; back off on 429.
11. The key never appears in `trader/`, fixtures, logs or error text.
12. The local plugin install reads skills live from this working tree (the checked-out branch loads at next session start or
    `/reload-plugins`; `plugin update` is a no-op); its cache snapshot also copies gitignored files. See docs/reviews/chunk0.md.
13. Upstream test pins bind every change; the Massive branch runs only under `--source massive` or `TRADER_SOURCE=massive`.
14. `trader/` is cwd-relative: `cd` to the repo root first.
15. No options endpoints, no `I:*` indices, no Benzinga: say so, never try.
