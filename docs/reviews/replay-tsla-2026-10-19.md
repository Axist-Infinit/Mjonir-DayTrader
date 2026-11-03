# Replay: TSLA, Monday 2026-10-19, Massive against upstream's Yahoo reel

Chunk 1b acceptance. Run on Mon 2026-11-02 between 23:48 and 00:10 ET (market closed), branch
`feat/c1-data`, from the worktree root, with the key from `~/Infinit/.env`. Every number below is printed
by Python (the comparison script at the end); nothing was computed by hand.

## Commands

```bash
python3 -m mjonir.bridge intraday TSLA --day 2026-10-19 --out trader/data/replay/2026-10-19/
python3 trader-entry/entry.py check TSLA --offline trader/data/replay/2026-10-19 --now "2026-10-19 10:15" --json
python3 trader-entry/entry.py check TSLA --offline trader/data/replay/2026-10-19 --now "2026-10-19 10:12" --json
python3 trader-entry/entry.py check TSLA --offline trader/data/replay/2026-10-19 --now "2026-10-19 09:44" --json
python3 -m mjonir.bridge intraday <the 234 names of tests/fixtures/trader-scanner/wall5m-2026-10-19.json.gz> \
    --day 2026-10-19 --bundle --out trader/data/replay/2026-10-19/          # 235 requests, 12.6 s
python3 trader-scanner/scan.py orb --offline trader/data/replay/2026-10-19/wall5m-2026-10-19.json.gz \
    --now "2026-10-19 10:15" --min-price 0 --json
python3 -m mjonir.bridge history TSLA --from 2026-07-27 --to 2026-10-19 --source api   # 60 sessions, 4,680 bars
python3 trader-timemachine/timemachine.py run --plan tests/fixtures/trader-budget/plan-tsla.json \
    --offline trader/data/history --now "2026-10-19 10:15" --json
python3 compare_replay.py          # the script at the end of this doc, run from the repo root
```

## The comparison, as printed

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

## Verdict per acceptance item

| item | asked | measured | state |
| --- | --- | --- | --- |
| opening range | 362.18 / 354.47 within $0.02 | 362.18 / 354.47, delta 0.00 / 0.00 | pass |
| trigger | 10:10 bar, index 8, 364.18 within $0.02 | 10:10 bar, index 8, 364.18, delta 0.00 | pass |
| `--now 10:12` | waiting | waiting (exit 1), same reason line as upstream | pass |
| `--now 09:44` | range forming | waiting / forming, 2 of 3 range bars | pass |
| bars (restated in review 1c) | closes within $0.05 on 15 of 15 bars, volume within 0.1 percent on 13 of 15, each exception listed with its tape evidence | closes: 15 of 15 within $0.05 (13 to the cent; 09:30 $0.04, 10:25 $0.05). Volume: 13 of 15 within 0.03 percent; exceptions 09:30 (minus 35 percent) and 10:30 (minus 96 percent), tape evidence below | pass as restated (the first wording, "volumes within 3 percent", fails on those two bars) |
| scan hit set | overlap at least 95 percent | 40 of upstream's 42 hits (95.2 percent); Jaccard 93.0 percent | pass |
| scan differences (restated in review 1c) | hit-set overlap at least 95 percent with every difference traced to the deciding bar's close and its cents from the range high | DASH, DLTR, VRTX each traced below: range highs equal to the cent, deciding closes 11 to 43 cents apart | pass as restated (the first wording, "each a cent at the range high", does not describe them) |
| time machine | pool_sessions within 1, triggered within 1 | 59 vs 59, 33 vs 33 | pass |

## The explanations

**The two volume exceptions: Massive's bars are traceable to Massive's consolidated tape; Yahoo's basis
is not established.** The only reference here is Massive's own trade tape (`/v3/trades/TSLA`,
read-only, the same session), so this traces Massive's bars to their source; it does not show which
vendor is right.

- 09:30 bar: the tape holds 2,208,736 shares in 52,195 prints. One of them is the Nasdaq official-open
  report (condition 16, 208,896 shares), a duplicate of the opening cross (condition 17, 208,895 shares,
  same millisecond). Without the duplicate the tape sums to 1,999,840 shares and Massive's bar says
  2,000,912: traceable. Yahoo's 3,080,684 is 54 percent above that whole tape; what Yahoo counted is not
  established.
- 10:30 bar: the tape holds 553,401 shares in 21,257 prints, the largest 3,732 shares. Massive's bar says
  553,697: traceable. Yahoo's 13,232,032 is not on Massive's tape; its basis is not established.
- The other 13 bars agree within 0.03 percent; closes agree to the cent on 13 of 15 bars (10:25 differs
  by $0.05, 9:30 by $0.04).

**The three scan differences are vendor bar closes within 0.25 percent of the range high.** The range
highs agree to the cent on all three (DASH 189.8645, DLTR 124.82, VRTX 504.02). The deciding bar's close
does not. From the tape's last prints before each bar's end:

- DASH, 10:10 bar: Massive closes 190.17, the price of the last 100-share round lot (10:14:58.209);
  after it only odd lots (condition 37) printed, at 190.17 to 190.36. Yahoo's 189.74 is none of the last
  prints. Massive hits (+30.5 cents over the high); Yahoo misses (-12.4 cents).
- DLTR, 10:05 bar: Massive closes 124.76, the last 100-share round lot (10:09:56.519); later prints are
  odd lots (124.76, 124.85) and a derivatively priced odd lot (condition 10, 124.7867). Massive's best
  post-range close is 124.81 on the 10:00 bar, one cent under the 124.82 high. Yahoo's 124.87 is none of
  the last prints. Yahoo hits; Massive misses.
- VRTX, 10:10 bar: Massive closes 503.875 (prints at that price at 10:14:56); the window's last prints
  run 503.44 to 503.96. Yahoo's 504.12 is above every one of them. Yahoo hits; Massive misses
  (-14.5 cents).

So every difference is traced to the deciding bar's close and its cents from the range high: the
vendors disagree on that close by 11 to 43 cents, Massive's close is traceable to a print on Massive's
consolidated tape, and Yahoo's is not among that tape's last prints in the window. Yahoo's basis is not
established; the reference is Massive's own tape, so this does not show which close is right. Ten common hits differ by one to eight cents in
the trigger close or one to four cents in the range high (CLSK); all fire on the same bar.

Counts: Massive built 232 of the 234 names (SQ has no 2026-10-19 bars under that ticker any more,
WBD none either); upstream's file holds SQ as a "no data" answer and WBD with no bars. Both scans use
231 charts; PARA is unusable in both (missing bars; Yahoo's PARA prices are a tenth of Massive's).

**The time machine.** Same 59 pool sessions (2026-07-27 to 2026-10-16), same 33 trigger dates. One
outcome flips: on 2026-08-06 the entry bar closes at 320.26 on Massive and 320.23 on Yahoo; the 1R
target is entry plus the risk, so it lands at 323.04 against 322.98, and the session's high touched
Yahoo's target but not Massive's, then the stop. That one trade moves the history's average from
-0.062 R to -0.123 R. The largest entry difference on a common trigger is $0.05.

## Also run (the other 1b acceptance lines)

- `bridge probe`: AUTHENTICATED, exit 0. `bridge status`: exit 0 (output in docs/reviews/chunk1.md).
- `bridge calendar`: 29 holidays, 5 early closes, covers 2026, 2027, 2028 (2028 from the NYSE rules;
  the vendor lists through 2027-09-06). `entry.py check TSLA --now "2028-01-05 10:00" --offline <the reel
  moved to 2028-01-05>` no longer prints "Holiday list covers 2026 and 2027 only"; with
  `TRADER_CALENDAR=/dev/null` it does.
- `entry.py watch TSLA --source massive --now "2026-10-30 09:50"`: replayed without sleeping (0.62 s),
  opening range 393.46 / 387.52, TRIGGERED on the 9:50 bar at 394.12, exit 0.
- Live `watch` timing (bar lines within seconds of each 5-minute close): owed, to be measured in the
  first live session (the market was closed for this run).

## The comparison script

```python
"""Print the deltas between upstream's Yahoo reel (its fixtures) and the Massive replay of 2026-10-19.
Run from the repo root after the bridge commands in docs/reviews/replay-tsla-2026-10-19.md."""
import datetime as dt
import json
import subprocess
import sys

sys.path.insert(0, "tests")
from _load import load  # noqa: E402

scan = load("trader-scanner", "scan")
entry = load("trader-entry", "entry")
REPLAY = "trader/data/replay/2026-10-19"
YF = "tests/fixtures/trader-entry/TSLA-2026-10-19-5m.json"


def sh(args):
    p = subprocess.run([sys.executable] + args, capture_output=True, text=True)
    return p.returncode, p.stdout


print("== 1. entry.py check TSLA, Massive replay vs upstream's Yahoo fixture")
for now in ("2026-10-19 10:15", "2026-10-19 10:12", "2026-10-19 09:44"):
    rows = []
    for name, src in (("massive", REPLAY), ("yahoo", YF)):
        code, out = sh(["trader-entry/entry.py", "check", "TSLA", "--offline", src, "--now", now, "--json"])
        r = json.loads(out)
        rows.append((name, code, r))
    (_, cm, m), (_, cy, y) = rows
    print("--now %s: status massive=%s/%s yahoo=%s/%s (exit %d/%d)" % (now[11:], m["status"], m["phase"], y["status"],
                                                                     y["phase"], cm, cy))
    om, oy = m["opening_range"], y["opening_range"]
    print("  opening range high %.2f vs %.2f (delta %+.2f), low %.2f vs %.2f (delta %+.2f), bars %d vs %d"
          % (om["high"], oy["high"], om["high"] - oy["high"], om["low"], oy["low"], om["low"] - oy["low"],
             om["bars"], oy["bars"]))
    if m.get("trigger") or y.get("trigger"):
        tm_, ty = m["trigger"], y["trigger"]
        print("  trigger %s bar %s (%s) at %.2f vs %s bar %s (%s) at %.2f: price delta %+.2f"
              % (tm_["time"], tm_["bar_index"], tm_["bar_start"], tm_["price"], ty["time"], ty["bar_index"],
                 ty["bar_start"], ty["price"], tm_["price"] - ty["price"]))
cm_ = entry.parse_chart(open(REPLAY + "/TSLA.json").read(), "TSLA")
cy_ = entry.parse_chart(open(YF).read(), "TSLA")
vm = {b["t"]: b for b in cm_["bars"]}
print("  bar by bar, the 15 complete bars both files hold (09:30 to 10:40):")
worst = []
for b in cy_["bars"]:
    if b["t"] % 300 or b["t"] not in vm or b["t"] >= 1792421100:
        continue
    a = vm[b["t"]]
    pct = 100.0 * (a["v"] / float(b["v"]) - 1) if b["v"] else float("nan")
    worst.append((abs(pct), b["t"]))
    print("   %s  close %.4f vs %.4f (%+.4f)  volume %9d vs %9d (%+.2f%%)" % (
        entry.to_eastern(entry.utc_of(b["t"])).strftime("%H:%M"), a["c"], b["c"], a["c"] - b["c"], a["v"], b["v"], pct))
print("  bars within 3%% on volume: %d of %d" % (sum(1 for p, _ in worst if p <= 3), len(worst)))

print()
print("== 2. scan.py orb --now 10:15 --min-price 0, the 234 names")
code, out = sh(["trader-scanner/scan.py", "orb", "--offline", REPLAY + "/wall5m-2026-10-19.json.gz", "--now",
                "2026-10-19 10:15", "--min-price", "0", "--json", "--no-write"])
m = json.loads(out)
code, out = sh(["trader-scanner/scan.py", "orb", "--offline", "tests/fixtures/trader-scanner/wall5m-2026-10-19.json.gz",
                "--now", "2026-10-19 10:15", "--min-price", "0", "--json", "--no-write"])
y = json.loads(out)
for k in ("requested", "fetched", "unusable", "scanned", "candidates", "hits"):
    print("  %-10s massive %4d  yahoo %4d" % (k, m["counts"][k], y["counts"][k]))
hm, hy = {h["symbol"]: h for h in m["hits"]}, {h["symbol"]: h for h in y["hits"]}
both = set(hm) & set(hy)
print("  overlap: %d of upstream's %d hits (%.1f%%); union %d, Jaccard %.1f%%" % (
    len(both), len(hy), 100.0 * len(both) / len(hy), len(set(hm) | set(hy)), 100.0 * len(both) / len(set(hm) | set(hy))))
same = sum(1 for s in both if (hm[s]["bar_index"], hm[s]["or_high"]) == (hy[s]["bar_index"], hy[s]["or_high"]))
print("  of the %d common hits: %d on the same bar with the same range high (to the cent)" % (len(both), same))
for s in sorted(both):
    if (hm[s]["bar_index"], hm[s]["or_high"], hm[s]["price"]) != (hy[s]["bar_index"], hy[s]["or_high"], hy[s]["price"]):
        print("   %-5s massive bar %d high %.2f close %.2f | yahoo bar %d high %.2f close %.2f" % (
            s, hm[s]["bar_index"], hm[s]["or_high"], hm[s]["price"], hy[s]["bar_index"], hy[s]["or_high"],
            hy[s]["price"]))
md, _ = scan.load_offline(REPLAY + "/wall5m-2026-10-19.json.gz")
yd, _ = scan.load_offline("tests/fixtures/trader-scanner/wall5m-2026-10-19.json.gz")
day, cut = dt.date(2026, 10, 19), dt.datetime(2026, 10, 19, 10, 15)
for s in sorted(set(hm) ^ set(hy)):
    bm, by = scan.session_bars(md[s], day, cut), scan.session_bars(yd[s], day, cut)
    oh = max(b["h"] for b in by[:3])
    ohm = max(b["h"] for b in bm[:3])
    k = max(range(3, len(by)), key=lambda i: max(bm[i]["c"], by[i]["c"]))
    print("  %-5s hit in %-7s range high %.4f (massive %.4f); deciding bar %s close massive %.4f, yahoo %.4f: "
          "%+.1f and %+.1f cents from the high, the vendors %.1f cents apart" % (
              s, "massive" if s in hm else "yahoo", oh, ohm, by[k]["start"].strftime("%H:%M"), bm[k]["c"], by[k]["c"],
              100 * (bm[k]["c"] - ohm), 100 * (by[k]["c"] - oh), 100 * abs(bm[k]["c"] - by[k]["c"])))

print()
print("== 3. timemachine.py run --plan plan-tsla.json --now 10:15 (Monte Carlo decimals not compared)")
args = ["trader-timemachine/timemachine.py", "run", "--plan", "tests/fixtures/trader-budget/plan-tsla.json", "--now",
        "2026-10-19 10:15", "--json"]
m = json.loads(sh(args + ["--offline", "trader/data/history"])[1])
y = json.loads(sh(args + ["--offline", "tests/fixtures/trader-timemachine/TSLA-60d5m.json.gz"])[1])
print("  pool_sessions %d vs %d (delta %+d), pool %s..%s vs %s..%s" % (
    m["mc"]["pool_sessions"], y["mc"]["pool_sessions"], m["mc"]["pool_sessions"] - y["mc"]["pool_sessions"],
    m["mc"]["pool_from"], m["mc"]["pool_to"], y["mc"]["pool_from"], y["mc"]["pool_to"]))
hm, hy = m["history"], y["history"]
print("  history triggered %d vs %d (delta %+d); target %d vs %d, stop %d vs %d, close %d vs %d; avg R %+.3f vs %+.3f"
      % (hm["triggered"], hy["triggered"], hm["triggered"] - hy["triggered"], hm["target"], hy["target"], hm["stop"],
         hy["stop"], hm["close"], hy["close"], hm["avg_R"], hy["avg_R"]))
tm_ = {t["date"]: t for t in hm["trades"]}
ty = {t["date"]: t for t in hy["trades"]}
print("  same trigger dates: %s" % (sorted(tm_) == sorted(ty)))
for d in sorted(set(tm_) | set(ty)):
    a, b = tm_.get(d), ty.get(d)
    if not a or not b or (a["time"], a["outcome"]) != (b["time"], b["outcome"]) or abs(a["entry"] - b["entry"]) > 0.02:
        print("   %s massive %s | yahoo %s" % (d, a and (a["time"], a["entry"], a["stop"], a["target"], a["outcome"], a["R"]),
                                             b and (b["time"], b["entry"], b["stop"], b["target"], b["outcome"], b["R"])))
d_entry = max(abs(tm_[d]["entry"] - ty[d]["entry"]) for d in set(tm_) & set(ty))
print("  largest entry difference on a common trigger: $%.2f" % d_entry)
print("  data: massive range %s, short sessions left out %s; yahoo %s" % (
    m["data"]["range"], m["data"]["short_sessions_left_out"], y["data"]["short_sessions_left_out"]))
```
