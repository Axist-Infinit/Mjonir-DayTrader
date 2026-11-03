"""mjonir.localstores, mjonir.cache and mjonir.bars: a synthetic store with the Kalex schema
(extended-hours rows, a NULL vw, WAL) read RTH-only and never written; a 3-row flat file folded to
5 minutes; the cache's complete-sessions-only rule; the chunk 2 interfaces."""

import csv
import gzip
import hashlib
import io
import os
import sqlite3
import tempfile
import unittest

import _mj
from mjonir import bars as B
from mjonir import cache as CA
from mjonir import calendar as K
from mjonir import localstores as LS
from mjonir import yahoo_shape as Y

CAL = K.Calendar()
AGGS = _mj.fixture("aggs-TSLA-5m-2026-10-19.json")["results"]
EARLY = _mj.fixture("aggs-TSLA-5m-2025-11-28.json")["results"]


def sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def make_kalex(path, rows_by_symbol):
    """The Kalex schema, WAL, closed clean (no sidecars left by the writer)."""
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE bars (symbol TEXT NOT NULL, t INTEGER NOT NULL, o REAL, h REAL, l REAL, c REAL, "
                 "v REAL, vw REAL, n INTEGER, PRIMARY KEY (symbol, t)) WITHOUT ROWID")
    conn.execute("CREATE TABLE coverage (symbol TEXT PRIMARY KEY, fetched_from TEXT, fetched_to TEXT, rows INTEGER, "
                 "updated_at TEXT)")
    for sym, rows in rows_by_symbol.items():
        conn.executemany("INSERT INTO bars VALUES (?,?,?,?,?,?,?,?,?)",
                         [(sym, r["t"], r["o"], r["h"], r["l"], r["c"], r["v"], r["vw"], r["n"]) for r in rows])
        conn.execute("INSERT INTO coverage VALUES (?,?,?,?,?)", (sym, "2015-01-02", "2026-07-15", len(rows), "x"))
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()


class Kalex(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.path = os.path.join(self.d, "intraday_5m.sqlite3")
        rows = [dict(r) for r in EARLY + AGGS]
        rows[0]["vw"] = None                                       # a NULL vw, as most Kalex rows are
        make_kalex(self.path, {"TSLA": rows})
        self.old = os.environ.get("MJONIR_KALEX_5M")
        os.environ["MJONIR_KALEX_5M"] = self.path

    def tearDown(self):
        if self.old is None:
            os.environ.pop("MJONIR_KALEX_5M", None)
        else:
            os.environ["MJONIR_KALEX_5M"] = self.old

    def test_raw_rows_rth_reader_and_no_writes(self):
        before = sha(self.path)
        raw = LS.kalex_5m("TSLA", "2026-10-19", "2026-10-19")
        self.assertEqual(len(raw), 192)                            # 04:00 to 19:55, raw
        self.assertEqual(K.et_of_ms(raw[0]["t"]).strftime("%H:%M"), "04:00")
        early = LS.kalex_5m("tsla", "2025-11-28", "2025-11-28")
        self.assertIsNone(early[0]["vw"])
        info = {}
        got = B.bars_5m("TSLA", "2025-11-28", "2026-10-19", source="kalex", cal=CAL, client=_mj.client(), info=info)
        self.assertEqual(info, {"source": "kalex", "adjusted": True, "as_of": "2026-10-19"})
        self.assertEqual(len(got), 42 + 78)                        # regular hours only, 42 on the early close
        self.assertEqual(len(got[0]), 6)
        self.assertEqual(K.et_of_ms(got[-1][0]).strftime("%H:%M"), "15:55")
        doc = Y.fetch_history_doc(_mj.client(), CAL, "TSLA", "2026-10-19", "2026-10-19", source="kalex")
        m = doc["chart"]["result"][0]["meta"]
        self.assertEqual((len(doc["chart"]["result"][0]["timestamp"]), m["mjonir"]["source"]), (78, "kalex"))
        cov = LS.kalex_coverage("TSLA")
        self.assertEqual((cov["first_day"], cov["last_day"], cov["n"]), ("2025-11-28", "2026-10-19", 192 + 121))
        self.assertIsNone(LS.kalex_coverage("ZZZZ"))
        # auto picks the store when it holds the whole range
        auto = Y.fetch_history_doc(_mj.client(), CAL, "TSLA", "2026-10-19", "2026-10-19")
        self.assertEqual(auto["chart"]["result"][0]["meta"]["mjonir"]["source"], "kalex")
        conn = LS.kalex_connect()
        with self.assertRaises(sqlite3.OperationalError):
            conn.execute("INSERT INTO bars VALUES ('X', 1, 1, 1, 1, 1, 1, 1, 1)")
        with self.assertRaises(sqlite3.OperationalError):
            conn.execute("DELETE FROM bars")
        conn.close()
        self.assertEqual(sha(self.path), before)                   # the bytes never change
        st = LS.stores_status("TSLA")
        self.assertEqual((st["kalex_5m"]["state"], st["kalex_5m"]["symbols"]), ("ok", 1))

    def test_empty_is_an_error(self):
        with self.assertRaises(Y.DataError):
            B.bars_5m("ZZZZ", "2026-10-19", "2026-10-19", source="kalex", cal=CAL, client=_mj.client())

    def test_a_split_after_the_store_ends_is_refused(self):
        late = {"/v3/reference/splits": lambda url, path, q: {"status": "OK", "results": [
            {"ticker": "TSLA", "execution_date": "2020-08-31", "split_from": 1, "split_to": 5},
            {"ticker": "TSLA", "execution_date": "2026-11-20", "split_from": 1, "split_to": 2}]}}
        c = _mj.client(_mj.FakeOpener(extra=late))
        for call in (lambda: B.bars_5m("TSLA", "2026-10-19", "2026-10-19", source="kalex", cal=CAL, client=c),
                     lambda: B.bars_5m("TSLA", "2026-10-19", "2026-10-19", cal=CAL, client=c),      # auto
                     lambda: Y.fetch_history_doc(c, CAL, "TSLA", "2026-10-19", "2026-10-19", source="kalex")):
            with self.assertRaises(Y.DataError) as cm:
                call()
            self.assertEqual(cm.exception.outcome, "refused")
            self.assertIn("2-for-1 on 2026-11-20", str(cm.exception))
            self.assertIn("coverage end 2026-10-19", str(cm.exception))

    def test_no_client_no_check_unverified(self):
        from mjonir import config as C
        saved = C.env_layers
        C.env_layers = lambda repo=None, environ=None: {}
        try:
            with self.assertRaises(Y.DataError) as cm:
                B.bars_5m("TSLA", "2026-10-19", "2026-10-19", source="kalex", cal=CAL)
            self.assertEqual(cm.exception.outcome, "unverified")
            self.assertIn("adjusted as of 2026-10-19", str(cm.exception))
        finally:
            C.env_layers = saved


class FlatFiles(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.old = os.environ.get("MJONIR_FLATFILE_DIR")
        os.environ["MJONIR_FLATFILE_DIR"] = self.d
        t0 = K.ms_of(K.parse_now("2025-11-28 09:30")) * 1000000      # ns
        rows = [("ZZZ", 300, 10.0, 10.5, 10.6, 9.9, t0, 3),
                ("TSLA", 100, 400.0, 401.0, 401.5, 399.5, t0, 10),
                ("TSLA", 200, 401.0, 400.2, 402.0, 400.0, t0 + 60 * 10 ** 9, 20),
                ("TSLA", 50, 400.2, 403.0, 403.1, 400.1, t0 + 4 * 60 * 10 ** 9, 5),
                ("TSLA", 70, 403.0, 403.5, 403.6, 402.9, t0 + 5 * 60 * 10 ** 9, 7)]
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["ticker", "volume", "open", "close", "high", "low", "window_start", "transactions"])
        w.writerows(rows)
        with gzip.open(os.path.join(self.d, "2025-11-28.csv.gz"), "wt") as fh:
            fh.write(buf.getvalue())

    def tearDown(self):
        if self.old is None:
            os.environ.pop("MJONIR_FLATFILE_DIR", None)
        else:
            os.environ["MJONIR_FLATFILE_DIR"] = self.old

    def test_three_minutes_fold_to_one_bar(self):
        rows = list(LS.flatfile_day("2025-11-28", ["TSLA"]))
        self.assertEqual(len(rows), 4)
        five = LS.fold_minutes_to_5m(rows[:3])
        self.assertEqual(len(five), 1)
        b = five[0]
        self.assertEqual(K.et_of_ms(b["t"]).strftime("%H:%M"), "09:30")
        self.assertEqual((b["o"], b["h"], b["l"], b["c"], b["v"], b["n"], b["vw"]),
                         (400.0, 403.1, 399.5, 403.0, 350, 35, None))
        bulk = LS.flatfile_bulk(["TSLA", "ZZZ", "NONE"], ["2025-11-28"])
        self.assertEqual([len(bulk[s]) for s in ("TSLA", "ZZZ", "NONE")], [2, 1, 0])
        with self.assertRaises(LS.StoreError):
            LS.flatfile_bulk(["TSLA"], ["2025-11-26"])
        self.assertEqual(LS.flatfile_range()["files"], 1)


class Cache(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "c.sqlite3")

    def test_complete_sessions_only(self):
        c = CA.Cache(self.path, clock="2026-10-19 23:00")
        with self.assertRaises(CA.CacheError):
            c.put_session("TSLA", "5m", "2026-10-19", AGGS, "massive")          # today: never
        c.close()
        c = CA.Cache(self.path, clock="2026-10-20 00:05")
        self.assertEqual(c.put_session("TSLA", "5m", "2026-10-19", AGGS, "massive"), 192)
        with self.assertRaises(CA.CacheError):
            c.put_session("TSLA", "5m", "2026-10-16", AGGS, "massive")          # rows of another day
        self.assertEqual(c.get_session("TSLA", "5m", "2026-10-19"), [dict(r) for r in AGGS])
        self.assertIsNone(c.get_session("TSLA", "5m", "2026-10-19", src="kalex"))
        self.assertIsNone(c.get_session("TSLA", "5m", "2026-10-16"))
        self.assertEqual(c.put_session("HALT", "5m", "2026-10-16", [], "massive"), 0)   # writes nothing
        self.assertIsNone(c.get_session("HALT", "5m", "2026-10-16"))
        self.assertIsNone(c.coverage("HALT", "5m", "2026-10-16"))
        with c.conn:     # an n=0 coverage row left by an older build is a miss, never "no bars"
            c.conn.execute("INSERT INTO coverage VALUES ('OLD','5m','2026-10-16','2026-10-16',NULL,NULL,0,'massive',1,'x')")
        self.assertIsNone(c.get_session("OLD", "5m", "2026-10-16"))
        g = {"SPY": {"t": 1, "o": 1, "h": 1, "l": 1, "c": 1, "v": 1, "vw": 1, "n": 1}}
        self.assertEqual(c.put_grouped("2026-10-19", g), 1)
        self.assertEqual(c.get_grouped("2026-10-19")["SPY"]["c"], 1)
        with self.assertRaises(CA.CacheError):
            c.put_grouped("2026-10-19", {})
        self.assertEqual(c.stats()["grouped_days"], 1)
        # a split executed after the rows were fetched makes them stale: dropped
        dropped = c.invalidate_split("TSLA", [{"execution_date": "2026-10-21"}])
        self.assertEqual(dropped, 192)
        self.assertIsNone(c.get_session("TSLA", "5m", "2026-10-19"))
        c.close()

    def test_a_live_chart_never_reaches_the_cache(self):
        c = CA.Cache(self.path)
        Y.fetch_chart_doc(_mj.client(), CAL, "TSLA", "2026-10-19", cache=c)
        c = CA.Cache(self.path)
        self.assertEqual(len(c.get_session("TSLA", "5m", "2026-10-19")), 192)    # a past session: cached
        self.assertEqual(len(c.get_session("TSLA", "1d", "2026-10-16")), 1)
        c.close()
        other = os.path.join(tempfile.mkdtemp(), "c.sqlite3")
        c = CA.Cache(other)
        Y.fetch_chart_doc(_mj.client(), CAL, "TSLA", "2026-10-19", live=True, cache=c)
        c = CA.Cache(other)
        self.assertIsNone(c.get_session("TSLA", "5m", "2026-10-19"))
        self.assertEqual(c.stats()["bars"], 0)
        c.close()

    def test_the_cache_answers_without_the_network(self):
        c = CA.Cache(self.path)
        Y.fetch_chart_doc(_mj.client(), CAL, "TSLA", "2026-10-19", cache=c)
        op = _mj.FakeOpener()
        Y.fetch_chart_doc(_mj.client(op), CAL, "TSLA", "2026-10-19", cache=CA.Cache(self.path))
        self.assertEqual(op.calls, [])


class EmptyAndKeys(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "c.sqlite3")

    def test_a_session_the_answer_lacks_is_asked_again(self):
        ranged = {"/v2/aggs/ticker/TSLA/range/5/minute/2026-10-16/2026-10-19":
                  lambda url, path, q: _mj.fixture("aggs-TSLA-5m-2026-10-19.json")}
        op = _mj.FakeOpener(extra=ranged)
        c = CA.Cache(self.path)
        rows = Y.range_rows(_mj.client(op), CAL, "TSLA", CAL.sessions_between("2026-10-16", "2026-10-19"), "5m", c)
        self.assertEqual(len(rows), 192)
        self.assertIsNotNone(c.coverage("TSLA", "5m", "2026-10-19"))
        self.assertIsNone(c.coverage("TSLA", "5m", "2026-10-16"))               # no row for the missing session
        op2 = _mj.FakeOpener()
        stats = {}
        Y.range_rows(_mj.client(op2), CAL, "TSLA", CAL.sessions_between("2026-10-16", "2026-10-19"), "5m", c, stats)
        self.assertEqual([u.split("?")[0].rsplit("/", 2)[-2:] for u in op2.calls], [["2026-10-16", "2026-10-16"]])
        self.assertEqual((stats["cached"], stats["fetched"], stats["requests"]), (1, 1, 1))
        c.close()

    def test_brk_dot_b_and_brk_dash_b_share_one_session(self):
        brk = {"/v2/aggs/ticker/BRK.B/": lambda url, path, q: _mj.fixture("aggs-TSLA-5m-2026-10-19.json")}
        op = _mj.FakeOpener(extra=brk)
        c = CA.Cache(self.path)
        Y.session_rows(_mj.client(op), CAL, "BRK-B", "2026-10-19", "5m", c)
        op2 = _mj.FakeOpener(extra=brk)
        self.assertEqual(len(Y.session_rows(_mj.client(op2), CAL, "brk.b", "2026-10-19", "5m", c)), 192)
        self.assertEqual(op2.calls, [])
        self.assertIsNotNone(c.coverage("BRK.B", "5m", "2026-10-19"))
        c.close()

    def test_a_split_also_drops_stale_grouped_rows(self):
        c = CA.Cache(self.path, clock="2026-10-20 08:00")
        g = {"SPY": {"t": 1, "c": 1.0}, "TSLA": {"t": 1, "c": 368.06}}
        c.put_grouped("2026-10-16", g)
        c.put_grouped("2026-10-19", g)
        c.close()
        c = CA.Cache(self.path, clock="2026-10-23 08:00")
        c.put_grouped("2026-10-22", g)                                          # fetched after the split
        c.invalidate_split("TSLA", [{"execution_date": "2026-10-21"}])
        self.assertIsNone(c.get_grouped("2026-10-16"))                          # a miss: fetched again, adjusted
        self.assertIsNone(c.get_grouped("2026-10-19"))
        self.assertEqual(sorted(c.get_grouped("2026-10-22")), ["SPY", "TSLA"])
        c.close()


class Interfaces(unittest.TestCase):
    def test_bars_daily_adv_quote(self):
        c = _mj.client()
        info = {}
        got = B.bars_5m("TSLA", "2026-10-19", "2026-10-19", client=c, cal=CAL, source="api", cache=None, info=info)
        self.assertEqual(info, {"source": "api", "adjusted": True, "as_of": K.today_et().isoformat()})
        path = os.path.join(tempfile.mkdtemp(), "c.sqlite3")
        B.bars_5m("TSLA", "2026-10-19", "2026-10-19", client=c, cal=CAL, source="api", cache=CA.Cache(path))
        B.bars_5m("TSLA", "2026-10-19", "2026-10-19", client=c, cal=CAL, source="api", cache=CA.Cache(path), info=info)
        self.assertEqual((info["source"], info["adjusted"]), ("cache", True))
        self.assertEqual(info["as_of"], K.today_et().isoformat())               # fetched today, in this test
        c2 = CA.Cache(path)
        with c2.conn:   # a fetch stamped 03:30 UTC on Nov 3 is the evening of Nov 2 in New York
            c2.conn.execute("UPDATE coverage SET fetched_at='2026-11-03T03:30:00Z'")
        B.bars_5m("TSLA", "2026-10-19", "2026-10-19", client=c, cal=CAL, source="api", cache=c2, info=info)
        self.assertEqual((info["source"], info["as_of"]), ("cache", "2026-11-02"))
        d_info = {}
        B.daily("TSLA", "2026-10-16", "2026-10-19", client=c, cal=CAL, cache=None, info=d_info)
        self.assertEqual(d_info["source"], "api")
        self.assertEqual(len(got), 78)
        self.assertEqual(got[8][4], 364.176)
        raw = B.bars_5m("TSLA", "2026-10-19", "2026-10-19", rth_only=False, client=c, cal=CAL, source="api", cache=None)
        self.assertEqual(len(raw), 192)
        d = B.daily("TSLA", "2026-10-16", "2026-10-19", client=c, cal=CAL, cache=None)
        self.assertEqual([r[4] for r in d], [354.72, 368.06])
        adv = B.adv_usd("TSLA", "2026-10-19", n=2, client=c, cal=CAL, cache=None)
        rows = _mj.fixture("aggs-TSLA-1d-2026-07-20_2026-10-19.json")["results"]
        want = [r for r in rows if K.et_of_ms(r["t"]).date().isoformat() in ("2026-10-15", "2026-10-16")]
        self.assertAlmostEqual(adv, sum(r["c"] * r["v"] for r in want) / 2.0)     # strictly before the 19th
        with self.assertRaises(B.InsufficientData):
            B.adv_usd("TSLA", "2026-07-22", n=20, client=c, cal=CAL, cache=None)
        with self.assertRaises(Y.DataError):
            B.daily("ZZZZ", "2026-10-16", "2026-10-19", client=c, cal=CAL, cache=None)
        with self.assertRaises(Y.DataError):
            B.bars_5m("TSLA", "2026-10-18", "2026-10-18", client=c, cal=CAL, cache=None)
        import urllib.error

        def down(url, headers, timeout):
            raise urllib.error.URLError("down")
        self.assertIsNone(B.quote("TSLA", client=_mj.client(down)))


if __name__ == "__main__":
    unittest.main()
