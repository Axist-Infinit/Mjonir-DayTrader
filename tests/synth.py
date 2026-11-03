"""Synthetic sessions for the chunk 2 tests (no network, no stores).

make_session(date, seed, early_close=False, gap_at=None, both_touch_at=None, start=100.0)
    -> 78 (or 42) five-minute bar dicts {t, date, slot, start, o, h, l, c, v}, a seeded random walk.
    gap_at=i       bar i opens 3% under bar i-1's close (a gap through any nearby stop)
    both_touch_at=i  bar i spans 3% each side of bar i-1's close (touches a nearby stop AND target)
make_store(sessions) -> a stand-in for mjonir.bars.bars_5m serving those sessions as tuples
chart_text(symbol, sessions, regular_market_time=None) -> a Yahoo v8 document (the time machine's input)
breakout_session(date, seed, ...) -> a session whose bar 4 closes above its 15-minute opening range
"""

import datetime as dt
import json
import random

from mjonir import calendar as K

OPEN = dt.time(9, 30)


def _ms(day, slot):
    local = dt.datetime.combine(day, OPEN, tzinfo=K.ET) + dt.timedelta(minutes=5 * slot)
    return K.ms_of(local)


def make_session(date, seed, early_close=False, gap_at=None, both_touch_at=None, start=100.0, drift=0.0,
                 vol=0.002):
    day = K.as_date(date)
    rng = random.Random("%s:%s" % (seed, day))
    n = 42 if early_close else 78
    bars, prev = [], float(start)
    for i in range(n):
        o = prev * (1 + rng.gauss(0, vol / 4))
        if gap_at is not None and i == gap_at:
            o = prev * 0.97
        c = o * (1 + drift + rng.gauss(0, vol))
        h = max(o, c) * (1 + abs(rng.gauss(0, vol / 2)))
        lo = min(o, c) * (1 - abs(rng.gauss(0, vol / 2)))
        if both_touch_at is not None and i == both_touch_at:
            h, lo = prev * 1.03, prev * 0.97
        t = _ms(day, i)
        bars.append({"t": t, "date": day.isoformat(), "slot": i,
                     "start": K.et_of_ms(t).strftime("%H:%M"), "o": round(o, 4), "h": round(h, 4),
                     "l": round(lo, 4), "c": round(c, 4), "v": 1000 + rng.randrange(1000)})
        prev = bars[-1]["c"]
    return bars


def breakout_session(date, seed, early_close=False, start=100.0, up=True):
    """A session whose bar 4 (the 9:50 bar) closes 0.5% above the 15-minute opening range high (or under
    the low), the rest a random walk from there."""
    s = make_session(date, seed, early_close=early_close, start=start)
    oh = max(b["h"] for b in s[:3])
    ol = min(b["l"] for b in s[:3])
    b = s[4]
    c = oh * 1.005 if up else ol * 0.995
    b.update(o=b["o"], c=round(c, 4), h=round(max(b["h"], c), 4), l=round(min(b["l"], c), 4))
    s[3].update(c=min(s[3]["c"], round(oh, 4)) if up else max(s[3]["c"], round(ol, 4)))
    s[3].update(h=max(s[3]["h"], s[3]["c"]), l=min(s[3]["l"], s[3]["c"]))
    return s


def as_tuples(bars):
    return [(b["t"], b["o"], b["h"], b["l"], b["c"], float(b["v"])) for b in bars]


def make_store(sessions, source="api", adjusted=True, as_of="2026-10-19"):
    """A bars_5m stand-in: bars_5m(symbol, start, end, rth_only=True, ..., info=None) over these sessions.
    It records each call in .calls and raises the data layer's DataError on an empty answer (P10)."""
    from mjonir.yahoo_shape import DataError
    by_day = {}
    for s in sessions:
        by_day.setdefault(s[0]["date"], []).extend(s)

    def bars_5m(symbol, start, end, rth_only=True, client=None, cal=None, source_=None, cache=None, info=None,
                **kw):
        bars_5m.calls.append((symbol, K.as_date(start), K.as_date(end)))
        a, b = K.as_date(start).isoformat(), K.as_date(end).isoformat()
        rows = [x for d in sorted(by_day) if a <= d <= b for x in by_day[d]]
        if info is not None:
            info.clear()
            info.update(source=source, adjusted=adjusted, as_of=as_of)
        if not rows:
            raise DataError("no 5-minute bars for %s between %s and %s" % (symbol, a, b))
        return as_tuples(rows)
    bars_5m.calls = []
    return bars_5m


def chart_text(symbol, sessions, regular_market_time=None, mjonir=None):
    """A Yahoo v8 chart document holding every bar of these sessions (the time machine reads it)."""
    bars = [b for s in sessions for b in s]
    bars.sort(key=lambda b: b["t"])
    meta = {"symbol": symbol, "dataGranularity": "5m", "range": "%dd" % len(sessions),
            "regularMarketTime": regular_market_time or (bars[-1]["t"] // 1000 + 300)}
    if mjonir is not None:
        meta["mjonir"] = mjonir
    q = {k: [b[f] for b in bars] for k, f in (("open", "o"), ("high", "h"), ("low", "l"), ("close", "c"),
                                               ("volume", "v"))}
    return json.dumps({"chart": {"result": [{"meta": meta, "timestamp": [b["t"] // 1000 for b in bars],
                                             "indicators": {"quote": [q]}}], "error": None}})


def sessions_back(end, n, cal=None):
    """The n sessions ending at `end` (dates), from the seed calendar."""
    cal = cal or K.Calendar()
    return cal.sessions_back(end, n)
