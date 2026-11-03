"""The bar cache: ``trader/data/mjonir_bars.sqlite3``, the only database this package opens read-write.

Rules (CLAUDE.md hazard 6):
* Only COMPLETE sessions are written: a session date strictly before today in New York, so its
  extended hours are over too. Today's session and a forming bar are never stored.
* One source per (symbol, res, session): ``src`` says where the rows came from, ``adjusted`` how.
  A chart file is never spliced across sources or across a split without a ``splits()`` check
  (``invalidate_split`` drops what a later split made stale).
"""

import os
import sqlite3
import threading
from functools import wraps

from . import calendar as K
from . import config as C

SCHEMA = """
CREATE TABLE IF NOT EXISTS bars(
    symbol TEXT NOT NULL, res TEXT NOT NULL, t INTEGER NOT NULL,
    o REAL, h REAL, l REAL, c REAL, v REAL, vw REAL, n INTEGER, src TEXT NOT NULL,
    PRIMARY KEY(symbol, res, t));
CREATE TABLE IF NOT EXISTS coverage(
    symbol TEXT NOT NULL, res TEXT NOT NULL, req_from TEXT NOT NULL, req_to TEXT NOT NULL,
    first_t INTEGER, last_t INTEGER, n INTEGER NOT NULL, src TEXT NOT NULL, adjusted INTEGER NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY(symbol, res, req_from, req_to));
CREATE TABLE IF NOT EXISTS grouped(
    date TEXT NOT NULL, T TEXT NOT NULL, ts INTEGER, o REAL, h REAL, l REAL, c REAL, v REAL, vw REAL,
    n INTEGER, fetched_at TEXT NOT NULL,
    PRIMARY KEY(date, T));
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
"""
FILE = "mjonir_bars.sqlite3"


class CacheError(RuntimeError):
    pass


def _locked(fn):
    @wraps(fn)
    def inner(self, *a, **kw):
        with self.lock:
            return fn(self, *a, **kw)
    return inner


def default_path():
    return os.path.join(str(C.data_dir()), FILE)


class Cache(object):
    def __init__(self, path=None, clock=None):
        self.path = path or default_path()
        self.clock = clock
        self.lock = threading.RLock()   # one connection, shared by the bulk fetcher's threads
        d = os.path.dirname(self.path)
        if d:
            os.makedirs(d, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=30.0, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    @_locked
    def close(self):
        self.conn.close()

    def _now(self):
        return K.now_et(self.clock)

    def _stamp(self):
        return self._now().astimezone(K.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _complete(self, day):
        return K.as_date(day) < self._now().date()

    # ------------------------------------------------------------ bars, one session at a time
    @_locked
    def put_session(self, symbol, res, day, rows, src, adjusted=True):
        """Store one COMPLETE session's rows (raw, extended hours included). Refuses today or later,
        and refuses rows dated another day. An empty list is stored as known-empty coverage."""
        day = K.as_date(day)
        if not self._complete(day):
            raise CacheError("refusing to cache %s %s %s: the session is not over (today or later)"
                             % (symbol, res, day))
        if res != "1d":
            bad = [r["t"] for r in rows if K.et_of_ms(r["t"]).date() != day]
            if bad:
                raise CacheError("refusing to cache %s %s %s: %d row(s) dated another day" % (symbol, res, day, len(bad)))
        sym = symbol.upper()
        iso = day.isoformat()
        with self.conn:
            if rows:
                self.conn.execute("DELETE FROM bars WHERE symbol=? AND res=? AND t BETWEEN ? AND ?",
                                  (sym, res, min(r["t"] for r in rows), max(r["t"] for r in rows)))
            self.conn.executemany(
                "INSERT OR REPLACE INTO bars(symbol,res,t,o,h,l,c,v,vw,n,src) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                [(sym, res, int(r["t"]), r["o"], r["h"], r["l"], r["c"], r.get("v"), r.get("vw"), r.get("n"), src)
                 for r in rows])
            self.conn.execute(
                "INSERT OR REPLACE INTO coverage(symbol,res,req_from,req_to,first_t,last_t,n,src,adjusted,fetched_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?)",
                (sym, res, iso, iso, min((r["t"] for r in rows), default=None),
                 max((r["t"] for r in rows), default=None), len(rows), src, 1 if adjusted else 0, self._stamp()))
        return len(rows)

    @_locked
    def coverage(self, symbol, res, day):
        row = self.conn.execute(
            "SELECT first_t,last_t,n,src,adjusted,fetched_at FROM coverage WHERE symbol=? AND res=? AND req_from<=? "
            "AND req_to>=? ORDER BY fetched_at DESC LIMIT 1",
            (symbol.upper(), res, K.as_date(day).isoformat(), K.as_date(day).isoformat())).fetchone()
        if not row:
            return None
        return dict(zip(("first_t", "last_t", "n", "src", "adjusted", "fetched_at"), row))

    @_locked
    def get_session(self, symbol, res, day, src=None):
        """The stored rows of one session, or None when it was never stored (or from another src)."""
        cov = self.coverage(symbol, res, day)
        if cov is None or (src and cov["src"] != src):
            return None
        if not cov["n"]:
            return []
        rows = self.conn.execute(
            "SELECT t,o,h,l,c,v,vw,n FROM bars WHERE symbol=? AND res=? AND t BETWEEN ? AND ? ORDER BY t",
            (symbol.upper(), res, cov["first_t"], cov["last_t"])).fetchall()
        out = [dict(zip(("t", "o", "h", "l", "c", "v", "vw", "n"), r)) for r in rows]
        if len(out) != cov["n"]:
            return None   # a partial overwrite: treat as never stored
        return out

    @_locked
    def fetched_at(self, symbol, res=None):
        q = "SELECT MIN(fetched_at) FROM coverage WHERE symbol=?" + (" AND res=?" if res else "")
        row = self.conn.execute(q, (symbol.upper(), res) if res else (symbol.upper(),)).fetchone()
        return row[0] if row else None

    @_locked
    def invalidate_split(self, symbol, splits):
        """Drop every cached row of `symbol` fetched before a split that executed after it was
        fetched: those rows are adjusted to the old share count. Returns the rows dropped."""
        sym = symbol.upper()
        dropped = 0
        for s in splits or []:
            ex = str(s.get("execution_date") or "")[:10]
            if not ex:
                continue
            with self.conn:
                stale = self.conn.execute(
                    "SELECT res, req_from, first_t, last_t FROM coverage WHERE symbol=? AND substr(fetched_at,1,10)<=?",
                    (sym, ex)).fetchall()
                for res, day, a, b in stale:
                    if a is not None:
                        dropped += self.conn.execute(
                            "DELETE FROM bars WHERE symbol=? AND res=? AND t BETWEEN ? AND ?", (sym, res, a, b)).rowcount
                    self.conn.execute("DELETE FROM coverage WHERE symbol=? AND res=? AND req_from=?", (sym, res, day))
        return dropped

    # ------------------------------------------------------------ grouped daily
    @_locked
    def put_grouped(self, day, rows):
        """One COMPLETE session's grouped-daily rows {T: row} (already checked by check_grouped)."""
        day = K.as_date(day)
        if not self._complete(day):
            raise CacheError("refusing to cache grouped %s: the session is not over" % day)
        if not rows:
            raise CacheError("refusing to cache an empty grouped day %s" % day)
        iso, stamp = day.isoformat(), self._stamp()
        with self.conn:
            self.conn.execute("DELETE FROM grouped WHERE date=?", (iso,))
            self.conn.executemany(
                "INSERT INTO grouped(date,T,ts,o,h,l,c,v,vw,n,fetched_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                [(iso, T, r.get("t"), r.get("o"), r.get("h"), r.get("l"), r.get("c"), r.get("v"), r.get("vw"),
                  r.get("n"), stamp) for T, r in rows.items()])
            self.conn.execute("INSERT OR REPLACE INTO meta(k,v) VALUES(?,?)", ("grouped:" + iso, str(len(rows))))
        return len(rows)

    @_locked
    def get_grouped(self, day):
        iso = K.as_date(day).isoformat()
        said = self.conn.execute("SELECT v FROM meta WHERE k=?", ("grouped:" + iso,)).fetchone()
        if not said:
            return None
        rows = self.conn.execute("SELECT T,ts,o,h,l,c,v,vw,n,fetched_at FROM grouped WHERE date=?", (iso,)).fetchall()
        if len(rows) != int(said[0]):
            return None
        return {r[0]: dict(zip(("t", "o", "h", "l", "c", "v", "vw", "n", "fetched_at"), r[1:])) for r in rows}

    @_locked
    def grouped_days(self):
        return [r[0][len("grouped:"):] for r in self.conn.execute("SELECT k FROM meta WHERE k LIKE 'grouped:%' ORDER BY k")]

    @_locked
    def stats(self):
        n_bars = self.conn.execute("SELECT COUNT(*) FROM bars").fetchone()[0]
        n_sym = self.conn.execute("SELECT COUNT(DISTINCT symbol) FROM coverage").fetchone()[0]
        days = self.grouped_days()
        return {"path": self.path, "bars": n_bars, "symbols": n_sym, "grouped_days": len(days),
                "grouped_from": days[0] if days else None, "grouped_to": days[-1] if days else None,
                "bytes": os.path.getsize(self.path) if os.path.exists(self.path) else 0}


