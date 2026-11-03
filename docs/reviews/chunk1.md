# Chunk 1 review: the Massive data layer and `--source massive`

Builder: Opus (claude-opus-5-5). Written Mon 2026-11-02 23:59 EST. Branch `feat/c1-data`, worktree
`.claude/worktrees/c1-data`, off `main` = `86b41f7`. Market closed throughout.

## 1. Commits

| commit | hash | on origin |
| --- | --- | --- |
| 1a, the `mjonir/` package, its tests, nine recorded fixtures | `4d4ca5f` | yes |
| 1b, the bridge, the wiring, the overlay, the docs, the replay | `5531f77` | yes |
| this review | the commit that adds this file; see `git log` | pushed with it |

Explicit `git add` paths only; no force-push, no amend. Each message ends with both trailers (the
brief's `Claude Fable 5.1` line and the harness's `Claude Opus 5.5` line), as chunk 0 did.

## 2. Tests

| tree | result | runtime |
| --- | --- | --- |
| `main` (`86b41f7`), clean tree | 315 OK | 7.1 s |
| after 1a | 399 OK (+84) | 7.3 s |
| after 1b | 422 OK (+23) | 8.6 s |

Finding: in the MAIN checkout, with this worktree living under `.claude/worktrees/`, `main`'s own suite
fails 2 tests (`test_no_em_dashes...` and `test_no_v1_only_skill...`): `every_text_file()` walked into
the worktree's copy of the fixtures and of `test_repo.py`. 1b makes that walk skip the local-only root
folders (`LOCAL_ONLY`: `.claude`, `.env`, `.pytest_cache`, `trader`), which also keeps a local
`trader/data/news/*.json` (headline text may carry U+2014) from failing the em-dash pin.

New test files: `test_mjonir_config`, `test_mjonir_massive`, `test_mjonir_calendar`, `test_mjonir_shape`
(round trips through `scan.parse_chart`, `scan.parse_spark`, `scan.load_offline` folder and bundle,
`entry.parse_chart` then `entry.evaluate`, exit's ATR reader, `tm.chart_result`/`parse_bars`/
`full_sessions` at 78 and 42 bars, `alerts.parse_yahoo`, `news.parse_chart`), `test_mjonir_universe`,
`test_mjonir_stores` (synthetic Kalex-schema WAL store with extended-hours rows and a NULL `vw`, read
RTH-only, writes raising, bytes unchanged; a 3-row flat file folded to 5m; the cache's complete-session
rule; the chunk 2 interfaces), `test_mjonir_fixtures` (no 20+ character mixed-case-and-digit token in any
fixture, nor the configured key), `test_source_wiring` (each script under `--source massive` equals its
`--offline` run; TRADER_SOURCE; the calendar overlay), `test_bridge_cli` (every verb, exit codes 0/1/2).
All offline; `tests/_mj.py` points the cache at a temp folder and the Kalex and flat-file paths at
nonexistent ones, so no test opens a real store.

## 3. The replay (full write-up: docs/reviews/replay-tsla-2026-10-19.md)

```text
== 1. entry.py check TSLA, Massive replay vs upstream's Yahoo fixture
--now 10:15: status massive=triggered/open yahoo=triggered/open (exit 0/0)
  opening range high 362.18 vs 362.18 (delta +0.00), low 354.47 vs 354.47 (delta +0.00), bars 3 vs 3
  trigger 10:15 AM bar 8 (10:10) at 364.18 vs 10:15 AM bar 8 (10:10) at 364.18: price delta +0.00
--now 10:12: status massive=waiting/open yahoo=waiting/open (exit 1/1)
  opening range high 362.18 vs 362.18 (delta +0.00), low 354.47 vs 354.47 (delta +0.00), bars 3 vs 3
--now 09:44: status massive=waiting/forming yahoo=waiting/forming (exit 1/1)
  opening range high 362.18 vs 362.18 (delta +0.00), low 354.47 vs 354.47 (delta +0.00), bars 2 vs 2
  bar by bar, the 15 complete bars both files hold (09:30 to 10:40):
   09:30  close 359.1400 vs 359.1800 (-0.0400)  volume   2000912 vs   3080684 (-35.05%)
   09:35  close 358.2700 vs 358.2700 (+0.0000)  volume    964918 vs    964899 (+0.00%)
   09:40  close 360.3850 vs 360.3850 (-0.0000)  volume    931228 vs    931253 (-0.00%)
   09:45  close 361.4500 vs 361.4500 (-0.0000)  volume    794904 vs    794838 (+0.01%)
   09:50  close 361.0694 vs 361.0694 (+0.0000)  volume   1207232 vs   1207272 (-0.00%)
   09:55  close 361.9250 vs 361.9250 (+0.0000)  volume    805722 vs    805723 (-0.00%)
   10:00  close 361.4685 vs 361.4685 (-0.0000)  volume    617662 vs    617820 (-0.03%)
   10:05  close 361.6800 vs 361.6800 (+0.0000)  volume    559030 vs    558955 (+0.01%)
   10:10  close 364.1760 vs 364.1760 (+0.0000)  volume   1000051 vs   1000057 (-0.00%)
   10:15  close 365.0450 vs 365.0450 (-0.0000)  volume    982319 vs    982318 (+0.00%)
   10:20  close 365.7500 vs 365.7500 (+0.0000)  volume    739146 vs    739146 (+0.00%)
   10:25  close 365.9000 vs 365.8500 (+0.0500)  volume    748974 vs    748942 (+0.00%)
   10:30  close 365.7500 vs 365.7500 (+0.0000)  volume    553697 vs  13232032 (-95.82%)
   10:35  close 365.6950 vs 365.6950 (-0.0000)  volume    512070 vs    512101 (-0.01%)
   10:40  close 366.1050 vs 366.1050 (-0.0000)  volume    594798 vs    594767 (+0.01%)
  bars within 3% on volume: 13 of 15

== 2. scan.py orb --now 10:15 --min-price 0, the 234 names
  requested  massive  232  yahoo  234
  fetched    massive  232  yahoo  233
  unusable   massive    1  yahoo    2
  scanned    massive  231  yahoo  231
  candidates massive   95  yahoo   95
  hits       massive   41  yahoo   42
  overlap: 40 of upstream's 42 hits (95.2%); union 43, Jaccard 93.0%
  of the 40 common hits: 35 on the same bar with the same range high (to the cent)
   AAPL  massive bar 6 high 344.75 close 345.48 | yahoo bar 6 high 344.75 close 345.51
   AMGN  massive bar 7 high 433.13 close 434.08 | yahoo bar 7 high 433.14 close 434.08
   CDNS  massive bar 3 high 324.80 close 326.76 | yahoo bar 3 high 324.80 close 326.74
   CLSK  massive bar 3 high 8.79 close 8.80 | yahoo bar 3 high 8.75 close 8.81
   ELV   massive bar 4 high 432.50 close 434.80 | yahoo bar 4 high 432.49 close 434.80
   LRCX  massive bar 3 high 276.84 close 277.50 | yahoo bar 3 high 276.84 close 277.42
   MPC   massive bar 4 high 487.62 close 492.49 | yahoo bar 4 high 487.62 close 492.48
   MSFT  massive bar 8 high 532.65 close 534.14 | yahoo bar 8 high 532.63 close 534.15
   PNC   massive bar 8 high 218.00 close 218.30 | yahoo bar 8 high 217.99 close 218.30
   PSX   massive bar 4 high 298.00 close 299.00 | yahoo bar 4 high 298.00 close 299.01
  DASH  hit in massive range high 189.8645 (massive 189.8645); deciding bar 10:10 close massive 190.1700, yahoo 189.7400: +30.5 and -12.4 cents from the high, the vendors 43.0 cents apart
  DLTR  hit in yahoo   range high 124.8200 (massive 124.8200); deciding bar 10:05 close massive 124.7600, yahoo 124.8700: -6.0 and +5.0 cents from the high, the vendors 11.0 cents apart
  VRTX  hit in yahoo   range high 504.0200 (massive 504.0200); deciding bar 10:10 close massive 503.8750, yahoo 504.1200: -14.5 and +10.0 cents from the high, the vendors 24.5 cents apart

== 3. timemachine.py run --plan plan-tsla.json --now 10:15 (Monte Carlo decimals not compared)
  pool_sessions 59 vs 59 (delta +0), pool 2026-07-27..2026-10-16 vs 2026-07-27..2026-10-16
  history triggered 33 vs 33 (delta +0); target 12 vs 13, stop 16 vs 15, close 5 vs 5; avg R -0.123 vs -0.062
  same trigger dates: True
   2026-08-06 massive ('10:00 AM', 320.26, 317.48, 323.04, 'stop', -1.0) | yahoo ('10:00 AM', 320.23, 317.48, 322.98, 'target', 1.0)
   2026-09-24 massive ('10:00 AM', 378.91, 377.43, 380.39, 'stop', -1.0) | yahoo ('10:00 AM', 378.89, 377.43, 380.35, 'stop', -1.0)
   2026-10-13 massive ('10:45 AM', 375.47, 373.1, 377.84, 'stop', -1.0) | yahoo ('10:45 AM', 375.52, 373.09, 377.95, 'stop', -1.0)
  largest entry difference on a common trigger: $0.05
  data: massive range 60d, short sessions left out []; yahoo []
```

Verdicts: opening range, trigger bar and price, `10:12` waiting, `09:44` forming, scan overlap (95.2
percent), `pool_sessions` and `triggered`: pass. Bar volumes within 3 percent: 13 of 15 bars, the two
misses are Yahoo's (09:30: Yahoo 54 percent above the whole consolidated tape; Massive equals the tape
minus the condition-16 official-open duplicate; 10:30: Yahoo 13.2M where the tape holds 553,401). The
scan's three differences are NOT "a cent at the range high": the range highs agree to the cent, the
deciding bar's close differs by 11 to 43 cents; in each case Massive's close is a print on the tape and
Yahoo's matches none of the window's last prints. The time machine's one flipped outcome (2026-08-06)
is a 3-cent entry difference moving the 1R target by 6 cents.

## 4. Universe and the daily scan

`python3 -m mjonir.bridge universe` (as of 2026-11-02, floors $5 and $20M from the code defaults; no
`trader/config.json` here): 25 requests, 19.7 s.

| funnel | count |
| --- | --- |
| reference rows (CS + ADRC, two verified walks) | 5,700 |
| not a plain ticker | 0 |
| no print on 2026-11-02 | 153 |
| price under $5 | 1,719 |
| ADV$ under $20M (20 sessions, a missing day counts 0) | 1,815 |
| kept | 2,013 |

`python3 trader-scanner/scan.py daily --source massive --universe trader/universe.txt`: exit 0, 40.9 s
cold (65 grouped-daily sessions, 46 not yet cached, plus the split list), as of the 2026-11-02 close:
2,013 requested, 2,013 fetched, 528 under the liquidity filter, 4 under 30 days, 1,481 scanned, 652 hits.
`scan.py universe --source massive` (the same rule through scan's own writer) answered 2,013 in 5.1 s
on the warm cache. For comparison only: Odyssey measured 2,238 CS+ADRC names on 2026-10-14 under its own
rule (ADV over a name's own prints, plus its store union); the two definitions differ.

## 5. `bridge probe` and `bridge status` (key never printed)

```text
$ python3 -m mjonir.bridge probe
Massive key: AUTHENTICATED (one reference row answered).
Not entitled: options, indices (I:) and Benzinga are not entitled on this key: never tried.
(exit 0)
$ python3 -m mjonir.bridge status
Massive key: present in MASSIVE_API_KEY; probe AUTHENTICATED.
Not entitled: options, indices (I:) and Benzinga are not entitled on this key: never tried.
Calendar: trader/calendar.json, covers 2026, 2027, 2028, vendor list through 2027-09-06.
Cache: 124163 bars, 234 symbols, 64 grouped days.
Universe: 2013 symbols in trader/universe.txt.
Kalex 5m: ok, 777 symbols, /home/axis/Kalex/data/intraday/intraday_5m.sqlite3.
Flat files: ok, 1402 days 2021-01-04 to 2026-08-04 (unadjusted).
(exit 0)
```

Other live runs: `bridge calendar` wrote 29 holidays and 5 early closes; `entry.py check TSLA --now
"2028-01-05 10:00" --offline <the reel moved to that date>` no longer prints the 2026-and-2027 warning
(with `TRADER_CALENDAR=/dev/null` it does). `entry.py watch TSLA --source massive --now "2026-10-30
09:50"` replayed in 0.62 s and triggered on the 9:50 bar at 394.12. `timemachine.py run --source massive`
live: 60d, pool 59, 33 triggers (0.8 s warm); `--years 2`: 500 sessions, pool 494, 283 triggers (10.4 s
cold). `bridge history --source kalex` (2026-05-01 to 2026-07-15, 51 sessions, 0.1 s) and `--source
flatfile` (2026-07-27 to 2026-08-04, 7 sessions, 15.4 s): the flat-file fold equals the API bar for bar
(546 bars, same stamps, zero close difference). `alerts.py quote --source massive` and `news.py --source
massive` answered (after the close: the session close stands, the 19:59 post-market print is withheld
and named).

## 6. `git diff --stat main -- 'trader-*'`

```text
 trader-alerts/SKILL.md            | 10 ++++++++
 trader-alerts/alerts.py           | 44 ++++++++++++++++++++++++++++++++-
 trader-entry/SKILL.md             | 12 +++++++++
 trader-entry/entry.py             | 44 ++++++++++++++++++++++++++++++---
 trader-exit/SKILL.md              |  8 ++++++
 trader-exit/exit.py               | 36 +++++++++++++++++++++++++++
 trader-news/SKILL.md              | 10 ++++++++
 trader-news/news.py               | 52 ++++++++++++++++++++++++++++++++++++++-
 trader-risk/SKILL.md              |  8 ++++++
 trader-risk/check.py              | 17 +++++++++++++
 trader-scanner/SKILL.md           | 14 +++++++++++
 trader-scanner/scan.py            | 49 ++++++++++++++++++++++++++++++++----
 trader-timemachine/SKILL.md       | 12 +++++++++
 trader-timemachine/timemachine.py | 36 ++++++++++++++++++++++++++-
 14 files changed, 341 insertions(+), 11 deletions(-)
```

(The brief's pathspec `'trader-*/'` with the trailing slash matches nothing in git; `'trader-*'` does.)
Every script carries the same 12-line `_calendar_overlay(g)` plus one call line (pinned identical by a
test) and, except `check.py`, the 10-line `_mjonir()` shim, so about 27 lines are fixed cost. Over 40:
`news.py` (52) adds three small functions (the snapshot moves, Massive headlines, and their offline
reader) because news has no single HTTP helper to branch above; `scan.py` (49) has five branch points
(fetch_spark, universe twice, the stage-1 refusal, stage 2) plus two flags. Upstream helpers patched by
upstream's tests (`scan.http_get`, `entry._open_url`, `tm._get`, `alerts._urlopen`) are untouched and the
Massive branch sits above them.

## 7. Kalex store sha256

| when (UTC) | sha256 of intraday_5m.sqlite3 |
| --- | --- |
| before any read, 2026-11-03T04:16:25Z | `2f5b1750164bd08db49bda4c9a2b2d4d1f24a3b32d5ec055ec1feef0bb39f45b` |
| after the replay reads, 04:52:12Z | `2f5b1750164bd08db49bda4c9a2b2d4d1f24a3b32d5ec055ec1feef0bb39f45b` |
| final, after the kalex history and status, 04:57:26Z and later | `2f5b1750164bd08db49bda4c9a2b2d4d1f24a3b32d5ec055ec1feef0bb39f45b` |

Size and mtime unchanged (10,739,052,544 bytes, 2026-07-15). The pre-existing `-shm` sidecar's mtime
moved: SQLite readers of a WAL store touch its shared-memory index, the limit Odyssey's `ro_connect`
documents. No write was accepted (the tests pin that on a synthetic store). No Odyssey store was opened.

## 8. Owed, uncertain, and decisions for the lead

- OWED to the lead, market closed: the LIVE `watch` timing (bar lines within seconds of each 5-minute
  close). The replay path is measured; the live clock path is not.
- Acceptance lines not met as written, both explained in section 3: bar volumes within 3 percent (2 of
  15 bars, Yahoo's), and "every scan difference a cent at the range high" (vendor bar closes 11 to 43
  cents apart).
- `tests/_load.py` (an upstream test helper) changed in 1a: it sets `TRADER_CALENDAR=/dev/null` and drops
  `TRADER_SOURCE`, so a local `trader/calendar.json` or an exported source never reaches upstream's tests
  (test_alerts pins the exact seed lists; test_entry and test_alerts pin `calendar_known` False for 2028).
  Without it, the first `bridge calendar` in the repo root breaks those upstream pins.
- `tests/test_repo.py` walk change (section 2), and the coordinator's two `.gitignore` lines, in 1b.
- Calendar coverage of 2028: the vendor lists holidays only through 2027-09-06, so `build_calendar_doc`
  fills the year after the vendor's last listed year from the NYSE rules (`basis: rule`, the rules
  reproduce upstream's 2026 and 2027 seeds exactly) and counts it as covered. That is what removes the
  2028 warning. A one-off closure cannot be known; the doc's note says to check nyse.com.
- The key travels as `Authorization: Bearer` (tested live), never in a URL, a change from Odyssey's
  `apiKey=` query string. Redaction by name and by value stays on every error path (tested with a symbol
  holding a space, through a leaky opener and through the real urllib). `grep -rn "apiKey\|api_key"
  mjonir/` shows only `config.py` and the client's `C.api_key()` call.
- Reference-walk sanity floors are mine: CS 3,000 rows, ADRC 100 (measured: 5,700 together).
- Cosmetic, left to keep the diffs small: some human lines still say Yahoo under `--source massive`
  (scan's "Yahoo spark" headers, entry's watchlist footer, alerts' footer). The JSON `source` fields and
  entry's header are right. `entry.json` says `yahoo` when a bridged file is replayed with `--offline`
  and no `--source massive` (the flag sets the label; the file's own `meta.mjonir.source` says massive).
- Massive volumes are fractional; documents round them to whole shares.
- Before the open, a quote needs the previous session's close: one daily request per ticker then (the
  03:30 ET snapshot clear empties `day`).
- No endpoint answered 403; nothing not entitled was tried. The two other live sessions in `~/Odyssey`
  were not touched; Odyssey sources were read only. The throwaway fixture recorder lived in the
  scratchpad and was deleted before 1a.
- The worktree's `trader/` (calendar, universe, cache with 124,163 bars, replay files) is local and
  gitignored; the main checkout has none until `bridge calendar` and `bridge universe` run there.
