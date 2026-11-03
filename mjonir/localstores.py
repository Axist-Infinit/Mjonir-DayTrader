"""Read-only local history: the Kalex 5-minute store and the Infinit minute flat files. Stdlib only.

* Kalex (``/home/axis/Kalex/data/intraday/intraday_5m.sqlite3``): ``bars(symbol, t ms, o, h, l, c, v,
  vw, n)`` PK(symbol, t), 04:00 to 19:55 ET rows, ADJUSTED as of its last fetch (2026-07-15). Opened
  through ``config.ro_connect`` only (``mode=ro`` + ``query_only``): never a second writer. ``vw`` is
  NULL on most rows. Rows come back RAW (extended hours included); the writer applies the RTH filter.
* Flat files (``minute_flatfiles/YYYY-MM-DD.csv.gz``): every US stock's 1-minute bars for one day,
  UNADJUSTED, columns ``ticker,volume,open,close,high,low,window_start(ns),transactions``.
  ``flatfile_bulk`` reads each day file ONCE for many symbols.

A chart file comes from one source (CLAUDE.md hazard 8): these readers never mix.
"""

import csv
import datetime as _dt
import gzip
import os

from . import calendar as K
from . import config as C

FIVE_MIN_MS = 300000


class StoreError(RuntimeError):
    pass


# ---------------------------------------------------------------- Kalex 5m

def kalex_connect(path=None):
    return C.ro_connect(path or C.kalex_5m_path())


def kalex_coverage(symbol, path=None):
    """{symbol, first_t, last_t, n, first_day, last_day} from the bars themselves, or None."""
    conn = kalex_connect(path)
    try:
        row = conn.execute("SELECT MIN(t), MAX(t), COUNT(*) FROM bars WHERE symbol=?", (symbol.upper(),)).fetchone()
    finally:
        conn.close()
    if not row or not row[2]:
        return None
    return {"symbol": symbol.upper(), "first_t": row[0], "last_t": row[1], "n": row[2],
            "first_day": K.et_of_ms(row[0]).date().isoformat(), "last_day": K.et_of_ms(row[1]).date().isoformat()}


def _day_bounds_ms(date_from, date_to):
    a = _dt.datetime.combine(K.as_date(date_from), _dt.time(0, 0), tzinfo=K.ET)
    b = _dt.datetime.combine(K.as_date(date_to) + _dt.timedelta(days=1), _dt.time(0, 0), tzinfo=K.ET)
    return K.ms_of(a), K.ms_of(b)


def kalex_5m(symbol, date_from, date_to, path=None):
    """Raw ascending rows {t, o, h, l, c, v, vw (may be None), n} for the New York dates given."""
    a, b = _day_bounds_ms(date_from, date_to)
    conn = kalex_connect(path)
    try:
        rows = conn.execute("SELECT t,o,h,l,c,v,vw,n FROM bars WHERE symbol=? AND t>=? AND t<? ORDER BY t",
                            (symbol.upper(), a, b)).fetchall()
    finally:
        conn.close()
    return [{"t": int(r[0]), "o": r[1], "h": r[2], "l": r[3], "c": r[4], "v": r[5], "vw": r[6], "n": r[7]}
            for r in rows if r[4] is not None]


# ---------------------------------------------------------------- flat files

def flatfile_path(day, folder=None):
    return os.path.join(str(folder or C.flatfile_dir()), "%s.csv.gz" % K.as_date(day).isoformat())


def flatfile_day(day, symbols=None, folder=None):
    """Iterate one day file: {ticker, t (ms, minute START), o, h, l, c, v, n}. `symbols` filters."""
    p = flatfile_path(day, folder)
    if not os.path.exists(p):
        raise StoreError("no flat file for %s at %s" % (K.as_date(day), p))
    want = set(s.upper() for s in symbols) if symbols else None
    with gzip.open(p, "rt", encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            t = r.get("ticker") or ""
            if want is not None and t not in want:
                continue
            ws = int(r["window_start"])
            yield {"ticker": t, "t": ws // 1000000 if ws > 10 ** 14 else ws, "o": float(r["open"]),
                   "h": float(r["high"]), "l": float(r["low"]), "c": float(r["close"]), "v": float(r["volume"]),
                   "n": int(r["transactions"]) if r.get("transactions") not in (None, "") else None}


def fold_minutes_to_5m(rows):
    """1-minute rows of ONE ticker -> 5-minute rows on the clock grid (start = floor to 5 minutes):
    open of the first minute, highest high, lowest low, close of the last, summed volume and trades.
    ``vw`` is None (the flat files do not carry it)."""
    buckets = {}
    for r in sorted(rows, key=lambda x: x["t"]):
        k = r["t"] - r["t"] % FIVE_MIN_MS
        b = buckets.get(k)
        if b is None:
            buckets[k] = {"t": k, "o": r["o"], "h": r["h"], "l": r["l"], "c": r["c"], "v": r["v"],
                          "vw": None, "n": r.get("n") or 0}
        else:
            b["h"] = max(b["h"], r["h"])
            b["l"] = min(b["l"], r["l"])
            b["c"] = r["c"]
            b["v"] += r["v"]
            b["n"] += r.get("n") or 0
    return [buckets[k] for k in sorted(buckets)]


def flatfile_bulk(symbols, dates, folder=None):
    """{SYMBOL: [5m rows, ascending, every date]} reading each day file ONCE for every symbol.
    Missing day files raise (a gap is never a quiet hole in a history)."""
    want = sorted(set(s.upper() for s in symbols))
    out = {s: [] for s in want}
    for d in sorted(K.as_date(x) for x in dates):
        per = {s: [] for s in want}
        for r in flatfile_day(d, want, folder):
            per[r["ticker"]].append(r)
        for s in want:
            out[s].extend(fold_minutes_to_5m(per[s]))
    return out


def flatfile_range(folder=None):
    folder = str(folder or C.flatfile_dir())
    try:
        names = sorted(f for f in os.listdir(folder) if f.endswith(".csv.gz"))
    except OSError:
        return None
    if not names:
        return None
    return {"files": len(names), "first_day": names[0][:10], "last_day": names[-1][:10]}


# ---------------------------------------------------------------- status

def stores_status(symbol="SPY"):
    """What each local store holds, read-only. Three outcomes per store: ok, missing, unreadable."""
    out = {}
    kp = C.kalex_5m_path()
    if not kp.exists():
        out["kalex_5m"] = {"state": "missing", "path": str(kp)}
    else:
        try:
            cov = kalex_coverage(symbol, kp)
            conn = kalex_connect(kp)
            try:
                n_sym = conn.execute("SELECT COUNT(*) FROM coverage").fetchone()[0]
            finally:
                conn.close()
            out["kalex_5m"] = {"state": "ok", "path": str(kp), "bytes": kp.stat().st_size, "symbols": n_sym,
                               "adjusted": True, "probe_symbol": cov}
        except Exception as e:   # unreadable is a counted state, never a crash
            out["kalex_5m"] = {"state": "unreadable", "path": str(kp), "detail": str(e)}
    fd = C.flatfile_dir()
    rng = flatfile_range(fd)
    out["flatfiles"] = dict({"state": "ok" if rng else "missing", "path": str(fd), "adjusted": False}, **(rng or {}))
    return out
