"""mjonir.yahoo_shape: documents built from the recorded Massive fixtures, read back through
upstream's OWN parsers and rules (scan, entry, timemachine, alerts, news). If these pass, a script
under --source massive sees exactly what it sees from Yahoo, field by field."""

import copy
import datetime as dt
import gzip
import json
import os
import shutil
import tempfile
import unittest

import _mj
from _load import load
from mjonir import calendar as K
from mjonir import massive as M
from mjonir import yahoo_shape as Y

scan = load("trader-scanner", "scan")
entry = load("trader-entry", "entry")
tm = load("trader-timemachine", "timemachine")
alerts = load("trader-alerts", "alerts")
news = load("trader-news", "news")

CAL = K.Calendar()
AGGS = _mj.fixture("aggs-TSLA-5m-2026-10-19.json")["results"]
EARLY = _mj.fixture("aggs-TSLA-5m-2025-11-28.json")["results"]
DAILY = _mj.fixture("aggs-TSLA-1d-2026-07-20_2026-10-19.json")["results"]
SNAP = {r["ticker"]: r for r in _mj.fixture("snapshot-TSLA-AAPL.json")["tickers"]}


def grouped_1016(url, path, q):
    t = K.ms_of(K.parse_now("2026-10-16 00:00"))
    return {"status": "OK", "adjusted": True, "resultsCount": 2,
            "results": [{"T": "SPY", "t": t, "o": 1, "h": 1, "l": 1, "c": 660.0, "v": 1},
                        {"T": "TSLA", "t": t, "o": 1, "h": 1, "l": 1, "c": 354.72, "v": 1}]}


def tsla_doc():
    return Y.fetch_chart_doc(_mj.client(), CAL, "TSLA", "2026-10-19", cache=None)


class ChartDoc(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = tsla_doc()
        cls.res = cls.doc["chart"]["result"][0]
        cls.meta = cls.res["meta"]

    def test_the_shape(self):
        m, r = self.meta, self.res
        self.assertEqual(len(r["timestamp"]), 78)                       # premarket and post-market filtered out
        self.assertEqual(r["timestamp"][0], 1792416600)                  # 09:30 EDT, upstream's OPEN_TS
        self.assertTrue(all(t % 300 == 0 for t in r["timestamp"]))
        self.assertEqual(r["timestamp"], sorted(r["timestamp"]))
        q = r["indicators"]["quote"][0]
        for k in ("open", "high", "low", "close", "volume"):
            self.assertEqual(len(q[k]), 78, k)
            self.assertNotIn(None, q[k], k)
        self.assertTrue(all(isinstance(v, int) for v in q["volume"]))
        self.assertEqual((m["symbol"], m["currency"], m["instrumentType"], m["dataGranularity"], m["range"]),
                         ("TSLA", "USD", "EQUITY", "5m", "1d"))
        self.assertEqual((m["exchangeTimezoneName"], m["timezone"], m["gmtoffset"]), ("America/New_York", "EDT", -14400))
        self.assertEqual(m["regularMarketTime"], 1792440000)            # the 16:00 close of a past session
        self.assertEqual((m["previousClose"], m["chartPreviousClose"]), (354.72, 354.72))
        self.assertEqual(m["regularMarketPrice"], 368.06)               # the daily bar, not the 15:55 bar
        self.assertEqual(m["regularMarketDayLow"], 354.47)
        self.assertEqual(m["regularMarketVolume"], sum(q["volume"]))     # regular hours only
        mj = m["mjonir"]
        self.assertEqual((mj["source"], mj["adjusted"], mj["rth_only"], mj["early_close"], mj["bars"],
                          mj["expected_bars"], mj["regular_market_time_basis"], mj["close_basis"]),
                         ("massive", True, True, None, 78, 78, "session_close", "daily_bar"))

    def test_scan_parse_chart_and_the_orb_hit(self):
        s = scan.parse_chart(Y.to_text(self.doc), "TSLA")
        day = dt.date(2026, 10, 19)
        bars = scan.session_bars(s, day, dt.datetime(2026, 10, 19, 10, 15))
        self.assertTrue(scan.usable(bars, day, dt.datetime(2026, 10, 19, 10, 15), 3))
        h = scan.orb_hit(bars, 3)
        self.assertEqual({k: h[k] for k in ("price", "bar_index", "or_high", "or_low", "at")},
                         {"price": 364.18, "bar_index": 8, "or_high": 362.18, "or_low": 354.47, "at": "10:15 AM"})

    def test_scan_parse_spark_and_load_offline(self):
        got = scan.parse_spark(Y.spark_doc([self.doc]))
        self.assertEqual(list(got), ["TSLA"])
        self.assertEqual(got["TSLA"]["c"], self.res["indicators"]["quote"][0]["close"])
        d = tempfile.mkdtemp()
        try:
            with open(os.path.join(d, "TSLA.json"), "w") as fh:
                fh.write(Y.to_text(self.doc))
            data, errors = scan.load_offline(d)
            self.assertEqual((list(data), errors), (["TSLA"], {}))
            bundle = os.path.join(d, "wall.json.gz")
            with gzip.open(bundle, "wt") as fh:
                json.dump({"TSLA": self.doc}, fh)
            data2, _ = scan.load_offline(bundle)
            self.assertEqual(data2["TSLA"]["c"], data["TSLA"]["c"])
            self.assertEqual(data2["TSLA"]["h"], self.res["indicators"]["quote"][0]["high"])
        finally:
            shutil.rmtree(d)

    def test_entry_parse_chart_then_evaluate(self):
        ch = entry.parse_chart(Y.to_text(self.doc), "TSLA")
        self.assertEqual((ch["symbol"], ch["prev_close"], ch["data_time"]), ("TSLA", 354.72, 1792440000))
        r = entry.evaluate(ch, entry.parse_now("2026-10-19 10:15"))
        self.assertEqual(r["status"], "triggered")
        self.assertEqual((r["opening_range"]["high"], r["opening_range"]["low"]), (362.18, 354.47))
        t = r["trigger"]
        self.assertEqual((t["time"], t["bar_start"], t["bar_index"], t["price"]), ("10:15 AM", "10:10", 8, 364.18))
        self.assertEqual(entry.evaluate(ch, entry.parse_now("2026-10-19 10:12"))["status"], "waiting")
        r = entry.evaluate(ch, entry.parse_now("2026-10-19 09:44"))
        self.assertEqual((r["status"], r["phase"]), ("waiting", "forming"))
        self.assertEqual(entry.evaluate(ch, entry.parse_now("2026-10-19 09:20"))["phase"], "pre-open")

    def test_exit_atr_reader(self):
        exitp = load("trader-exit", "exit")
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, "TSLA.json")
            with open(p, "w") as fh:
                fh.write(Y.to_text(self.doc))
            ch = exitp.load_chart("TSLA", "5m", dt.date(2026, 10, 19), d)
            bars = exitp.session_bars(ch, dt.date(2026, 10, 19), "5m", 8)
            self.assertEqual(len(bars), 9)
        finally:
            shutil.rmtree(d)

    def test_a_class_share_symbol(self):
        doc = Y.chart_doc("BRK.B", AGGS, "5m", CAL, day="2026-10-19", now=K.parse_now("2026-11-02 12:00"))
        self.assertEqual(doc["chart"]["result"][0]["meta"]["symbol"], "BRK-B")
        self.assertIn("BRK.B", scan.parse_spark(Y.spark_doc([doc])))
        self.assertEqual((Y.massive_symbol("brk-b"), Y.yahoo_symbol("brk.b")), ("BRK.B", "BRK-B"))

    def test_refusals(self):
        with self.assertRaises(Y.DataError) as cm:
            Y.fetch_chart_doc(_mj.client(), CAL, "TSLA", "2026-10-18", cache=None)
        self.assertIn("weekend", str(cm.exception))
        with self.assertRaises(Y.DataError):
            Y.fetch_chart_doc(_mj.client(), CAL, "ZZZZ", "2026-10-19", cache=None)   # no bars: P10
        with self.assertRaises(Y.DataError):
            Y.fetch_chart_doc(_mj.client(), CAL, "TSLA", "2099-10-19", cache=None)
        with self.assertRaises(Y.DataError):
            Y.chart_doc("TSLA", [], "5m", CAL, day="2026-10-19")


class EarlyClose(unittest.TestCase):
    def test_42_bars_and_the_one_oclock_close(self):
        doc = Y.fetch_chart_doc(_mj.client(), CAL, "TSLA", "2025-11-28", cache=None)
        m = doc["chart"]["result"][0]["meta"]
        self.assertEqual(len(doc["chart"]["result"][0]["timestamp"]), 42)
        self.assertEqual((m["timezone"], m["mjonir"]["early_close"], m["mjonir"]["early_close_basis"],
                          m["mjonir"]["expected_bars"]), ("EST", "day after Thanksgiving", "verified", 42))
        self.assertEqual(K.et_of_ms(m["regularMarketTime"] * 1000).strftime("%H:%M"), "13:00")


class TimeMachine(unittest.TestCase):
    """A history document through tm.chart_result / parse_bars / full_sessions at 78 and 42 bars."""

    def test_78_and_42(self):
        doc = Y.history_doc("TSLA", EARLY + AGGS, CAL, "2025-11-28", "2026-10-19",
                            now=K.parse_now("2026-11-02 12:00"))
        meta = doc["chart"]["result"][0]["meta"]
        self.assertEqual(meta["range"], "%dd" % len(CAL.sessions_between("2025-11-28", "2026-10-19")))
        self.assertEqual(meta["mjonir"]["early_closes"]["2025-11-28"], "verified")
        self.assertNotIn("2025-11-28", [x["date"] for x in meta["mjonir"]["incomplete_sessions"]])
        res = tm.chart_result(Y.to_text(doc), "TSLA")
        _, bars, dropped = tm.parse_bars(res, tm.parse_now("2026-10-20 09:00"))
        self.assertEqual(dropped, {"no_price": 0, "off_grid": 0, "not_complete": 0, "outside_hours": 0})
        days = tm.split_sessions(bars)
        self.assertEqual({d: len(v) for d, v in days.items()}, {"2025-11-28": 42, "2026-10-19": 78})
        full, short = tm.full_sessions(days, "2026-10-20")
        self.assertEqual([d for d, _ in full], ["2026-10-19"])
        self.assertEqual(short, [{"date": "2025-11-28", "bars": 42}])
        # the plan day itself, cut at --now 10:15: the entry bar is there, the rest is "not complete"
        _, bars, dropped = tm.parse_bars(res, tm.parse_now("2026-10-19 10:15"))
        day = tm.split_sessions(bars)["2026-10-19"]
        self.assertEqual((max(day), dropped["not_complete"]), (8, 78 - 9))

    def test_sixty_sessions_say_60d(self):
        cal = CAL
        start = cal.sessions_back("2026-10-19", 60)[0]
        doc = Y.history_doc("TSLA", AGGS, cal, start, "2026-10-19", now=K.parse_now("2026-11-02 12:00"))
        meta = doc["chart"]["result"][0]["meta"]
        self.assertEqual((meta["range"], meta["mjonir"]["first_session"]), ("60d", "2026-07-27"))
        self.assertEqual(len(meta["mjonir"]["incomplete_sessions"]), 59)   # only the 19th was given


def snap_at(row, trade_et, minute_et=None, quote_et=None, day=True):
    """A copy of a recorded snapshot row with its stamps moved to New York times (ns and ms kept)."""
    r = copy.deepcopy(row)
    ns = lambda text: K.ms_of(K.parse_now(text)) * 1000000   # noqa: E731
    r["lastTrade"]["t"] = ns(trade_et)
    r["lastQuote"]["t"] = ns(quote_et or trade_et)
    r["updated"] = ns(trade_et)
    r["min"]["t"] = K.ms_of(K.parse_now(minute_et or trade_et[:-3] + ":00" if len(trade_et) > 16 else trade_et))
    if not day:
        r["day"] = {}
    return r


class Live(unittest.TestCase):
    def test_a_live_chart_keeps_the_settle_rule(self):
        now = K.parse_now("2026-10-19 10:17:00")
        rows = [r for r in AGGS if r["t"] <= K.ms_of(now)]
        snap = snap_at(SNAP["TSLA"], "2026-10-19 10:16:30", "2026-10-19 10:16")
        doc = Y.chart_doc("TSLA", rows, "5m", CAL, day="2026-10-19", live=snap, now=now)
        m = doc["chart"]["result"][0]["meta"]
        self.assertEqual(m["mjonir"]["regular_market_time_basis"], "last_trade")
        self.assertEqual(m["regularMarketTime"], K.ms_of(K.parse_now("2026-10-19 10:16:30")) // 1000)
        self.assertEqual(m["mjonir"]["forming"]["start"], "10:15")
        self.assertEqual(m["previousClose"], SNAP["TSLA"]["prevDay"]["c"])
        self.assertEqual(m["mjonir"]["session"], "regular")
        self.assertIsNotNone(m["mjonir"]["spread_bps"])
        ch = entry.parse_chart(Y.to_text(doc), "TSLA")
        r = entry.evaluate(ch, entry.parse_now("2026-10-19 10:17"))
        self.assertEqual((r["status"], r["trigger"]["price"]), ("triggered", 364.18))
        self.assertEqual(r["forming"]["bar_start"], "10:15")
        # a last trade BEFORE the 10:10 bar's close: entry holds that bar until the data catches up
        early = snap_at(SNAP["TSLA"], "2026-10-19 10:14:50", "2026-10-19 10:14")
        rows = [r for r in AGGS if r["t"] <= K.ms_of(K.parse_now("2026-10-19 10:14"))]
        doc = Y.chart_doc("TSLA", rows, "5m", CAL, day="2026-10-19", live=early, now=K.parse_now("2026-10-19 10:15:05"))
        r = entry.evaluate(entry.parse_chart(Y.to_text(doc), "TSLA"), entry.parse_now("2026-10-19 10:15:05"))
        self.assertEqual(r["status"], "waiting")
        self.assertIn("catches up", r["lag_note"])

    def test_before_the_open_a_live_chart_is_empty_not_refused(self):
        now = K.parse_now("2026-10-19 09:00")
        rows = [r for r in AGGS if r["t"] < K.ms_of(now)]
        snap = snap_at(SNAP["TSLA"], "2026-10-19 08:59:30", "2026-10-19 08:59")
        doc = Y.chart_doc("TSLA", rows, "5m", CAL, day="2026-10-19", live=snap, now=now)
        m = doc["chart"]["result"][0]["meta"]
        self.assertEqual(doc["chart"]["result"][0]["timestamp"], [])
        self.assertIn("extended-hours print at 08:59", m["mjonir"]["withheld"])
        r = entry.evaluate(entry.parse_chart(Y.to_text(doc), "TSLA"), entry.parse_now("2026-10-19 09:00"))
        self.assertEqual(r["phase"], "pre-open")


class Quotes(unittest.TestCase):
    def test_after_the_close_the_session_close_stands(self):
        now = K.parse_now("2026-11-02 23:30")       # when the fixture was recorded
        doc = Y.quote_doc("TSLA", SNAP["TSLA"], CAL, now)
        q = alerts.parse_yahoo(Y.to_text(doc), "TSLA")
        self.assertEqual((q["price"], q["prev_close"], q["open"]), (403.82, 399.81, 404.66))
        self.assertEqual(q["time"], "2026-11-02T21:00:00Z")                 # 16:00 EST
        m = doc["chart"]["result"][0]["meta"]
        self.assertEqual(m["mjonir"]["regular_market_time_basis"], "session_close")
        self.assertIn("19:59", m["mjonir"]["withheld"])                    # the post-market print, named
        n = news.parse_chart(Y.to_text(doc), "TSLA")
        self.assertEqual((n["price"], n["prev_close"], n["pct"]), (403.82, 399.81, 1.0))

    def test_in_the_session_the_last_regular_trade(self):
        now = K.parse_now("2026-11-02 15:00:10")
        snap = snap_at(SNAP["AAPL"], "2026-11-02 14:59:58", "2026-11-02 14:59")
        q = alerts.parse_yahoo(Y.to_text(Y.quote_doc("AAPL", snap, CAL, now)), "AAPL")
        self.assertEqual((q["price"], q["prev_close"]), (SNAP["AAPL"]["lastTrade"]["p"], SNAP["AAPL"]["prevDay"]["c"]))
        self.assertEqual(q["time"], "2026-11-02T19:59:58Z")

    def test_before_the_open_the_premarket_print_is_withheld(self):
        now = K.parse_now("2026-11-03 08:00")
        snap = snap_at(SNAP["TSLA"], "2026-11-03 07:58:00", "2026-11-03 07:58", day=False)
        doc = Y.quote_doc("TSLA", snap, CAL, now, prev_close=395.0)
        q = alerts.parse_yahoo(Y.to_text(doc), "TSLA")
        self.assertEqual((q["price"], q["prev_close"], q["open"]), (SNAP["TSLA"]["prevDay"]["c"], 395.0, None))
        m = doc["chart"]["result"][0]["meta"]
        self.assertEqual((m["mjonir"]["session"], m["mjonir"]["session_date"]), ("pre", "2026-11-02"))
        self.assertIn("07:58", m["mjonir"]["withheld"])

    def test_fetch_quote_docs_on_the_fake_client(self):
        docs, errors = Y.fetch_quote_docs(_mj.client(), CAL, ["TSLA", "AAPL", "ZZZZ"], clock="2026-11-02 23:30")
        self.assertEqual(sorted(docs), ["AAPL", "TSLA"])
        self.assertIn("ZZZZ", errors)


class Daily(unittest.TestCase):
    def test_daily_doc_through_scan_daily(self):
        res = Y.daily_doc("TSLA", DAILY, CAL, rng="3mo")
        m = res["meta"]
        self.assertEqual((m["regularMarketPrice"], m["regularMarketVolume"]), (DAILY[-1]["c"], int(round(DAILY[-1]["v"]))))
        self.assertEqual(K.et_of_ms(res["timestamp"][-1] * 1000).strftime("%Y-%m-%d %H:%M"), "2026-10-19 09:30")
        data = scan.parse_spark(Y.spark_doc([res]))
        closes = scan.daily_closes(data["TSLA"], scan.parse_now("2026-10-20 08:00"))
        self.assertEqual((closes[-1][0].isoformat(), closes[-1][1], len(closes)), ("2026-10-19", 368.06, len(DAILY)))
        hits, counts, last = scan.scan_daily(data, ["TSLA"], scan.parse_now("2026-10-20 08:00"), 5, 1000000)
        self.assertEqual((counts["scanned"], last.isoformat()), (1, "2026-10-19"))
        self.assertEqual(Y.daily_doc("TSLA", DAILY, CAL, closes_only=True)["indicators"]["quote"][0].keys(), {"close"})

    def test_the_bundle_from_grouped_days(self):
        op = _mj.FakeOpener()
        doc, info = Y.fetch_daily_bundle(_mj.client(op), CAL, ["TSLA", "SPY", "ZZZZ"], sessions=1, end="2026-10-19",
                                         cache=None)
        data = scan.parse_spark(doc)
        self.assertEqual(sorted(data), ["SPY", "TSLA"])
        self.assertEqual((info["sessions"], info["built"], info["failed"]), (1, 2, 1))
        self.assertEqual(data["TSLA"]["c"], [368.06])
        self.assertIsNotNone(data["TSLA"]["h"])                           # real highs and lows
        # a ticker that split inside the window is fetched on its own, adjusted
        split = {"/v3/reference/splits": lambda url, path, q: {"status": "OK", "results": [
            {"ticker": "TSLA", "execution_date": "2026-10-19", "split_from": 1, "split_to": 2}]}}
        op = _mj.FakeOpener(extra=split)
        doc, info = Y.fetch_daily_bundle(_mj.client(op), CAL, ["TSLA"], sessions=1, end="2026-10-19", cache=None)
        self.assertEqual(info["split_refetched"], ["TSLA"])
        self.assertTrue(any("/v2/aggs/ticker/TSLA/range/1/day/" in u for u in op.calls))


class Bulk(unittest.TestCase):
    def test_charts_bulk_on_a_past_day(self):
        op = _mj.FakeOpener(extra={"/v2/aggs/grouped/locale/us/market/stocks/2026-10-16": grouped_1016})
        docs, errors = Y.fetch_charts_bulk(_mj.client(op), CAL, ["TSLA", "ZZZZ"], "2026-10-19", cache=None)
        self.assertEqual(sorted(docs), ["TSLA"])
        self.assertIn("no regular-hours", errors["ZZZZ"])
        m = docs["TSLA"]["chart"]["result"][0]["meta"]
        self.assertEqual((m["previousClose"], m["regularMarketPrice"]), (354.72, 368.06))
        got = scan.parse_spark(Y.spark_doc([docs["TSLA"]]))
        self.assertEqual(scan.orb_hit(scan.session_bars(got["TSLA"], dt.date(2026, 10, 19),
                                                         dt.datetime(2026, 10, 19, 10, 15)), 3)["price"], 364.18)


class Adapter(unittest.TestCase):
    def test_errors_come_back_as_the_scripts_own_class(self):
        class ScriptError(Exception):
            pass
        a = Y.adapter(ScriptError)
        saved = Y.fetch_chart_doc
        try:
            def boom(*args, **kw):
                raise M.Refused("grouped 2026-10-19: no SPY print")
            Y.fetch_chart_doc = boom
            with self.assertRaises(ScriptError) as cm:
                a.chart_text("TSLA", "5m", dt.date(2026, 10, 19))
            self.assertIn("Massive (refused)", str(cm.exception))

            def down(*args, **kw):
                raise M.MassiveError("network error on /v2/x: timed out")
            Y.fetch_chart_doc = down
            with self.assertRaises(ScriptError) as cm:
                a.chart_text("TSLA", "5m", dt.date(2026, 10, 19))
            self.assertIn("Massive (unverified)", str(cm.exception))
        finally:
            Y.fetch_chart_doc = saved

    def test_news_items(self):
        rows = _mj.fixture("news-TSLA.json")["results"]
        items = Y.news_items("tsla", rows)
        self.assertEqual(len(items), 2)
        it = items[0]
        self.assertEqual((it["source"], it["kind"], it["ticker"]), ("Massive news", "headline", "TSLA"))
        self.assertTrue(it["id"].startswith("massive:"))
        self.assertEqual(it["link"], rows[0]["article_url"])
        self.assertIsNotNone(news.parse_time(it["time"]))


if __name__ == "__main__":
    unittest.main()
