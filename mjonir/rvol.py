"""The RVOL list of docs/PREREG_RVOL_ORB.md (sections 3.3, 3.4, 4.3 and 4.4), one definition shared by the live
scanner (trader-scanner/scan.py rvol) and the study (tools/rvol_study.py), P8. Stdlib only, Python 3.8 syntax.

    floors_stage(symbols, daily, split_hit, floors, adv_n)   the floors from the sessions STRICTLY before D
    bar_stage(passed, first_bars, history, rvol_n, gap)       the first bar of D, the gap guard, the RVOL history
    rank(eligible, top)                                       the day's list L(D): RVOL descending, ties by ticker,
                                                              direction-agnostic; then fire = the first bar is up
                                                              (the day's orders: a buy-stop at its high plus TICK)
    stop_fill(bars, level, first, until)                      a buy-stop's fill: (k, entry) or None (no_fill)
    atr_of(rows, n)                                           trader-exit daily_atr's arithmetic
    direction(o, c)                                           "up" only when the close is strictly above the open
                                                              on unrounded values; a doji is not up
    first_bar(rows, day)                                      the 09:30 bucket of a session's 5-minute rows

The funnel, in order; a name-day is counted under the FIRST cause it fails:
  insufficient_history  fewer than adv_n daily rows strictly before D, or one with no positive volume
  split_guard           a split executed inside [the first session of that window, D]
  below_price           the close of the session before D under floors.min_price
  below_adv_usd         the mean of close x volume over the window under floors.min_adv_usd
  below_adv_shares      the mean volume over the window under floors.min_avg_volume
  below_atr             the simple mean of ATR_N true ranges (the window's last ATR_N + 1 rows) under
                        floors.min_atr_usd (the paper's ATR floor; None turns it off)
  no_first_bar          D's 09:30 bucket absent, without a positive volume, or without an open and a close
  gap_guard             that bucket's open under GAP_GUARD[0] or over GAP_GUARD[1] times the prior close
  rvol_history_short    one of the rvol_n prior sessions' 09:30 buckets absent or without a positive volume
  below_rvol            the RVOL under min_rvol (RVOL_MIN, the paper's floor; None turns it off)
No row of session D is read before the first-bar stage: the floors use the window before D only.

scan(fetch, cal, day, symbols, floors, ...) is the live scanner's two stages: one full-market snapshot ranks
day volume over the window's mean volume to a shortlist (a past day has no snapshot: every name past the
floors goes to stage 2, or a --shortlist by the day's whole-session volume), then the exact first-bar RVOL
from mjonir.bars.bars_5m on the shortlist. Its data
(Massive, adjusted) differ from the study's (the flat files, unadjusted); its list can differ from the study's
on a few names a day (PREREG section 11). The rules do not differ.
"""

import datetime as _dt
from concurrent.futures import ThreadPoolExecutor

from . import calendar as K

ADV_N = 20
RVOL_N = 14
TOP_K = 20
SHORTLIST = 200
GAP_GUARD = (0.4, 2.5)
P_MIN = 5.0
ADV_USD_MIN = 20000000.0
ADV_SH_MIN = 1000000.0
ATR_N = 14
ATR_MIN = 0.50
RVOL_MIN = 1.0
TICK = 0.01
FLOOR_CAUSES = ("insufficient_history", "split_guard", "below_price", "below_adv_usd", "below_adv_shares", "below_atr")
BAR_CAUSES = ("no_first_bar", "gap_guard", "rvol_history_short", "below_rvol")
CAUSES = FLOOR_CAUSES + BAR_CAUSES
WORKERS = 8
OPEN = _dt.time(9, 30)



# ---------------------------------------------------------------- the rules

def direction(o, c):
    """'up' when the close is strictly above the open (unrounded), 'down' under it, 'doji' when equal."""
    if c > o:
        return "up"
    if c < o:
        return "down"
    return "doji"


def is_up(o, c):
    return direction(o, c) == "up"


def _fb(fb):
    """A first bar as a dict {o, h, l, c, v} (h and l may be None: the study's store keeps o, c and v)."""
    if fb is None:
        return None
    if isinstance(fb, dict):
        return {"o": fb.get("o"), "h": fb.get("h"), "l": fb.get("l"), "c": fb.get("c"), "v": fb.get("v")}
    o, h, l, c, v = fb
    return {"o": o, "h": h, "l": l, "c": c, "v": v}


def atr_of(rows, n=ATR_N):
    """trader-exit daily_atr's arithmetic: the mean of n true ranges from the last n + 1 daily rows (o, h, l, c, v),
    TR = max(high - low, |high - prior close|, |low - prior close|)."""
    rows = rows[-(n + 1):]
    trs = [max(r[1] - r[2], abs(r[1] - rows[i][3]), abs(r[2] - rows[i][3])) for i, r in enumerate(rows[1:])]
    return sum(trs) / len(trs)


def stop_fill(bars, level, first, until):
    """A buy-stop at `level`, live from bar `first` through bar `until` (positions in `bars`, dicts {o,h,l,c} or
    (t, o, h, l, c, v) tuples): (k, entry) for the first bar whose high reaches the level, filled at max(level,
    its open), unrounded (a bar opening past the level fills at its open); None when no bar reaches it."""
    from .outcomes import ohlc
    for k in range(int(first), min(int(until), len(bars) - 1) + 1):
        o, h, _l, _c = ohlc(bars[k])
        if not h < level:
            return k, max(level, o)
    return None


def floors_stage(symbols, daily, split_hit, floors, adv_n=ADV_N):
    """The floors of section 3.3 and the split guard of 3.4, from the adv_n sessions strictly before D.
    daily(sym) -> that window's rows present, oldest first, each (o, h, l, c, v) (a missing session is simply
    absent); split_hit(sym) -> True when a split executed inside [the window's first session, D];
    floors: {min_price, min_adv_usd, min_avg_volume, min_atr_usd (absent or None: off)}.
    Returns ({sym: {price, adv_usd, adv_shares, atr, rows}}, {cause: n}) over the symbols, sorted."""
    counts = dict((c, 0) for c in FLOOR_CAUSES)
    passed = {}
    for sym in sorted(set(symbols)):
        rows = daily(sym) or []
        if len(rows) < adv_n or any(not (r[4] or 0) > 0 or r[3] is None for r in rows[-adv_n:]):
            counts["insufficient_history"] += 1
            continue
        rows = rows[-adv_n:]
        if split_hit(sym):
            counts["split_guard"] += 1
            continue
        price = float(rows[-1][3])
        adv_usd = sum(float(r[3]) * float(r[4]) for r in rows) / adv_n
        adv_shares = sum(float(r[4]) for r in rows) / adv_n
        if price < floors["min_price"]:
            counts["below_price"] += 1
            continue
        if adv_usd < floors["min_adv_usd"]:
            counts["below_adv_usd"] += 1
            continue
        if adv_shares < floors["min_avg_volume"]:
            counts["below_adv_shares"] += 1
            continue
        atr = atr_of(rows, ATR_N)
        if floors.get("min_atr_usd") is not None and atr < floors["min_atr_usd"]:
            counts["below_atr"] += 1
            continue
        passed[sym] = {"price": price, "adv_usd": adv_usd, "adv_shares": adv_shares, "atr": atr, "rows": rows}
    return passed, counts


def bar_stage(passed, first_bars, history, rvol_n=RVOL_N, gap=GAP_GUARD, rows=True, min_rvol=RVOL_MIN):
    """Section 4.3 and the gap guard of 3.4 on the names past the floors. first_bars: {sym: first bar of D};
    history(sym) -> the 09:30 volumes of the rvol_n sessions strictly before D, oldest first, None where a
    session has no bucket. Returns ([{symbol, rvol, first_bar, direction, price, adv_usd, adv_shares}],
    {cause: n}), sorted by symbol. rows=False (the study's counts-only mode) returns the eligible SYMBOLS
    only: no direction is read and no RVOL is kept for any name (the RVOL_MIN comparison is made, its value is
    not returned)."""
    counts = dict((c, 0) for c in BAR_CAUSES)
    out = []
    for sym in sorted(passed):
        p = passed[sym]
        fb = _fb(first_bars.get(sym))
        if fb is None or fb["o"] is None or fb["c"] is None or not (fb["v"] or 0) > 0:
            counts["no_first_bar"] += 1
            continue
        if fb["o"] < gap[0] * p["price"] or fb["o"] > gap[1] * p["price"]:
            counts["gap_guard"] += 1
            continue
        hist = list(history(sym) or [])
        if len(hist) < rvol_n or any(h is None or not h > 0 for h in hist[-rvol_n:]):
            counts["rvol_history_short"] += 1
            continue
        hist = hist[-rvol_n:]
        mean = sum(float(h) for h in hist) / rvol_n
        if min_rvol is not None and float(fb["v"]) < min_rvol * mean:
            counts["below_rvol"] += 1
            continue
        if not rows:
            out.append(sym)
            continue
        out.append({"symbol": sym, "rvol": float(fb["v"]) / mean, "first_bar": fb,
                    "direction": direction(fb["o"], fb["c"]), "price": p["price"], "adv_usd": p["adv_usd"],
                    "adv_shares": p["adv_shares"], "atr": p.get("atr")})
    return out, counts


def rank(eligible, top=TOP_K):
    """L(D): the first `top` by RVOL descending, ties by ticker ascending, whatever the first bar did; each row
    gets its rank (1 = the highest RVOL) and fire = its first bar is up (section 4.4)."""
    rows = sorted(eligible, key=lambda r: (-r["rvol"], r["symbol"]))[:int(top)]
    out = []
    for i, r in enumerate(rows, 1):
        out.append(dict(r, rank=i, fire=is_up(r["first_bar"]["o"], r["first_bar"]["c"])))
    return out


def first_bar(rows, day):
    """The 09:30 bucket of `day` from 5-minute rows (t_ms START, o, h, l, c, v) or dicts, else None."""
    t0 = K.ms_of(_dt.datetime.combine(K.as_date(day), OPEN, tzinfo=K.ET))
    for r in rows:
        t = r["t"] if isinstance(r, dict) else r[0]
        if int(t) == t0:
            if isinstance(r, dict):
                return {"o": r["o"], "h": r["h"], "l": r["l"], "c": r["c"], "v": r["v"]}
            return {"o": r[1], "h": r[2], "l": r[3], "c": r[4], "v": r[5]}
    return None


# ---------------------------------------------------------------- the live scanner

class Fetch(object):
    """The live scanner's questions to Massive, in one place (the tests serve a synthetic store instead):
    grouped(day) {SYM: {o,h,l,c,v}} (grouped daily, cached), splits(since) rows, snapshot(day) ({SYM: day
    volume}, counts), first_bars(symbols, days) ({SYM: {date_iso: bar}}, {SYM: error}) from bars.bars_5m."""

    def __init__(self, client=None, cal=None):
        from . import massive as M
        self.client = client or M.Client()
        self.cal = cal or K.Calendar.load()

    def grouped(self, day):
        from . import cache as CA
        from .yahoo_shape import grouped_day
        c = CA.Cache()
        try:
            return grouped_day(self.client, day, c)
        finally:
            c.close()

    def splits(self, since):
        return self.client.splits(since=since)

    def snapshot(self, day):
        """({SYM: day volume} of the rows whose day bar is session `day`, {rows, other_day})."""
        from .yahoo_shape import snapshot_day_is
        rows = self.client.snapshot_all()
        out, other = {}, 0
        for sym, r in rows.items():
            if snapshot_day_is(r, day):
                out[sym] = float(((r.get("day") or {}).get("v")) or 0.0)
            else:
                other += 1
        return out, {"rows": len(rows), "other_day": other}

    def first_bars(self, symbols, days):
        from . import bars as B
        from .yahoo_shape import ERRORS
        got, errors = {}, {}

        def one(sym):
            try:
                rows = B.bars_5m(sym, days[0], days[-1], rth_only=True, client=self.client, cal=self.cal,
                                 source="api")
            except ERRORS as e:
                return sym, None, str(e)
            per = {}
            for d in days:
                fb = first_bar(rows, d)
                if fb is not None:
                    per[d.isoformat()] = fb
            return sym, per, None
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            for sym, per, err in ex.map(one, sorted(symbols)):
                if err is None:
                    got[sym] = per
                else:
                    errors[sym] = err
        return got, errors

    def requests(self):
        return self.client.requests


def make_fetch(cal=None):
    """The live Fetch (the tests replace this function)."""
    return Fetch(cal=cal)


def split_days(rows):
    """{TICKER: [execution dates]} from split rows."""
    out = {}
    for r in rows or []:
        t = str(r.get("ticker") or "").upper()
        d = str(r.get("execution_date") or "")[:10]
        if t and d:
            out.setdefault(t, []).append(d)
    return out


def scan(fetch, cal, day, symbols, floors, top=TOP_K, lookback=RVOL_N, adv_n=ADV_N, shortlist=None,
         live=True, gap=GAP_GUARD, say=None):
    """The live list for session `day`. Stage 1 (live): one snapshot, day volume over the window's mean volume,
    the `shortlist` highest past the floors (ties by ticker; a name with no snapshot row is counted no_snapshot).
    A past day (live False) has no snapshot: every name past the floors goes on, or, with a shortlist, the
    highest by the day's whole-session volume over the mean (a replay-only proxy the 9:35 snapshot cannot know;
    the floors still read only the sessions before the day). Stage 2: the 09:30 buckets of D and the `lookback`
    sessions before it from bars_5m, then bar_stage and rank; say(text) hears the stage-2 request count first.
    shortlist None: SHORTLIST live, every name past the floors on a replay. Returns the document scan.py writes
    (rows, fires, counts)."""
    day = K.as_date(day)
    if live and shortlist is None:
        shortlist = SHORTLIST
    prev = cal.prev_session(day)
    adv_days = cal.sessions_back(prev, int(adv_n))
    hist_days = cal.sessions_back(prev, int(lookback))
    grouped = dict((d, fetch.grouped(d)) for d in adv_days)
    sp = split_days(fetch.splits(adv_days[0].isoformat()))
    lo, hi = adv_days[0].isoformat(), day.isoformat()

    def daily(sym):
        rows = []
        for d in adv_days:
            r = grouped[d].get(sym)
            if r is not None:
                rows.append((r.get("o"), r.get("h"), r.get("l"), r.get("c"), r.get("v")))
        return rows

    def split_hit(sym):
        return any(lo <= x <= hi for x in sp.get(sym, ()))
    passed, c_floor = floors_stage(symbols, daily, split_hit, floors, adv_n)
    stage1 = {"candidates": len(set(symbols)), "passed_floors": len(passed)}
    if live or shortlist:
        if live:
            vols, meta = fetch.snapshot(day)
            basis = "snapshot: day volume over the %d-session mean volume" % adv_n
        else:
            g = fetch.grouped(day)
            vols = dict((t, float(r.get("v") or 0.0)) for t, r in g.items())
            meta = {"rows": len(g), "other_day": 0}
            basis = ("replay with a shortlist: the day's whole-session volume (grouped daily) over the %d-session "
                     "mean volume, a proxy the live 9:35 snapshot cannot know; the floors still read only the "
                     "sessions before the day" % adv_n)
        ratios, no_snap, zero = [], 0, 0
        for sym in sorted(passed):
            v = vols.get(sym)
            if v is None:
                no_snap += 1
            elif not v > 0:
                zero += 1
            else:
                ratios.append((-(v / passed[sym]["adv_shares"]), sym))
        ratios.sort()
        short = [s for _, s in ratios[:int(shortlist)]]
        stage1.update(basis=basis, snapshot_rows=meta.get("rows"), snapshot_other_day=meta.get("other_day"),
                      no_snapshot=no_snap, zero_volume=zero, with_volume=len(ratios), shortlist=len(short),
                      shortlist_size=int(shortlist))
        vx = dict((s, -r) for r, s in ratios) if live else {}
    else:
        short = sorted(passed)
        stage1.update(basis="replay: a past day has no snapshot, every name past the floors goes to stage 2",
                      shortlist=len(short), shortlist_size=None)
        vx = {}
    if say is not None:
        say("Stage 2: 5-minute bars for %d names over %d sessions: about %d requests (a bar range and a split "
            "check a name; sessions already cached are not asked again)."
            % (len(short), len(hist_days) + 1, 2 * len(short)))
    bars, errors = fetch.first_bars(short, hist_days + [day]) if short else ({}, {})
    firsts = dict((s, (bars.get(s) or {}).get(day.isoformat())) for s in short if s in bars)
    hist_iso = [d.isoformat() for d in hist_days]

    def history(sym):
        per = bars.get(sym) or {}
        return [(per.get(d) or {}).get("v") for d in hist_iso]
    eligible, c_bar = bar_stage(dict((s, passed[s]) for s in short if s in bars), firsts, history, lookback, gap)
    listed = rank(eligible, top)
    rows = []
    for r in listed:
        fb = r["first_bar"]
        rows.append({"symbol": r["symbol"], "rvol": r["rvol"], "rank": r["rank"],
                     "first_bar": {"o": fb["o"], "h": fb["h"], "l": fb["l"], "c": fb["c"], "v": fb["v"]},
                     "direction": r["direction"], "adv_usd": r["adv_usd"], "price": r["price"], "fire": r["fire"],
                     "level": (fb["h"] + TICK) if r["fire"] else None, "atr": r.get("atr"),
                     "volume_x": vx.get(r["symbol"])})
    funnel = dict(c_floor)
    funnel.update(c_bar)
    funnel["fetch_failed"] = len(errors)
    funnel["eligible"] = len(eligible)
    return {"date": day.isoformat(), "live": bool(live), "stage1": stage1, "funnel": funnel,
            "fetch_failed": dict(sorted(errors.items())), "rows": rows,
            "fires": [r["symbol"] for r in rows if r["fire"]],
            "windows": {"adv": [adv_days[0].isoformat(), adv_days[-1].isoformat()],
                        "rvol_history": [hist_days[0].isoformat(), hist_days[-1].isoformat()]},
            "params": {"top": int(top), "lookback": int(lookback), "adv_sessions": int(adv_n), "min_rvol": RVOL_MIN,
                       "tick": TICK,
                       "shortlist": int(shortlist) if shortlist else None, "gap_guard": list(gap),
                       "floors": dict(floors)}}
