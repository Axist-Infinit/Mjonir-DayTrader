#!/usr/bin/env python3
"""Time Machine for trader-timemachine. Standard library only.

Replays a planned day trade before you risk a dollar: the same rule on every
past session in the data, net of costs, beside a random-entry control and a
buy-any-morning-strength baseline; plus 10,000 simulated runs of the rest of
the session from your entry (a shape diagnostic, never the verdict).

    python3 timemachine.py run                          # trader/plan.json, 10,000 replays, seed 19
    python3 timemachine.py run --write                  # also save trader/timemachine.json
    python3 timemachine.py run --until 15:55            # stop each replay at your flat-by time
    python3 timemachine.py run --seed 7 --replays 20000 --json
    python3 timemachine.py run --source massive --years 2 --control-draws 3
    python3 timemachine.py run --no-costs --gap-fill stop   # upstream's gross mechanics
    python3 timemachine.py run --symbol TSLA --date 2026-10-19 --entry 364.18 \\
        --stop 358.32 --target 370.04 --entry-time "10:15 AM"
    python3 timemachine.py chart                        # ASCII fan chart of the replays
    python3 timemachine.py chart --from trader/timemachine.json

How the replays work (the reel's sim.py, same algorithm, same random draws):
  1. Fetch 60 days of 5-minute bars (Yahoo v8 chart, range=60d interval=5m;
     one request). Keep only FULL sessions before the plan's date: 78 bars,
     9:30 to 4:00 New York time. Half days, gaps and today are left out.
  2. The pool: for every bar slot 1..77 of the day, each past session's bar as
     ratios to the previous bar's close: (open, high, low, close) / prev close.
  3. One replay starts at the entry price and walks the rest of the session.
     For each bar i it picks a slot j = i + randint(-window, window), kept in
     1..77, then one past bar from pool[j] (random.choice), and scales it to
     the current price. The stop is checked before the target in every bar,
     so a bar that touches both counts as the stop (the conservative call).
  4. Outcomes: "target" or "stop" (whichever was touched first), or "neither"
     when the trade is still open at --until (default 16:00, the close, or
     13:00 on an NYSE early-close day).
     "green" = target first, or above the entry at --until (below for a sell).
     R = the target's R at the target, -1 at the stop, otherwise
     (price at --until - entry) / risk. A bar that OPENS through the stop
     fills at its open (--gap-fill open, the default: worse than -1R);
     --gap-fill stop is upstream's exact -1R. Every outcome, here and in the
     history, comes from mjonir/outcomes.py (touch, score_trade).
  5. The price at --until: median and the 5th to 95th percentile of all
     replays (pct(a, q) = sorted a at index int(q * n)). The fan chart uses a
     second run of 2,000 paths with the same seed. The histogram has 24 bins
     between the 1st and 99th percentile.
  6. History: the plan's own rule (an opening-range breakout with the same
     opening range, stop rule and target R) re-run on every past session in
     the data: the full ones and the 1:00 p.m. early closes (42 bars, scored
     to bar 41, the flat-by moved up three hours as trader-exit does); other
     short sessions are dropped and listed. First close beyond the range =
     entry, at the UNROUNDED close (rounded only for display); the stop by the
     rule (a cent price, away from the entry); the target = entry + R x risk.
     Each trade's R is charged its own round trip once (mjonir/costs.py; the
     plan's cost card, or the defaults with ADV unverified): net R = gross R -
     cost_r. Also: the decided count with its Wilson interval, the "fragile"
     decisions (the deciding touch cleared its level by under 0.05 R), a
     one-tick sensitivity (the entry 1 cent higher and lower: how many
     outcomes flip), the net average by year, the random-entry control
     (--control-draws K a session, mjonir/control.py) and the baseline (buy the
     close of the last opening-range bar on every session). No average is
     printed without its 95 % bootstrap interval and n.

The verdict reads the HISTORY, net of costs (mjonir.stats.verdict_history),
on the money gate's own statistic: the 95 % bootstrap interval of the net R
over every fire, against 0. Under 40 fires it cannot judge; an interval holding
0 is not distinguishable from zero; wholly under 0 fails, wholly over 0 passes
("A past sample is not a forward result."). For a plan with a target the
decided rate (target or stop) and its Wilson interval follow as a diagnostic,
against the net break-even (1 + c) / (target R + 1) where c is the history's
own mean round trip in R; it never sets the state. verdict_control reads the
paired net delta against the random entry, floored at 40 paired sessions. The Monte Carlo block is a SHAPE diagnostic only (an
unconditional per-slot bootstrap, not conditioned on the breakout, volatility
regimes mixed): mc_shape_line() states its target-first and stop-first shares,
with a note when more than 40 % hit neither, and no verdict reads it.

5-minute bars only: Yahoo keeps 60 days of 5-min bars but only about 7 days of
1-min bars, too few sessions for a fair pool. The run refuses with a plain
message when there are fewer than 20 full sessions or the entry bar is not in
the data. Same plan, same data and same --seed give the same numbers on any
machine. A simulation built from the stock's own recent bars is not a
prediction: earnings, news and halts can do what the last 60 days never did.

Data: https://query2.finance.yahoo.com/v8/finance/chart/<T>?range=60d&interval=5m
(unofficial and free, can lag; falls back to query1 on 429 or 5xx).
--offline FILE reads a saved chart JSON (.json or .json.gz) instead.
--source massive: --sessions N (default 60) or --years N of complete 5-minute
bars from mjonir.bars.bars_5m, ONE store per run (Kalex, the API or its cache);
data.source and the adjustment basis come from that call, never from the flag,
and a Yahoo history and a Massive one are never pooled. ADV$ for the slippage
tier comes from Massive under --source massive; otherwise it is unverified (the
most expensive tier). --no-costs turns costs off.
The entry window: --no-entries-after HH:MM (default the config's
no_entries_after, else 15:30; on a 1:00 p.m. early close it moves up three
hours, as trader-entry moves it) caps the bars the history's rule may fire on
and the random-entry control's entry bars, as the entry timer and the
forward record do; 16:00 is upstream's (no cap). --until is the last bar each
trade is scored to (default the 16:00 close); give the plan's flat-by
(--until 15:55) to score the way the plan exits; a later --until prints a
notice.
Times are New York (ET) wall-clock; --now "2026-10-19 10:15" pins the clock.
"""

import argparse
import datetime
import gzip
import importlib
import json
import math
import os
import random
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (compatible; day-trader-skill/2.0; +https://github.com/Jakeschincariol/day-trader-skill)"
PAUSE = 0.5          # seconds between requests: be polite to free endpoints
BACKOFF = 5.0        # seconds to wait once after a 429
HOSTS = ("query2", "query1")
INTERVAL = 300       # 5-minute bars, in seconds
SESSION_BARS = 78    # 9:30 to 16:00 in 5-minute bars
OPEN_MIN = 9 * 60 + 30
CLOSE_MIN = 16 * 60
MIN_SESSIONS = 20
SAMPLE_PATHS = 160
BAND_PATHS = 2000
BAND_Q = (0.05, 0.25, 0.5, 0.75, 0.95)
HIST_BINS = 24
NOTE_GAP = 0.05      # the average-R note's threshold (target share minus break-even share)
MANY_NEITHER = 0.40
TICK = 0.01          # the one-tick sensitivity
SHAPE = ("Shape diagnostic (unconditional per-slot bootstrap, not conditioned on the breakout, "
         "vol regimes mixed)")
EPOCH = datetime.datetime(1970, 1, 1)
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
NYSE_EARLY_CLOSE = {  # 1:00 p.m. ET, from https://www.nyse.com/markets/hours-calendars (read 2026-10-13)
    "2026-11-27": "day after Thanksgiving",
    "2026-12-24": "Christmas Eve",
    "2027-11-26": "day after Thanksgiving",
}
EARLY_MIN = 13 * 60
EARLY_BARS = 42      # 9:30 to 13:00


class TMError(Exception):
    pass


def _calendar_overlay(g):
    """Extend the lists above from trader/calendar.json or TRADER_CALENDAR (`python3 -m mjonir.bridge calendar`)."""
    try:
        with open(os.environ.get("TRADER_CALENDAR") or "trader/calendar.json", encoding="utf-8") as fh:
            doc = json.load(fh)
        years = set(int(y) for y in doc.get("covered_years") or ())
        g.get("NYSE_HOLIDAYS", {}).update(doc.get("holidays") or {})
        g.get("NYSE_EARLY_CLOSE", {}).update(doc.get("early_closes") or {})
    except (OSError, ValueError, TypeError, AttributeError):
        return  # no calendar file (or not one): the seed lists above stand
    if "CALENDAR_YEARS" in g:
        g["CALENDAR_YEARS"] = tuple(sorted(set(g["CALENDAR_YEARS"]) | years))


_calendar_overlay(globals())


def _mjonir():
    """--source massive: the Mjonir data layer (mjonir/ beside the skill folders, or MJONIR_ROOT)."""
    root = os.environ.get("MJONIR_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        from mjonir import yahoo_shape
    except ImportError as e:
        raise TMError("--source massive needs the mjonir package (Python 3.9+) at %s: %s" % (root, e))
    return yahoo_shape.adapter(TMError)


def _measure(name):
    """mjonir.<name> (stats, costs, outcomes, control): the one definition every script uses, on every run
    whatever --source is (Python 3.8 syntax, stdlib only)."""
    root = os.environ.get("MJONIR_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        return importlib.import_module("mjonir." + name)
    except ImportError as e:
        raise TMError("the measurement layer (mjonir/%s.py) is missing at %s: %s" % (name, root, e))


# ---------------------------------------------------------------- time (copied from trader-alerts)

def _nth_sunday(year, month, n):
    d = datetime.date(year, month, 1)
    d += datetime.timedelta(days=(6 - d.weekday()) % 7)
    return d + datetime.timedelta(weeks=n - 1)


def eastern_offset(utc):
    """Hours from UTC for New York: -4 in daylight time, -5 otherwise.
    DST runs from 2:00 a.m. on the second Sunday of March to 2:00 a.m. on the
    first Sunday of November (US rule since 2007)."""
    y = utc.year
    start = datetime.datetime.combine(_nth_sunday(y, 3, 2), datetime.time(7, 0))   # 2:00 EST
    end = datetime.datetime.combine(_nth_sunday(y, 11, 1), datetime.time(6, 0))    # 2:00 EDT
    naive = utc.replace(tzinfo=None)
    return -4 if start <= naive < end else -5


def to_eastern(utc):
    return utc.replace(tzinfo=None) + datetime.timedelta(hours=eastern_offset(utc))


def eastern_to_utc(local):
    for off in (-4, -5):
        utc = local - datetime.timedelta(hours=off)
        if eastern_offset(utc) == off:
            return utc
    return local + datetime.timedelta(hours=5)


def parse_now(text):
    """ISO time -> naive UTC. A time without an offset is taken as New York time."""
    if not text:
        return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0, tzinfo=None)
    t = text.strip().replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(t)
    except ValueError:
        raise TMError("--now wants a time like \"2026-10-19 10:15\" (New York) or ...Z (UTC)")
    if dt.tzinfo is None:
        return eastern_to_utc(dt)
    return (dt - dt.utcoffset()).replace(tzinfo=None)


def utc_of(ts):
    return EPOCH + datetime.timedelta(seconds=int(ts))


def parse_clock(text, what):
    """'10:15 AM', '10:15am', '15:55' or '3:55' (a bare 1 to 8 o'clock means p.m.) -> minutes after midnight."""
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*(?:([AaPp])\.?\s*[Mm]\.?)?\s*$", str(text or ""))
    if not m:
        raise TMError("%s wants a New York time like 10:15 AM or 15:55, not %r" % (what, text))
    h, mi, ap = int(m.group(1)), int(m.group(2)), (m.group(3) or "").lower()
    if mi > 59 or h > 23 or (ap and not 1 <= h <= 12):
        raise TMError("%s %r is not a clock time" % (what, text))
    if ap == "p" and h != 12:
        h += 12
    elif ap == "a" and h == 12:
        h = 0
    elif not ap and 1 <= h <= 8:
        h += 12
    return h * 60 + mi


def clock12(minutes):
    h, m = divmod(minutes, 60)
    return "%d:%02d %s" % (h % 12 or 12, m, "AM" if h < 12 else "PM")


def clock24(minutes):
    return "%02d:%02d" % divmod(minutes, 60)


# ---------------------------------------------------------------- data

def chart_url(sym, host="query2"):
    return "https://%s.finance.yahoo.com/v8/finance/chart/%s?range=60d&interval=5m" % (
        host, urllib.parse.quote(sym.upper().replace(".", "-")))


def _sleep(seconds):
    time.sleep(seconds)


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def fetch_chart(sym):
    """One request for 60 days of 5-min bars. query2 first, one retry after a 429,
    then query1 on 429 or 5xx."""
    last = None
    for n, host in enumerate(HOSTS):
        if n:
            _sleep(PAUSE)
        for attempt in (0, 1):
            url = chart_url(sym, host)
            try:
                return _get(url)
            except urllib.error.HTTPError as e:
                last = e.code
                try:
                    e.close()
                except Exception:
                    pass
                if e.code == 429 and attempt == 0:
                    _sleep(BACKOFF)
                    continue
                if e.code == 429 or e.code >= 500:
                    break
                if e.code == 404:
                    raise TMError("Yahoo has no chart for %s (HTTP 404): check the ticker" % sym.upper())
                raise TMError("Yahoo answered HTTP %d for %s" % (e.code, sym.upper()))
            except urllib.error.URLError as e:
                raise TMError("could not reach Yahoo: %s" % e.reason)
            except OSError as e:
                raise TMError("could not reach Yahoo: %s" % e)
    if last == 429:
        raise TMError("Yahoo is rate limiting (HTTP 429). Wait a minute and run it again.")
    raise TMError("Yahoo answered HTTP %s for %s on both hosts. Try again later." % (last, sym.upper()))


def read_offline(path, sym):
    """A saved Yahoo chart file (.json or .json.gz), or a folder holding <SYM>-60d5m.json(.gz)."""
    if os.path.isdir(path):
        for name in ("%s-60d5m.json" % sym.upper(), "%s-60d5m.json.gz" % sym.upper()):
            if os.path.exists(os.path.join(path, name)):
                path = os.path.join(path, name)
                break
        else:
            raise TMError("no %s-60d5m.json(.gz) in %s" % (sym.upper(), path))
    if not os.path.exists(path):
        raise TMError("no offline chart file %s" % path)
    opener = gzip.open if path.endswith(".gz") else open
    try:
        with opener(path, "rt", encoding="utf-8") as fh:
            return fh.read()
    except OSError as e:
        raise TMError("could not read %s: %s" % (path, e))


def chart_result(text, sym):
    try:
        data = json.loads(text)
    except ValueError:
        raise TMError("Yahoo returned something that is not JSON for %s" % sym.upper())
    chart = data.get("chart") if isinstance(data, dict) else None
    if not isinstance(chart, dict):
        raise TMError("Yahoo returned something unexpected for %s" % sym.upper())
    res = chart.get("result")
    if not res:
        err = chart.get("error") or {}
        raise TMError("Yahoo has no data for %s: %s" % (sym.upper(), err.get("description") or "unknown ticker"))
    return res[0]


def parse_bars(result, now_utc):
    """Yahoo chart result -> (meta, bars, dropped). Regular-session 5-min bars only,
    oldest first. Dropped: bars with a missing price, bars off the 5-minute grid
    (the live tick, e.g. 10:49:45), bars not complete yet (now < start + 5 min,
    where now is the earlier of --now and the data's own regularMarketTime), and
    bars outside 9:30 to 16:00 New York time."""
    meta = result.get("meta") or {}
    stamps = result.get("timestamp") or []
    q = ((result.get("indicators") or {}).get("quote") or [{}])[0] or {}
    cols = [q.get(k) or [] for k in ("open", "high", "low", "close", "volume")]
    as_of = now_utc
    rmt = meta.get("regularMarketTime")
    if isinstance(rmt, (int, float)) and utc_of(rmt) < as_of:
        as_of = utc_of(rmt)
    dropped = {"no_price": 0, "off_grid": 0, "not_complete": 0, "outside_hours": 0}
    bars = {}
    for i, ts in enumerate(stamps):
        o, h, l, c, v = [col[i] if i < len(col) else None for col in cols]
        if ts is None or None in (o, h, l, c):
            dropped["no_price"] += 1
            continue
        ts = int(ts)
        if ts % INTERVAL:
            dropped["off_grid"] += 1
            continue
        start = utc_of(ts)
        local = to_eastern(start)
        mins = local.hour * 60 + local.minute - OPEN_MIN
        if mins < 0 or mins >= SESSION_BARS * 5:
            dropped["outside_hours"] += 1
            continue
        if start + datetime.timedelta(seconds=INTERVAL) > as_of:
            dropped["not_complete"] += 1
            continue
        bars[ts] = {"date": local.date().isoformat(), "slot": mins // 5, "start": local.strftime("%H:%M"),
                    "o": o, "h": h, "l": l, "c": c, "v": v or 0}
    return meta, [bars[t] for t in sorted(bars)], dropped


def split_sessions(bars):
    """{date: {slot: bar}}."""
    days = {}
    for b in bars:
        days.setdefault(b["date"], {})[b["slot"]] = b
    return days


def full_sessions(days, before):
    """Full sessions (all 78 bars) strictly before the plan's date, oldest first,
    and the short ones that were left out (half days, gaps)."""
    full, short = [], []
    for d in sorted(days):
        if d >= before:
            continue
        s = days[d]
        if len(s) == SESSION_BARS:
            full.append((d, [s[i] for i in range(SESSION_BARS)]))
        else:
            short.append({"date": d, "bars": len(s)})
    return full, short


def classify_sessions(days, before, early_dates=()):
    """(full, early, incomplete) strictly before the plan's date, oldest first. full: all 78 bars (the
    Monte Carlo pool, the history); early: a 1:00 p.m. early close on the calendar with all 42 bars (the
    history, the control and the baseline only); incomplete: anything else, dropped and listed."""
    full, early, short = [], [], []
    for d in sorted(days):
        if d >= before:
            continue
        s = days[d]
        if len(s) == SESSION_BARS:
            full.append((d, [s[i] for i in range(SESSION_BARS)]))
        elif d in early_dates and len(s) == EARLY_BARS and all(i in s for i in range(EARLY_BARS)):
            early.append((d, [s[i] for i in range(EARLY_BARS)]))
        else:
            short.append({"date": d, "bars": len(s)})
    return full, early, short


def early_last(until_min, plan_early):
    """The last bar of an early-close session in the history: the --until (flat-by) time moved up with
    the 1:00 p.m. close the way trader-exit's resolve_flat_by moves it (16:00 -> 13:00, bar 41; 15:55 ->
    12:55, bar 40); a time before 13:00, or a plan day that is itself an early close, stays."""
    if plan_early or until_min < EARLY_MIN:
        return (min(until_min, EARLY_MIN) - OPEN_MIN) // 5 - 1
    return (until_min - (CLOSE_MIN - EARLY_MIN) - OPEN_MIN) // 5 - 1


# ---------------------------------------------------------------- the simulation (sim.py)

def build_pool(sessions):
    """pool[i] = every past session's bar i as (o, h, l, c) / bar i-1's close, in date order."""
    pool = [[] for _ in range(SESSION_BARS)]
    for _, D in sessions:
        for i in range(1, SESSION_BARS):
            pc = D[i - 1]["c"]
            pool[i].append((D[i]["o"] / pc, D[i]["h"] / pc, D[i]["l"] / pc, D[i]["c"] / pc))
    return pool


def pct(a, q):
    return a[min(len(a) - 1, int(q * len(a)))]


def simulate(pool, entry, stop, target, k, last, replays=10000, seed=19, window=2, side="buy", gap_fill="open"):
    """Monte Carlo replays of bars k+1..last. Same draws and order as the reel's sim.py. This loop is the
    one caller that reuses mjonir.outcomes.touch() bar by bar instead of score_trade(): the bars are
    drawn as it walks (the draws must stay in upstream's order), so there is no bar list to score. touch()
    is score_trade()'s own per-bar rule (the stop first; a bar opening through the stop fills at its open
    under gap_fill "open", at the stop under "stop"). target None: only the stop or the close."""
    touch = _measure("outcomes").touch
    long = side == "buy"
    risk = (entry - stop) if long else (stop - entry)
    r_target = None if target is None else round(((target - entry) if long else (entry - target)) / risk, 4)

    def slot(rng, i):
        return i if window == 0 else min(SESSION_BARS - 1, max(1, i + rng.randint(-window, window)))

    rng = random.Random(seed)
    choice = rng.choice
    outcomes, closes, paths, fills = [], [], [], []
    for n in range(replays):
        p = entry
        outcome = fill = None
        keep = n < SAMPLE_PATHS
        path = [entry]
        for i in range(k + 1, last + 1):
            o, h, l, c = choice(pool[slot(rng, i)])
            hi, lo, cl = p * h, p * l, p * c
            if outcome is None:
                hit = touch(p * o, hi, lo, stop, target, long, gap_fill)   # both in one bar: the stop
                if hit is not None:
                    outcome, fill = hit
            p = cl
            if keep:
                path.append(round(p, 2))
        outcomes.append(outcome or "close")
        closes.append(p)
        fills.append(fill)
        if keep:
            paths.append(path)
    cnt = {x: outcomes.count(x) for x in ("target", "stop", "close")}
    green = sum(1 for o, p in zip(outcomes, closes)
                if o == "target" or (o == "close" and (p > entry if long else p < entry)))
    Rs = [r_target if o == "target" else
          (((f - entry) if long else (entry - f)) / risk) if o == "stop" else
          ((p - entry) if long else (entry - p)) / risk
          for o, p, f in zip(outcomes, closes, fills)]
    srt = sorted(closes)
    # percentile bands per bar for the fan chart: a second run of 2,000 paths, same seed
    rng = random.Random(seed)
    choice = rng.choice
    allp = []
    for n in range(BAND_PATHS):
        p = entry
        path = [entry]
        for i in range(k + 1, last + 1):
            o, h, l, c = choice(pool[slot(rng, i)])
            p = p * c
            path.append(p)
        allp.append(path)
    bands = []
    for j in range(last - k + 1):
        col = sorted(pp[j] for pp in allp)
        bands.append([round(pct(col, q), 2) for q in BAND_Q])
    lo_, hi_ = pct(srt, 0.01), pct(srt, 0.99)
    W = (hi_ - lo_) / HIST_BINS
    bins = [0] * HIST_BINS
    for c in srt:
        b = int((c - lo_) / W) if W > 0 else 0
        if 0 <= b < HIST_BINS:
            bins[b] += 1
    return {
        "replays": replays, "seed": seed, "window": window, "bars_left": last - k, "gap_fill": gap_fill,
        "p_target": round(cnt["target"] / replays, 4), "p_stop": round(cnt["stop"] / replays, 4),
        "p_neither": round(cnt["close"] / replays, 4), "p_green": round(green / replays, 4),
        "median_close": round(pct(srt, 0.5), 2), "p5_close": round(pct(srt, 0.05), 2),
        "p95_close": round(pct(srt, 0.95), 2), "avg_R": round(statistics.mean(Rs), 3),
        "r_at_target": r_target, "band_paths": BAND_PATHS, "bands": bands, "sample_paths": paths,
        "hist": {"lo": round(lo_, 2), "hi": round(hi_, 2), "bins": bins},
    }


# ---------------------------------------------------------------- stop rules and the history replay

def cents_away(x, long):
    """Round a stop to the cent, away from the entry: down for a buy, up for a sell."""
    c = round(x * 100, 4)
    return (math.floor(c) if long else math.ceil(c)) / 100.0


def opening_range(D, n):
    """(high, low) of the first n bars of a session given as {slot: bar} or a list."""
    rows = [D[i] for i in range(n)]
    return max(b["h"] for b in rows), min(b["l"] for b in rows)


def rule_stop(rule, oh, ol, entry, long):
    r = rule["stop_rule"]
    if r == "or_mid":
        return cents_away((oh + ol) / 2, long)
    if r in ("or_low", "or_high"):
        return cents_away(ol if long else oh, long)
    frac = rule["stop_pct"] / 100.0
    return cents_away(entry * (1 - frac) if long else entry * (1 + frac), long)


def rule_trade(D, rule, n, last, long, entry_shift=0.0):
    """(bar, entry, stop, target) of the rule on one session, or None: the first bar after the opening
    range to close beyond it (up to `last`), entered at that UNROUNDED close (+ entry_shift, the one-tick
    sensitivity), the stop by the rule (a cent price), the target = entry + R x risk (None without one)."""
    oh, ol = opening_range(D, n)
    kk = next((i for i in range(n, last + 1) if (D[i]["c"] > oh if long else D[i]["c"] < ol)), None)
    if kk is None:
        return None
    e = D[kk]["c"] + entry_shift
    s = rule_stop(rule, oh, ol, e, long)
    risk = (e - s) if long else (s - e)
    if risk <= 0:
        return None
    r = rule.get("target_r")
    t = None if r is None else (e + r * risk if long else e - r * risk)
    return kk, e, s, t


def _cost_fn(cost_model):
    costs = _measure("costs")
    return lambda entry, risk: costs.trade_cost_r(entry, risk, cost_model)


def _ci(stats, rs, seed):
    return stats.expectancy_ci(rs, seed=seed) if rs else None


def history_replay(sessions, rule, last, side="buy", cost_model=None, gap_fill="open", control_draws=0,
                   symbol="", seed=19, lasts=None, entry_shift=0.0, summary=True, control_bar="random",
                   entry_until=None, entry_untils=None):
    """The plan's rule on every past session given (full and early closes): entry = the first bar after
    the opening range to close beyond it (up to the session's last bar), then mjonir.outcomes.score_trade
    (the stop first, the target, else the close at the last bar). lasts: {date: last bar} for the early
    closes. Each trade is charged its own cost_r once (cost_model None = costs off). With control_draws
    K, K random-entry control trades a firing session (mjonir/control.py); control_bar="rule" pins them to
    the rule's own bar (the delta-0 pin). summary=False skips the intervals (the sensitivity re-runs).
    entry_until (entry_untils {date: bar} for the early closes): the last bar the rule may fire on and a
    control may enter on (the no-entries-after window); None = up to the session's last bar (upstream)."""
    outcomes, stats, control = _measure("outcomes"), _measure("stats"), _measure("control")
    long = side == "buy"
    n = rule["or_minutes"] // 5
    cost_r_of = _cost_fn(cost_model)
    lasts = lasts or {}
    trades, ctrl, skipped = [], {}, {"risk_floor": 0, "no_eligible_bar": 0}
    for d, D in sessions:
        ls = lasts.get(d, last)
        eu = (entry_untils or {}).get(d, entry_until)
        fire_last = ls if eu is None else min(ls, eu)
        rt = rule_trade(D, rule, n, fire_last, long, entry_shift)
        if rt is None:
            continue
        kk, e, st, t = rt
        risk = (e - st) if long else (st - e)
        cr = cost_r_of(e, risk)
        res = outcomes.score_trade(D, kk, e, st, t, ls, cr, gap_fill=gap_fill, long=long)
        trades.append({"date": d, "time": clock12(OPEN_MIN + 5 * (kk + 1)), "entry": round(e, 2), "stop": st,
                       "target": None if t is None else round(t, 2), "outcome": res["outcome"],
                       "R": round(res["gross_r"], 2), "net_R": round(res["net_r"], 4), "cost_r": round(cr, 4),
                       "margin_r": None if res["decision_margin_r"] is None else round(res["decision_margin_r"], 4),
                       "fragile": res["fragile"], "gap": res["gap"], "last_bar": ls,
                       "early_close": d in lasts, "_gross": res["gross_r"], "_net": res["net_r"],
                       "_entry": e, "_bar": kk})
        if control_draws:
            got, why = control.draw_controls(D, symbol, d, seed, control_draws, n, ls, e, st, rule.get("target_r"),
                                             cost_r_of, gap_fill, long, entry_until=fire_last,
                                             force_bar=kk if control_bar == "rule" else None)
            for key, v in why.items():
                skipped[key] += v
            if got:
                ctrl[d] = got
    out = {
        "sessions": len(sessions), "triggered": len(trades),
        "target": sum(1 for x in trades if x["outcome"] == "target"),
        "stop": sum(1 for x in trades if x["outcome"] == "stop"),
        "close": sum(1 for x in trades if x["outcome"] == "close"),
        "green": sum(1 for x in trades if x["R"] > 0),
        "avg_R": round(statistics.mean(x["R"] for x in trades), 3) if trades else None,
        "rule": rule, "trades": trades,
    }
    if summary:
        out.update(_history_summary(stats, trades, seed))
        if control_draws:
            out["control"] = _control_summary(stats, trades, ctrl, skipped, control_draws, seed)
    for x in trades:
        if summary:
            for key in ("_gross", "_net", "_entry", "_bar"):
                x.pop(key, None)
    return out


def _history_summary(stats, trades, seed):
    gross = [x["_gross"] for x in trades]
    net = [x["_net"] for x in trades]
    dec = stats.decided_rate([x["outcome"] for x in trades])
    years = {}
    for x in trades:
        years.setdefault(x["date"][:4], []).append(x)
    by_year = {}
    for y in sorted(years):
        rows = years[y]
        by_year[y] = {"n": len(rows), "target": sum(1 for x in rows if x["outcome"] == "target"),
                      "stop": sum(1 for x in rows if x["outcome"] == "stop"),
                      "close": sum(1 for x in rows if x["outcome"] == "close"),
                      "net": _ci(stats, [x["_net"] for x in rows], seed),
                      "decided": stats.decided_rate([x["outcome"] for x in rows])}
    signs = {y: (v["net"]["mean"] > 0) for y, v in by_year.items() if v["net"] and v["net"]["mean"] != 0}
    note = None
    if len(set(signs.values())) > 1:
        note = "the sign of the net average flips between years: " + ", ".join(
            "%s %+.3f (n %d)" % (y, by_year[y]["net"]["mean"], by_year[y]["n"]) for y in sorted(signs))
    return {"gross": _ci(stats, gross, seed), "net": _ci(stats, net, seed), "decided": dec,
            "fragile": sum(1 for x in trades if x["fragile"]),
            "fragile_dates": [x["date"] for x in trades if x["fragile"]],
            "cost_r_mean": (sum(x["cost_r"] for x in trades) / len(trades)) if trades else None,
            "gap_fills": sum(1 for x in trades if x["gap"]),
            "early_close_trades": sum(1 for x in trades if x["early_close"]),
            "by_year": by_year, "by_year_note": note}


def _control_summary(stats, trades, ctrl, skipped, draws, seed):
    rows = [c for d in sorted(ctrl) for c in ctrl[d]]
    rule_by = {x["date"]: [x["_net"]] for x in trades}
    ctrl_by = {d: [c["net_r"] for c in v] for d, v in ctrl.items()}
    paired = [d for d in rule_by if d in ctrl_by]
    return {"draws": draws, "seed": seed, "sessions": len(ctrl), "trades": len(rows), "skipped": skipped,
            "net": _ci(stats, [c["net_r"] for c in rows], seed),
            "decided": stats.decided_rate([c["outcome"] for c in rows]),
            "delta": stats.paired_delta_ci(rule_by, ctrl_by, seed=seed) if paired else None,
            "rule": "random bar after the opening range and before the last bar, the rule's risk as a percent "
                    "of the entry, the same target multiple and last bar; seed %s:symbol:date a session" % seed}


def sensitivity(sessions, rule, last, side, cost_model, gap_fill, lasts, base, tick=TICK, entry_until=None,
                entry_untils=None):
    """The one-tick sensitivity: the history re-scored with the entry `tick` higher and lower. A flip is a
    date whose outcome changes (a trade that no longer has a valid stop counts as a flip to "none")."""
    was = {t["date"]: t["outcome"] for t in base["trades"]}
    out = {"tick": tick, "of": len(was)}
    for name, shift in (("up", tick), ("down", -tick)):
        h = history_replay(sessions, rule, last, side, cost_model, gap_fill, 0, lasts=lasts, entry_shift=shift,
                           entry_until=entry_until, entry_untils=entry_untils,
                           summary=False)
        now = {t["date"]: t["outcome"] for t in h["trades"]}
        flipped = sorted(d for d in was if now.get(d, "none") != was[d])
        out[name] = {"flips": len(flipped), "dates": flipped}
    out["flips"] = out["up"]["flips"] + out["down"]["flips"]
    return out


def baseline_replay(sessions, rule, last, side="buy", cost_model=None, gap_fill="open", lasts=None, seed=19):
    """"Buy any morning strength": the close of the last opening-range bar on EVERY session, the rule's
    stop and target multiple, scored like the rule. A diagnostic, never a verdict."""
    outcomes, stats, control = _measure("outcomes"), _measure("stats"), _measure("control")
    long = side == "buy"
    n = rule["or_minutes"] // 5
    j = control.baseline_entry_bar(n)
    cost_r_of = _cost_fn(cost_model)
    lasts = lasts or {}
    rows, skipped = [], 0
    for d, D in sessions:
        ls = lasts.get(d, last)
        oh, ol = opening_range(D, n)
        e = D[j]["c"]
        st = rule_stop(rule, oh, ol, e, long)
        risk = (e - st) if long else (st - e)
        if risk <= 0 or ls <= j or 100.0 * risk / e < control.RISK_FLOOR_PCT:
            skipped += 1
            continue
        r = rule.get("target_r")
        t = None if r is None else (e + r * risk if long else e - r * risk)
        rows.append(outcomes.score_trade(D, j, e, st, t, ls, cost_r_of(e, risk), gap_fill=gap_fill, long=long))
    return {"sessions": len(sessions), "trades": len(rows), "skipped": skipped,
            "target": sum(1 for x in rows if x["outcome"] == "target"),
            "stop": sum(1 for x in rows if x["outcome"] == "stop"),
            "close": sum(1 for x in rows if x["outcome"] == "close"),
            "net": _ci(stats, [x["net_r"] for x in rows], seed),
            "decided": stats.decided_rate([x["outcome"] for x in rows]),
            "note": "buy any morning strength: the close of the last opening-range bar on every session, the "
                    "rule's stop and target multiple. A diagnostic, never a verdict."}


# ---------------------------------------------------------------- the plan

def _num(v, what):
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise TMError("the plan needs a number for %s, got %r" % (what, v))
    if not x > 0 or math.isinf(x):
        raise TMError("the plan's %s must be a positive price, got %r" % (what, v))
    return x


def load_plan(a, now_utc):
    """The plan from --plan (trader/plan.json) or from the flags, checked and normalized."""
    if a.symbol:
        need = ("entry", "stop", "entry_time") if getattr(a, "exit", None) == "close" else \
            ("entry", "stop", "target", "entry_time")
        missing = [f for f in need if getattr(a, f) is None]
        if missing:
            raise TMError("with --symbol also give %s" % ", ".join("--" + m.replace("_", "-") for m in missing))
        raw = {"symbol": a.symbol, "side": a.side, "date": a.date or to_eastern(now_utc).date().isoformat(),
               "entry": a.entry, "stop": a.stop, "target": a.target, "entry_time": a.entry_time,
               "setup": a.setup, "opening_range": {"minutes": a.or_minutes}, "stop_rule": a.stop_rule,
               "interval": "5m", "exit": getattr(a, "exit", None) or "target"}
        src = "flags"
    else:
        if not os.path.exists(a.plan):
            raise TMError("no plan at %s: run /trader-exit first, or pass --symbol --date --entry --stop "
                          "--target --entry-time" % a.plan)
        try:
            with open(a.plan, encoding="utf-8") as fh:
                raw = json.load(fh)
        except ValueError as e:
            raise TMError("%s is not valid JSON: %s" % (a.plan, e))
        if not isinstance(raw, dict):
            raise TMError("%s is not a plan" % a.plan)
        src = a.plan
    return normalize_plan(raw, src)


def normalize_plan(raw, src="flags"):
    """A plan dict (trader/plan.json shape) -> the checked plan the time machine runs."""
    sym = str(raw.get("symbol") or "").strip().upper()
    if not re.match(r"^[A-Z][A-Z0-9.\-]{0,9}$", sym):
        raise TMError("the plan needs a ticker symbol, got %r" % raw.get("symbol"))
    side = str(raw.get("side") or "buy").lower()
    if side not in ("buy", "sell"):
        raise TMError("side must be buy or sell, got %r" % raw.get("side"))
    interval = str(raw.get("interval") or "5m")
    if interval != "5m":
        raise TMError("5-minute bars only (the plan says %s): Yahoo keeps 60 days of 5-min bars but only about "
                      "7 days of 1-min bars, too few sessions for a fair replay pool" % interval)
    try:
        date = datetime.date.fromisoformat(str(raw.get("date") or "")).isoformat()
    except ValueError:
        raise TMError("the plan needs a date like 2026-10-19, got %r" % raw.get("date"))
    exit_rule = str(raw.get("exit") or "target").lower()
    if exit_rule not in ("target", "close"):
        raise TMError("exit is target (out at the target, the stop or the flat-by) or close (no target: the stop "
                      "or the flat-by close), not %r" % raw.get("exit"))
    if exit_rule == "close" and raw.get("target") is not None:
        raise TMError("an exit-at-the-close plan has no target (got target %r)" % raw.get("target"))
    entry, stop = _num(raw.get("entry"), "entry"), _num(raw.get("stop"), "stop")
    target = None if exit_rule == "close" else _num(raw.get("target"), "target")
    long = side == "buy"
    if target is None:
        if (long and not stop < entry) or (not long and not entry < stop):
            raise TMError("a %s needs its stop %s the entry (got stop %s, entry %s)"
                          % (side, "under" if long else "over", stop, entry))
    elif long and not stop < entry < target:
        raise TMError("a buy needs stop < entry < target (got stop %s, entry %s, target %s)" % (stop, entry, target))
    elif not long and not target < entry < stop:
        raise TMError("a sell needs target < entry < stop (got target %s, entry %s, stop %s)" % (target, entry, stop))
    k = None
    if raw.get("entry_time"):
        close_min = parse_clock(raw["entry_time"], "entry_time")
        if (close_min - OPEN_MIN) % 5:
            raise TMError("entry_time %s is not on the 5-minute grid (use the bar's close, e.g. 10:15 AM)"
                          % raw["entry_time"])
        k = (close_min - OPEN_MIN) // 5 - 1
    if raw.get("entry_bar") is not None:
        try:
            kb = int(raw["entry_bar"])
        except (TypeError, ValueError):
            raise TMError("entry_bar must be a bar number, got %r" % raw["entry_bar"])
        if k is not None and kb != k:
            raise TMError("the plan disagrees with itself: entry_bar %d but entry_time %s is bar %d"
                          % (kb, raw["entry_time"], k))
        k = kb
    if k is None:
        raise TMError("the plan needs entry_time (the entry bar's close, e.g. 10:15 AM) or entry_bar")
    if not 0 <= k <= SESSION_BARS - 2:
        raise TMError("the entry must close between 9:35 AM and 3:55 PM to leave bars to replay "
                      "(got %s)" % clock12(OPEN_MIN + 5 * (k + 1)))
    orng = raw.get("opening_range") or {}
    or_min = orng.get("minutes", 15) if isinstance(orng, dict) else 15
    try:
        or_min = int(or_min)
    except (TypeError, ValueError):
        raise TMError("opening_range.minutes must be a number")
    if or_min < 5 or or_min % 5 or or_min >= 390:
        raise TMError("opening_range.minutes must be a multiple of 5 (got %s)" % or_min)
    risk = (entry - stop) if long else (stop - entry)
    return {
        "symbol": sym, "side": side, "date": date, "setup": str(raw.get("setup") or "orb"),
        "entry": entry, "entry_time": clock12(OPEN_MIN + 5 * (k + 1)), "entry_bar": k,
        "stop": stop, "target": target, "risk_per_share": round(risk, 2),
        "target_r": None if target is None else round(((target - entry) if long else (entry - target)) / risk, 2),
        "opening_range": dict(orng, minutes=or_min) if isinstance(orng, dict) else {"minutes": or_min},
        "stop_rule": str(raw.get("stop_rule") or "auto"), "interval": "5m",
        "flat_by": raw.get("flat_by"), "from": src, "exit": exit_rule,
        "costs": raw.get("costs") if isinstance(raw.get("costs"), dict) else None,
    }


def resolve_rule(plan, entry_day):
    """The rule the history replay uses: orb, the plan's opening range, its stop rule
    (or_mid, or_low / or_high, or 'pct' = the plan's stop distance as a percent of
    the entry), and the plan's target R. 'auto' works the stop rule out from the
    plan day's own opening range. None when the setup is not orb."""
    if plan["setup"].lower() != "orb":
        return None
    long = plan["side"] == "buy"
    n = plan["opening_range"]["minutes"] // 5
    rule = {"setup": "orb", "or_minutes": plan["opening_range"]["minutes"], "stop_rule": plan["stop_rule"],
            "target_r": plan["target_r"],
            "stop_pct": round(100.0 * plan["risk_per_share"] / plan["entry"], 4)}
    far = "or_low" if long else "or_high"
    if rule["stop_rule"] == "auto":
        rule["stop_rule"] = "pct"
        if all(i in entry_day for i in range(n)):
            oh, ol = opening_range(entry_day, n)
            if abs(cents_away((oh + ol) / 2, long) - plan["stop"]) < 0.005:
                rule["stop_rule"] = "or_mid"
            elif abs(cents_away(ol if long else oh, long) - plan["stop"]) < 0.005:
                rule["stop_rule"] = far
    elif rule["stop_rule"] in ("or_low", "or_high") and rule["stop_rule"] != far:
        rule["stop_rule"] = "pct"
    elif rule["stop_rule"] not in ("or_mid", far):
        rule["stop_rule"] = "pct"
    if rule["stop_rule"] != "pct":
        del rule["stop_pct"]
    return rule


# ---------------------------------------------------------------- the run

def _until12(mc):
    t = mc.get("until") or "16:00"
    return clock12(int(t[:2]) * 60 + int(t[3:]))


def lean(mc):
    """(gap, share, break_even): the target's share of the replays that hit one side,
    minus the share that breaks even at the target's R. None when nothing hit a side."""
    pt, ps = mc["p_target"], mc["p_stop"]
    if pt + ps <= 0 or mc.get("r_at_target", 1.0) is None:
        return None
    r = mc.get("r_at_target") or 1.0
    share, even = pt / (pt + ps), 1.0 / (1.0 + r)
    return share - even, share, even


def mc_shape_line(mc):
    """The Monte Carlo block's one line: a shape diagnostic, never a verdict (no verdict reads it)."""
    pt, ps = mc["p_target"], mc["p_stop"]
    if "r_at_target" in mc and mc["r_at_target"] is None:
        return "%s: no target; stop first %.1f %%, still open at %s %.1f %%." % (
            SHAPE, 100 * ps, _until12(mc), 100 * mc.get("p_neither", 0))
    lv = lean(mc)
    if lv is None:
        return "%s: no replay reached the target or the stop by %s; the price at %s decides every one." % (
            SHAPE, _until12(mc), _until12(mc))
    d, share, even = lv
    r = mc.get("r_at_target") or 1.0
    odds = "target first %.1f %% vs stop first %.1f %%" % (100 * pt, 100 * ps)
    if abs(r - 1.0) < 0.005:
        return "%s: %s." % (SHAPE, odds)
    return ("%s: at %gR the target has to come first in %.0f %% of the replays that hit one side; "
            "it did in %.0f %% (%s)." % (SHAPE, round(r, 2), 100 * even, 100 * share, odds))


def verdict_notes(mc):
    """The Monte Carlo notes printed under its shape line (doc key mc_notes)."""
    notes = []
    pn = mc.get("p_neither", 0)
    if pn > MANY_NEITHER and lean(mc) is not None:
        notes.append("%.1f %% of the replays hit neither by %s; the price at %s decides those."
                     % (100 * pn, _until12(mc), _until12(mc)))
    lv = lean(mc)
    avg = mc.get("avg_R")
    if lv and abs(lv[0]) >= NOTE_GAP and avg is not None and avg != 0 and (avg > 0) != (lv[0] > 0):
        notes.append("Average R is %+.3f all the same: the replays that hit neither pull it the other way." % avg)
    return notes


def cost_card_for(plan, costs_arg="auto", cfg=None, adv_usd=None, adv_note=None):
    """The plan's cost card: costs_arg None/False = off; a dict = that card; "auto" = the plan's own card
    (trader-exit writes one) or a default card (ADV as given, else unverified: the most expensive tier)."""
    if costs_arg is None or costs_arg is False:
        return None
    if isinstance(costs_arg, dict):
        return costs_arg
    if plan.get("costs"):
        return plan["costs"]
    costs = _measure("costs")
    long = plan["side"] == "buy"
    risk = (plan["entry"] - plan["stop"]) if long else (plan["stop"] - plan["entry"])
    try:
        ml = costs.max_loss_basis(cfg)     # a percent config: the derived max loss (mjonir/limits.py)
        shares, how = costs.shares_basis(risk, ml)
        card = costs.cost_card(plan["entry"], plan["stop"], plan["target"], shares, adv_usd=adv_usd, cfg=cfg,
                               long=long, adv_note=adv_note, max_loss_usd=float(ml))
    except costs.CostError as e:
        raise TMError("costs: %s" % e)
    card["shares_basis"] = how
    return card


def data_basis(meta, source):
    """(data source, adjustment) from the document itself, never from --source: meta.mjonir.store (the
    bars_5m call's own source: api, cache, kalex or flatfile), else meta.mjonir.source (a bridged file),
    else a Yahoo document (no mjonir block)."""
    mj = meta.get("mjonir") if isinstance(meta.get("mjonir"), dict) else None
    if mj is None:
        return "yahoo", {"adjusted": None, "as_of": None,
                         "basis": "Yahoo v8 chart: the adjustment is not stated by the source"}
    src = mj.get("store") or mj.get("source") or source
    adj = mj.get("adjusted")
    basis = ("adjusted as of %s" % mj["as_of"]) if adj and mj.get("as_of") else (
        "adjusted" if adj else "UNADJUSTED (flat files: no split may fall inside the window)" if adj is False
        else "not stated")
    return src, {"adjusted": adj, "as_of": mj.get("as_of"), "basis": basis}


def entry_window_bar(cut_min, early):
    """The last bar an entry may close on for a no-entries-after time: on a 1:00 p.m. early close a cut at
    or after 13:00 moves up three hours (15:30 -> 12:30), as trader-entry's early_cutoff and the forward record
    move it. 15:30 is bar 71; 16:00 is bar 77, the session's last (upstream: no cap)."""
    close = EARLY_MIN if early else CLOSE_MIN
    if cut_min >= close:
        cut_min -= CLOSE_MIN - close
        if cut_min <= OPEN_MIN:
            cut_min = close
    return (cut_min - OPEN_MIN) // 5 - 1


def time_machine(text, plan, now_utc, replays=10000, seed=19, window=2, until=None, source="yahoo",
                 costs="auto", gap_fill="open", control_draws=3, cfg=None, no_entries_after=None):
    """Chart JSON text + a normalized plan -> the timemachine.json document. costs: "auto" (the plan's
    cost card, else the defaults with ADV unverified), a card dict, or None (off: gross only)."""
    if not 1 <= replays <= 1000000:
        raise TMError("--replays must be between 1 and 1,000,000")
    if not 0 <= window <= 10:
        raise TMError("--window must be between 0 and 10 bars")
    if gap_fill not in ("open", "stop"):
        raise TMError("--gap-fill is open or stop")
    if not 0 <= int(control_draws) <= 100:
        raise TMError("--control-draws must be between 0 and 100")
    stats = _measure("stats")
    sym = plan["symbol"]
    result = chart_result(text, sym)
    meta, bars, dropped = parse_bars(result, now_utc)
    if source == "massive":  # the history document names its own store (massive, kalex or flatfile)
        source = (meta.get("mjonir") or {}).get("source") or source
    data_source, adjustment = data_basis(meta, source)
    msym = str(meta.get("symbol") or "").upper()
    if msym and msym != sym.replace(".", "-"):
        raise TMError("the data is for %s but the plan is for %s" % (msym, sym))
    gran = meta.get("dataGranularity")
    if gran and gran != "5m":
        raise TMError("the data has %s bars; the time machine needs 5-minute bars" % gran)
    if not bars:
        raise TMError("no complete 5-minute bars for %s in the data" % sym)
    k = plan["entry_bar"]
    early = plan["date"] in NYSE_EARLY_CLOSE
    end_min = EARLY_MIN if early else CLOSE_MIN
    until_min = end_min if until is None else parse_clock(until, "--until")
    if (until_min - OPEN_MIN) % 5 or until_min > end_min:
        raise TMError("--until must be on the 5-minute grid and no later than %s%s"
                      % (clock12(end_min), " (an early close)" if early else ""))
    last = (until_min - OPEN_MIN) // 5 - 1
    if last <= k:
        raise TMError("--until %s leaves nothing to replay after the %s entry" % (clock12(until_min),
                                                                             plan["entry_time"]))
    days = split_sessions(bars)
    entry_day = days.get(plan["date"], {})
    if k not in entry_day:
        reason = ("no bars for that day" if not entry_day else
                  "the data stops at the %s bar" % entry_day[max(entry_day)]["start"])
        raise TMError("the entry is not in the data: no complete %s bar (closing %s) on %s for %s (%s)"
                      % (clock24(OPEN_MIN + 5 * k), plan["entry_time"], plan["date"], sym, reason))
    eb = entry_day[k]
    warn = []
    if not eb["l"] - 0.01 <= plan["entry"] <= eb["h"] + 0.01:
        warn.append("the plan's entry %.2f is outside that bar's range %.2f to %.2f"
                    % (plan["entry"], eb["l"], eb["h"]))
    mj = meta.get("mjonir") if isinstance(meta.get("mjonir"), dict) else {}
    early_dates = set(NYSE_EARLY_CLOSE) | set(d for d, b in (mj.get("early_closes") or {}).items()
                                               if b != "contradicted")
    sessions, early_sessions, short = classify_sessions(days, plan["date"], early_dates)
    if len(sessions) < MIN_SESSIONS:
        raise TMError("only %d full session(s) of %s before %s in the data; the time machine needs at least %d"
                      % (len(sessions), sym, plan["date"], MIN_SESSIONS))
    card = cost_card_for(plan, costs, cfg)
    cost_model = _measure("costs").model_of(card)
    pool = build_pool(sessions)
    mc = simulate(pool, plan["entry"], plan["stop"], plan["target"], k, last, replays, seed, window, plan["side"],
                  gap_fill)
    mc = dict(mc, until=clock24(until_min), pool_sessions=len(sessions), pool_from=sessions[0][0],
              pool_to=sessions[-1][0],
              band_times=[clock24(OPEN_MIN + 5 * (j + 1)) for j in range(k, last + 1)])
    if card is not None:
        mc["avg_R_net"] = round(mc["avg_R"] - card["cost_r"], 3)
    rule = resolve_rule(plan, entry_day)
    plan_out = {kk: v for kk, v in plan.items() if v is not None and kk != "costs"}
    hist_sessions = sorted(sessions + early_sessions)
    le = early_last(until_min, early)
    lasts = {d: le for d, _ in early_sessions}
    eu = eus = window_doc = None
    if no_entries_after is not None:     # None: fires up to each session's last bar (upstream)
        cut = parse_clock(no_entries_after, "--no-entries-after")
        eu = entry_window_bar(cut, False)
        eus = {d: entry_window_bar(cut, True) for d, _ in early_sessions}
        window_doc = {"no_entries_after": clock24(cut), "bar": eu, "early_close_bar": entry_window_bar(cut, True)}
    if rule:
        plan_out["stop_rule"] = rule["stop_rule"]
        history = history_replay(hist_sessions, rule, last, plan["side"], cost_model, gap_fill, control_draws, sym,
                                 seed, lasts, entry_until=eu, entry_untils=eus)
        history["entry_window"] = window_doc
        history["sensitivity"] = sensitivity(hist_sessions, rule, last, plan["side"], cost_model, gap_fill, lasts,
                                             history, entry_until=eu, entry_untils=eus)
        history["baseline"] = baseline_replay(hist_sessions, rule, last, plan["side"], cost_model, gap_fill, lasts,
                                              seed)
    else:
        history = {"sessions": len(hist_sessions), "triggered": 0, "rule": None, "trades": [],
                   "note": "skipped: the history replay knows the opening-range breakout (orb) only, "
                           "this plan's setup is %r" % plan["setup"]}
    # the break-even in the decided diagnostic is the history's OWN mean round trip (each trade was charged
    # its own), else the plan card's, else 0
    if history.get("cost_r_mean") is not None:
        cost_r = history["cost_r_mean"]
    else:
        cost_r = card["cost_r"] if card else 0.0
    vh = stats.verdict_history({"target": history.get("target", 0), "stop": history.get("stop", 0),
                                "triggered": history.get("triggered", 0), "expectancy": history.get("net")},
                               plan["target_r"], cost_r, costs_on=card is not None)
    ctrl = history.get("control") or {}
    vc = stats.verdict_control(ctrl.get("delta"))
    if not control_draws:
        vc = dict(vc, reason="off", text="Random-entry control: off (--control-draws 0).")
    last_bar = bars[-1]
    return {
        "created_by": "trader-timemachine",
        "created_at": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": source,
        "data": {"symbol": msym or sym, "interval": "5m", "range": meta.get("range") or "60d",
                 "last_bar": "%s %s ET" % (last_bar["date"], last_bar["start"]),
                 "dropped": dropped, "source": data_source, "adjustment": adjustment,
                 "early_close_used": [{"date": d, "bars": len(D), "last_bar": le} for d, D in early_sessions],
                 "incomplete_dropped": short},
        "plan": plan_out,
        "costs": {"on": card is not None, "card": card, "model": cost_model, "gap_fill": gap_fill,
                  "control_draws": int(control_draws)},
        "mc": mc,
        "history": history,
        "verdict_history": vh,
        "verdict_control": vc,
        "mc_shape": mc_shape_line(mc),
        "mc_notes": verdict_notes(mc),
        "warnings": warn,
        "note": ("A simulation built from %s's own last %d full sessions. It is not a prediction: earnings, "
                 "news and halts can do things those sessions never did. Same seed, same numbers." % (sym, len(sessions))),
    }


# ---------------------------------------------------------------- output

def pc(x):
    return "%.1f %%" % (100.0 * x)


def _iv(ci):
    """'-0.190 (95 % bootstrap interval -0.52 to +0.15, n 33)': no average without its interval and n."""
    return "%+.3f (95 %% bootstrap interval %+.3f to %+.3f, n %d)" % (ci["mean"], ci["lo"], ci["hi"], ci["n"])


def _dec(d):
    if not d or not d.get("n"):
        return "no decided fires"
    return "%d of %d hit the target first (%s, 95 %% Wilson %s to %s)" % (d["k"], d["n"], pc(d["p"]), pc(d["lo"]),
                                                                         pc(d["hi"]))


def history_lines(doc):
    p, h, c = doc["plan"], doc["history"], doc.get("costs") or {}
    on = c.get("on")
    if not h.get("rule"):
        return ["History: " + h.get("note", "skipped.")]
    ru = h["rule"]
    stop_words = {"or_mid": "opening-range midpoint", "or_low": "opening-range low",
                  "or_high": "opening-range high"}.get(ru["stop_rule"], "%.2f %% from the entry" % ru.get("stop_pct", 0))
    tgt = ("%gR target" % ru["target_r"]) if ru.get("target_r") is not None else "no target (out at the close)"
    if not h["triggered"]:
        return ["History: the same rule never fired in those %d sessions." % h["sessions"]]
    head = ("History: the same rule (%d-min opening range, stop at the %s, %s) on each of those %d real sessions "
            "fired %d times: %d target, %d stop, %d neither." % (ru["or_minutes"], stop_words, tgt, h["sessions"],
                                                                 h["triggered"], h["target"], h["stop"], h["close"]))
    if on:
        out = [head + " Average R, net of costs, %s." % _iv(h["net"]),
               "  Gross average R %s; costs %.3f R a trade on average (n %d)."
               % (_iv(h["gross"]), h["cost_r_mean"], h["triggered"])]
    else:
        out = [head + " Average R %s, costs off." % _iv(h["gross"])]
    frag = "%d of the %d decided by under %g R (fragile)" % (h["fragile"], h["decided"]["n"], 0.05)
    out.append("  Decided: %s; %s." % (_dec(h["decided"]), frag))
    sv = h.get("sensitivity")
    if sv:
        out.append("  One-tick sensitivity: the entry 1 cent higher flips %d outcome%s, 1 cent lower flips %d (of %d)."
                   % (sv["up"]["flips"], "" if sv["up"]["flips"] == 1 else "s", sv["down"]["flips"], sv["of"]))
    if h.get("by_year"):
        rows = ["%s %s" % (y, _iv(v["net"])) for y, v in sorted(h["by_year"].items()) if v["net"]]
        out.append("  By year, net R a trade: " + "; ".join(rows) + ".")
        if h.get("by_year_note"):
            out.append("  Note: " + h["by_year_note"] + ".")
    ctrl = h.get("control")
    if ctrl:
        skip = ", ".join("%d %s" % (v, k.replace("_", " ")) for k, v in sorted(ctrl["skipped"].items()) if v)
        if ctrl.get("net"):
            out.append("  Random-entry control (%d draws a firing session, the rule's risk percent, target multiple "
                       "and flat-by): %d trades, net average R %s; %s.%s"
                       % (ctrl["draws"], ctrl["trades"], _iv(ctrl["net"]), _dec(ctrl["decided"]),
                          (" Skipped: %s." % skip) if skip else ""))
        else:
            out.append("  Random-entry control: no control trade%s." % ((" (skipped: %s)" % skip) if skip else ""))
    b = h.get("baseline")
    if b:
        if b.get("net"):
            out.append("  Baseline, buy any morning strength (the last opening-range bar's close, every session; a "
                       "diagnostic, not a verdict): %d trades, net average R %s; %s."
                       % (b["trades"], _iv(b["net"]), _dec(b["decided"])))
        else:
            out.append("  Baseline, buy any morning strength: no trade (%d sessions skipped)." % b["skipped"])
    return out


def report(doc):
    p, m, h = doc["plan"], doc["mc"], doc["history"]
    long = p["side"] == "buy"
    until = clock12(int(m["until"][:2]) * 60 + int(m["until"][3:]))
    wd = WEEKDAYS[datetime.date.fromisoformat(p["date"]).weekday()]
    r = p.get("target_r")
    c = doc.get("costs") or {}
    if p.get("target") is not None:
        tgt = "target %.2f (%sR, risk %.2f a share)" % (p["target"], ("%g" % r), p["risk_per_share"])
    else:
        tgt = "no target, out by %s (risk %.2f a share)" % (until, p["risk_per_share"])
    gap = m.get("gap_fill") == "open"
    if p.get("target") is not None:
        rwords = "%sR at the target, -1R at the stop%s" % (("+%g" % m["r_at_target"]),
                                                          ", worse on a gap through it" if gap else "")
    else:
        rwords = "-1R at the stop%s, else the price at %s" % (", worse on a gap through it" if gap else "", until)
    d = doc["data"]
    lines = [
        "%s %s, %s %s: entry %.2f at %s (bar %d), stop %.2f, %s."
        % (p["symbol"], p["side"], wd, p["date"], p["entry"], p["entry_time"], p["entry_bar"], p["stop"], tgt),
        _measure("costs").card_line(c.get("card")) if c.get("on") else "Costs: off (--no-costs): gross numbers only.",
        "",
    ]
    lines += history_lines(doc)
    lines.append("  Data: %s (%s); %d early-close session(s) used, %d incomplete dropped."
                 % (d.get("source"), (d.get("adjustment") or {}).get("basis"), len(d.get("early_close_used") or []),
                    len(d.get("incomplete_dropped") or [])))
    ew = h.get("entry_window")
    if ew:
        lines.append("  Entry window: the rule fires, and a control enters, on bars closing by %s (bar %d; bar %d on an "
                     "early close); scored to %s." % (ew["no_entries_after"], ew["bar"], ew["early_close_bar"], until))
    lines += ["", doc["verdict_history"]["text"], doc["verdict_control"]["text"], ""]
    lines += [
        "%s replays of the rest of the session, %s to %s (%d five-minute bars), seed %d."
        % ("{:,}".format(m["replays"]), p["entry_time"], until, m["bars_left"], m["seed"]),
        "Each bar is drawn whole from %s's own 5-min bars at the same time of day (+-%d bars) over its last "
        "%d full sessions (%s to %s)." % (p["symbol"], m["window"], m["pool_sessions"], m["pool_from"], m["pool_to"]),
        "",
        "  target first   %s" % pc(m["p_target"]),
        "  stop first     %s" % pc(m["p_stop"]),
        "  neither        %-8s still open at %s" % (pc(m["p_neither"]), until),
        "  green          %-8s target first, or %s the entry at %s" % (pc(m["p_green"]),
                                                                       "above" if long else "below", until),
        "",
        "  Price at %s: median %.2f, 90 %% of replays between %.2f and %.2f."
        % (until, m["median_close"], m["p5_close"], m["p95_close"]),
        "  Average R: %+.3f (R = the %.2f risk: %s).%s"
        % (m["avg_R"], p["risk_per_share"], rwords,
           (" After the %.3f R round trip: %+.3f." % (c["card"]["cost_r"], m["avg_R_net"]))
           if c.get("on") and "avg_R_net" in m else ""),
        "",
    ]
    lines += [doc["mc_shape"]] + list(doc.get("mc_notes") or []) + [""]
    for w in doc.get("warnings") or []:
        lines.append("Note: " + w + ".")
    if d.get("incomplete_dropped"):
        lines.append("Left out %d short session(s) (incomplete, not an early close on the calendar): %s."
                     % (len(d["incomplete_dropped"]), ", ".join(x["date"] for x in d["incomplete_dropped"])))
    if d.get("early_close_used"):
        lines.append("Used %d early-close session(s) in the history, scored to the 1:00 PM close: %s."
                     % (len(d["early_close_used"]), ", ".join(x["date"] for x in d["early_close_used"])))
    lines.append(doc["note"] + " Repeat this run with --seed %d." % m["seed"])
    return lines


def render_chart(doc, height=17):
    """ASCII fan chart of the bands: one column per 5-min bar."""
    p, m = doc["plan"], doc["mc"]
    bands, times = m["bands"], m["band_times"]
    levels = [p["stop"]] + ([p["target"]] if p.get("target") is not None else [])
    lo = min([b[0] for b in bands] + levels)
    hi = max([b[4] for b in bands] + levels)
    pad = (hi - lo) * 0.04 or 0.01
    lo, hi = lo - pad, hi + pad
    step = (hi - lo) / (height - 1)

    def row(price):
        return max(0, min(height - 1, int(round((hi - price) / step))))
    grid = [[" "] * len(bands) for _ in range(height)]
    for j, b in enumerate(bands):
        r5, r25, r50, r75, r95 = [row(x) for x in b]
        for r in range(r95, r5 + 1):
            grid[r][j] = "."
        for r in range(r75, r25 + 1):
            grid[r][j] = ":"
        grid[r50][j] = "*"
    marks = {row(p["stop"]): "stop"}
    if p.get("target") is not None:
        marks[row(p["target"])] = "target"
    if row(p["entry"]) not in marks:
        marks[row(p["entry"])] = "entry"
    for r in [row(x) for x in levels]:
        grid[r] = ["-" if ch == " " else ch for ch in grid[r]]
    out = ["%s %s, %s replay paths from the %s entry (seed %d)" % (
        p["symbol"], p["date"], "{:,}".format(m.get("band_paths", BAND_PATHS)), p["entry_time"], m["seed"])]
    for r in range(height):
        label = marks.get(r)
        price = {"target": p["target"], "stop": p["stop"], "entry": p["entry"]}.get(label, hi - r * step)
        left = ("%9.2f |" % price) if (label or r in (0, height - 1)) else "          |"
        out.append(left + "".join(grid[r]) + ("  " + label if label else ""))
    axis = [" "] * len(bands)
    for j in sorted({0, len(bands) // 2, len(bands) - 1}):
        t = times[j]
        hh, mm = int(t[:2]), t[3:]
        lab = "%d:%s" % (hh % 12 or 12, mm)
        s = max(0, min(j, len(bands) - len(lab)))
        axis[s:s + len(lab)] = list(lab)
    out.append("          +" + "-" * len(bands))
    out.append("           " + "".join(axis))
    out.append("* median   : middle half of the paths   . 90 % of the paths   - stop and target")
    return out


# ---------------------------------------------------------------- commands

def _write(path, doc):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1)
        fh.write("\n")


def read_config(path):
    """trader/config.json (for the costs block and the max loss the share basis uses), {} when absent."""
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except ValueError as e:
        raise TMError("%s is not valid JSON: %s" % (path, e))
    return doc if isinstance(doc, dict) else {}


def compute(a):
    now = parse_now(a.now)
    plan = load_plan(a, now)
    cfg = read_config(getattr(a, "config", None))
    if a.offline:
        text, source = read_offline(a.offline, plan["symbol"]), "offline"
    elif a.source == "massive":
        text, source = _mjonir().history_text(plan["symbol"], plan["date"], a.sessions, a.years), "massive"
    else:
        text, source = fetch_chart(plan["symbol"]), "yahoo"
    card = None
    if not a.no_costs:
        adv = note = None
        if not plan.get("costs"):
            if a.source == "massive":   # ADV$ for the slippage tier from Massive, strictly before the plan day
                try:
                    adv = _mjonir().adv_usd(plan["symbol"], plan["date"])
                    note = "Massive: mean close x volume over the 20 sessions before %s" % plan["date"]
                except TMError as e:
                    note = "unverified: %s" % e
            else:
                note = "unverified: --source yahoo has no ADV (the most expensive tier)"
        card = cost_card_for(plan, "auto", cfg, adv, note)
    fb = plan.get("flat_by")
    try:
        later = fb and parse_clock(a.until or "16:00", "--until") > parse_clock(fb, "the plan's flat_by")
    except TMError:
        later = False
    if later:
        print("timemachine.py: note: --until %s is later than the plan's flat-by %s: the history scores each trade "
              "past the time the plan exits (give --until %s)" % (a.until or "16:00", fb, fb), file=sys.stderr)
    nea = getattr(a, "no_entries_after", None) or cfg.get("no_entries_after") or "15:30"
    return time_machine(text, plan, now, a.replays, a.seed, a.window, a.until, source, card, a.gap_fill,
                        a.control_draws, cfg, no_entries_after=nea)


def cmd_run(a):
    doc = compute(a)
    if a.write:
        _write(a.write, doc)
    if a.json:
        slim = dict(doc, mc={k: v for k, v in doc["mc"].items() if k != "sample_paths"})
        print(json.dumps(slim, indent=2))
    else:
        print("\n".join(report(doc)))
        if a.write:
            print("Wrote %s." % a.write)
        print("Next: /trader-budget sizes it to your budget and your max loss per trade.")
    return 0


def cmd_chart(a):
    if a.from_file:
        if not os.path.exists(a.from_file):
            raise TMError("no %s: run timemachine.py run --write first" % a.from_file)
        try:
            with open(a.from_file, encoding="utf-8") as fh:
                doc = json.load(fh)
            doc["mc"]["bands"]
        except (ValueError, KeyError, TypeError):
            raise TMError("%s is not a time machine result" % a.from_file)
    else:
        doc = compute(a)
    print("\n".join(render_chart(doc)))
    print("\n".join([(doc.get("verdict_history") or {}).get("text", ""),
                      (doc.get("verdict_control") or {}).get("text", ""), doc.get("mc_shape", "")]
                     + list(doc.get("mc_notes") or [])))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Time Machine: replay a planned day trade (trader-timemachine).")
    sub = ap.add_subparsers(dest="cmd")

    def common(p):
        p.add_argument("--plan", default="trader/plan.json", help="the plan from trader-exit")
        p.add_argument("--symbol", help="or give the plan as flags: ticker")
        p.add_argument("--side", default="buy", choices=["buy", "sell"])
        p.add_argument("--date", help="the plan's day, YYYY-MM-DD (default today, New York)")
        p.add_argument("--entry", type=float)
        p.add_argument("--stop", type=float)
        p.add_argument("--target", type=float)
        p.add_argument("--exit", choices=["target", "close"], help="close: no target, out at the stop or the close")
        p.add_argument("--entry-time", help='the entry bar\'s close, e.g. "10:15 AM"')
        p.add_argument("--setup", default="orb")
        p.add_argument("--or-minutes", type=int, default=15)
        p.add_argument("--stop-rule", default="auto", choices=["auto", "or_mid", "or_low", "or_high", "pct"])
        p.add_argument("--replays", type=int, default=10000)
        p.add_argument("--seed", type=int, default=19)
        p.add_argument("--window", type=int, default=2, help="draw from the same time of day +- this many bars")
        p.add_argument("--until", help="end each replay at this time (default 16:00, the close)")
        p.add_argument("--offline", metavar="FILE", help="a saved Yahoo chart JSON (.json or .json.gz), no network")
        p.add_argument("--source", choices=["yahoo", "massive"], default=os.environ.get("TRADER_SOURCE") or "yahoo")
        p.add_argument("--sessions", type=int, default=60, help="massive: sessions up to the plan's day (60 = Yahoo's 60d)")
        p.add_argument("--years", type=float, help="massive: every session of the N years before the plan's day")
        p.add_argument("--no-costs", action="store_true", help="gross only: no slippage, spread or commission")
        p.add_argument("--gap-fill", choices=["open", "stop"], default="open",
                       help="a bar opening through the stop fills at its open (default) or at the stop (upstream)")
        p.add_argument("--control-draws", type=int, default=3, help="random-entry control trades a firing session")
        p.add_argument("--no-entries-after", metavar="HH:MM",
                       help="the last entry bar's close for the history and the control (default the config's "
                            "no_entries_after, else 15:30; 16:00 = upstream, no cap)")
        p.add_argument("--config", default="trader/config.json", help="the costs block and the max loss")
        p.add_argument("--now", help='pretend it is this time ("2026-10-19 10:15" New York, or ISO with Z)')

    p = sub.add_parser("run", help="replay the plan: 10,000 simulated sessions plus the history")
    common(p)
    p.add_argument("--json", action="store_true")
    p.add_argument("--write", nargs="?", const="trader/timemachine.json", metavar="PATH",
                   help="save the result (default trader/timemachine.json)")
    p = sub.add_parser("chart", help="ASCII fan chart of the replays")
    common(p)
    p.add_argument("--from", dest="from_file", nargs="?", const="trader/timemachine.json", metavar="PATH",
                   help="draw a saved result instead of running again")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    try:
        return {"run": cmd_run, "chart": cmd_chart}[a.cmd](a)
    except TMError as e:
        print("timemachine.py: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
