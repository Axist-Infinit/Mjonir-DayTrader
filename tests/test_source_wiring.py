"""--source massive in the upstream scripts. mjonir.yahoo_shape's fetchers are replaced by ones that
serve upstream's own Yahoo fixture documents, so each script's output under --source massive must
equal its --offline run on that fixture, field for field, except "source". This tests the wiring
(the branch, the adapter, the shapes), not the data. Plus TRADER_SOURCE, and the calendar overlay."""

import contextlib
import datetime as dt
import gzip
import io
import json
import os
import shutil
import tempfile
import unittest

import _mj  # noqa: F401
from _load import FIX, ROOT, load
from mjonir import yahoo_shape as Y

SFIX = os.path.join(FIX, "trader-scanner")
TSLA = os.path.join(FIX, "trader-entry", "TSLA-2026-10-19-5m.json")
TM60 = os.path.join(FIX, "trader-timemachine", "TSLA-60d5m.json.gz")
PLAN = os.path.join(FIX, "trader-budget", "plan-tsla.json")
AFIX = os.path.join(FIX, "trader-alerts")
NFIX = os.path.join(FIX, "trader-news")
SCRIPTS = [("trader-scanner", "scan"), ("trader-entry", "entry"), ("trader-exit", "exit"),
           ("trader-timemachine", "timemachine"), ("trader-alerts", "alerts"), ("trader-risk", "check")]


def doc_of(path):
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def run(mod, argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = mod.main(argv)
    return code, out.getvalue(), err.getvalue()


class Wired(unittest.TestCase):
    """Each test patches the fetchers it needs; tearDown puts every one back."""

    NAMES = ("fetch_chart_doc", "fetch_charts_bulk", "fetch_daily_bundle", "fetch_history_doc", "fetch_quote_docs",
             "fetch_news")

    def setUp(self):
        self.saved = {n: getattr(Y, n) for n in self.NAMES}
        self.calls = []
        self.cwd = os.getcwd()
        self.d = tempfile.mkdtemp()
        os.chdir(self.d)

    def tearDown(self):
        for n, f in self.saved.items():
            setattr(Y, n, f)
        os.chdir(self.cwd)
        shutil.rmtree(self.d)

    def serve(self, name, value):
        def fake(*a, **kw):
            self.calls.append((name, a, kw))
            return value(*a, **kw) if callable(value) else value
        setattr(Y, name, fake)

    def same(self, a, b, drop=("seconds", "offline", "source")):
        a = json.loads(a)
        b = json.loads(b)
        for k in drop:
            a.pop(k, None)
            b.pop(k, None)
        self.assertEqual(a, b)


class Scanner(Wired):
    def test_daily(self):
        scan = load("trader-scanner", "scan")
        daily = os.path.join(SFIX, "daily-spark-2026-10-19.json")
        self.serve("fetch_daily_bundle", (doc_of(daily), {}))
        now = "2026-10-20 08:00"
        c1, off, _ = run(scan, ["daily", "--offline", daily, "--now", now, "--json", "--no-write"])
        syms = ",".join(json.loads(off)["counts"] and sorted(scan.parse_spark(doc_of(daily))))
        c2, mas, err = run(scan, ["daily", "--source", "massive", "--symbols", syms, "--now", now, "--json"])
        self.assertEqual((c1, c2), (0, 0), err)
        self.same(off, mas)
        self.assertEqual((json.loads(off)["source"], json.loads(mas)["source"]), ("yahoo", "massive"))
        with open(os.path.join("trader", "watchlist.json")) as fh:
            self.assertEqual(json.load(fh)["source"], "massive")
        self.assertEqual(self.calls[0][0], "fetch_daily_bundle")

    def test_orb_needs_no_stage_two(self):
        scan = load("trader-scanner", "scan")
        wall = os.path.join(SFIX, "wall5m-2026-10-19.json.gz")
        bundle = doc_of(wall)
        docs = {s: d for s, d in bundle.items() if d["chart"].get("result")}
        errs = {s: "no data from Massive" for s in bundle if s not in docs}
        self.serve("fetch_charts_bulk", (docs, errs))
        args = ["--now", "2026-10-19 10:15", "--min-price", "0", "--json", "--no-write"]
        c1, off, _ = run(scan, ["orb", "--offline", wall] + args)
        c2, mas, err = run(scan, ["orb", "--source", "massive", "--symbols", ",".join(sorted(bundle))] + args)
        self.assertEqual((c1, c2), (0, 0), err)
        self.same(off, mas)
        m = json.loads(mas)
        self.assertEqual((len(m["hits"]), m["counts"]["confirmed"], m["counts"]["unconfirmed"]), (42, 95, 0))
        name, a, kw = self.calls[0]
        self.assertEqual((name, a[3]), ("fetch_charts_bulk", dt.date(2026, 10, 19)))   # the --now day
        # a past day is not refused under massive (Yahoo's 5-minute history is short; Massive's is not)
        c3, _, err = run(scan, ["orb", "--symbols", "TSLA", "--now", "2026-10-19 10:15", "--json", "--no-write"])
        self.assertEqual(c3, 1)
        self.assertIn("Yahoo's free 5-minute history is short", err)

    def test_trader_source_and_an_explicit_flag(self):
        scan = load("trader-scanner", "scan")
        daily = os.path.join(SFIX, "daily-spark-2026-10-19.json")
        self.serve("fetch_daily_bundle", (doc_of(daily), {}))
        os.environ["TRADER_SOURCE"] = "massive"
        try:
            code, out, _ = run(scan, ["daily", "--symbols", "AAPL,BLK", "--now", "2026-10-20 08:00", "--json",
                                      "--no-write"])
            self.assertEqual(json.loads(out)["source"], "massive")
            code, out, _ = run(scan, ["daily", "--source", "yahoo", "--offline", daily, "--now", "2026-10-20 08:00",
                                      "--json", "--no-write"])
            self.assertEqual(json.loads(out)["source"], "yahoo")
        finally:
            os.environ.pop("TRADER_SOURCE")
        self.assertEqual(len(self.calls), 1)


class Entry(Wired):
    def setUp(self):
        super().setUp()
        self.serve("fetch_chart_doc", lambda *a, **kw: doc_of(TSLA))

    def test_check(self):
        entry = load("trader-entry", "entry")
        for now in ("2026-10-19 10:15", "2026-10-19 10:12", "2026-10-19 09:44"):
            c1, off, _ = run(entry, ["check", "TSLA", "--offline", TSLA, "--now", now, "--json"])
            c2, mas, err = run(entry, ["check", "TSLA", "--source", "massive", "--now", now, "--json"])
            self.assertEqual(c1, c2, err)
            self.assertEqual(json.loads(off), json.loads(mas))
        name, a, kw = self.calls[0]
        self.assertEqual((a[2], a[3], a[4], a[5]), ("TSLA", dt.date(2026, 10, 19), "5m", False))   # never live
        c, text, _ = run(entry, ["check", "TSLA", "--source", "massive", "--now", "2026-10-19 10:15", "--write"])
        self.assertIn("(Massive)", text.splitlines()[0])
        with open(os.path.join("trader", "entry.json")) as fh:
            e = json.load(fh)
        self.assertEqual((e["source"], e["price"], e["bar_index"]), ("massive", 364.18, 8))

    def test_watch_replays_without_sleeping(self):
        entry = load("trader-entry", "entry")
        c1, off, _ = run(entry, ["watch", "TSLA", "--offline", TSLA, "--now", "2026-10-19 09:50", "--out", "a.json"])
        c2, mas, err = run(entry, ["watch", "TSLA", "--source", "massive", "--now", "2026-10-19 09:50", "--out",
                                   "b.json"])
        self.assertEqual((c1, c2), (0, 0), err)
        self.assertEqual(off.replace("Yahoo, free, can lag", "Massive").replace("a.json", "b.json"), mas)
        self.assertIn("10:10 bar  closed $364.18  TRIGGERED", mas)


class Exit(Wired):
    def test_atr_stop(self):
        exitp = load("trader-exit", "exit")
        self.serve("fetch_chart_doc", lambda *a, **kw: doc_of(TSLA))
        args = ["plan", "--symbol", "TSLA", "--entry", "364.18", "--date", "2026-10-19", "--entry-bar", "8",
                "--stop", "atr:1.5", "--now", "2026-10-19 10:15", "--json"]
        c1, off, _ = run(exitp, args + ["--offline", TSLA])
        c2, mas, err = run(exitp, args + ["--source", "massive"])
        self.assertEqual((c1, c2), (0, 0), err)
        self.assertEqual(json.loads(off), json.loads(mas))
        self.assertEqual(self.calls[0][1][2:6], ("TSLA", dt.date(2026, 10, 19), "5m", False))


class TimeMachine(Wired):
    def test_run(self):
        tm = load("trader-timemachine", "timemachine")
        self.serve("fetch_history_doc", lambda *a, **kw: doc_of(TM60))
        args = ["run", "--plan", PLAN, "--now", "2026-10-19 10:15", "--replays", "500", "--json"]
        c1, off, _ = run(tm, args + ["--offline", TM60])
        c2, mas, err = run(tm, args + ["--source", "massive"])
        self.assertEqual((c1, c2), (0, 0), err)
        a, b = json.loads(off), json.loads(mas)
        self.assertEqual((a.pop("source"), b.pop("source")), ("offline", "massive"))
        self.assertEqual(a, b)
        self.assertEqual(b["mc"]["pool_sessions"], 59)
        self.assertEqual(b["data"]["range"], "60d")                  # read from meta.range
        name, args_, kw = self.calls[0]
        self.assertEqual((args_[2], args_[3].isoformat(), args_[4].isoformat(), args_[5]),
                         ("TSLA", "2026-07-27", "2026-10-19", "auto"))      # 60 sessions ending on the plan day
        run(tm, ["run", "--plan", PLAN, "--now", "2026-10-19 10:15", "--replays", "10", "--json", "--source",
                 "massive", "--years", "1"])
        self.assertEqual(self.calls[-1][1][3].isoformat(), "2025-10-19")

    def test_the_source_is_the_documents_own(self):
        tm = load("trader-timemachine", "timemachine")

        def from_kalex(*a, **kw):
            d = doc_of(TM60)
            d["chart"]["result"][0]["meta"]["mjonir"] = {"source": "kalex", "adjusted": True}
            return d
        self.serve("fetch_history_doc", from_kalex)
        code, out, err = run(tm, ["run", "--plan", PLAN, "--now", "2026-10-19 10:15", "--replays", "10", "--json",
                                  "--source", "massive"])
        self.assertEqual((code, json.loads(out)["source"]), (0, "kalex"), err)


class Alerts(Wired):
    def test_quote_and_prices(self):
        alerts = load("trader-alerts", "alerts")
        self.serve("fetch_quote_docs", ({"TSLA": doc_of(os.path.join(AFIX, "yahoo-TSLA.json"))}, {}))
        c1, off, _ = run(alerts, ["quote", "TSLA", "ZZZZ", "--offline", AFIX, "--json", "--now", "2026-10-19 10:50"])
        c2, mas, err = run(alerts, ["quote", "TSLA", "ZZZZ", "--source", "massive", "--json", "--now",
                                    "2026-10-19 10:50", "--write"])
        self.assertEqual((c1, c2), (0, 0), err)
        a, b = json.loads(off), json.loads(mas)
        self.assertEqual((a["quotes"]["TSLA"].pop("source"), b["quotes"]["TSLA"].pop("source")), ("yahoo", "massive"))
        self.assertEqual(a["quotes"], b["quotes"])
        self.assertEqual(b["errors"], ["no Massive quote for ZZZZ"])
        self.assertEqual(len(self.calls), 1)                         # one snapshot call for every ticker
        with open(os.path.join("trader", "prices.json")) as fh:
            p = json.load(fh)
        self.assertEqual((p["source"], p["detail"]["TSLA"]["source"]), ("massive", "massive"))

    def test_offline_massive_files(self):
        alerts = load("trader-alerts", "alerts")
        os.mkdir("q")
        shutil.copy(os.path.join(AFIX, "yahoo-TSLA.json"), os.path.join("q", "massive-TSLA.json"))
        code, out, _ = run(alerts, ["quote", "TSLA", "--source", "massive", "--offline", "q", "--json"])
        self.assertEqual(json.loads(out)["quotes"]["TSLA"]["source"], "massive")
        self.assertEqual(self.calls, [])


class News(Wired):
    def setUp(self):
        super().setUp()
        self.news = load("trader-news", "news")

        def from_fixtures(fetcher, url, name, sec=False):
            p = os.path.join(NFIX, name)
            if not os.path.isfile(p):
                raise self.news.NewsError("offline: no file %s" % p)
            with open(p, "rb") as fh:
                return fh.read()
        self.real_get = self.news.Fetcher.get
        self.news.Fetcher.get = from_fixtures

    def tearDown(self):
        self.news.Fetcher.get = self.real_get
        super().tearDown()

    def test_moves_and_a_third_headline_source(self):
        self.serve("fetch_quote_docs", ({"TSLA": doc_of(os.path.join(NFIX, "chart-TSLA.json"))}, {}))
        rows = _mj.fixture("news-TSLA.json")["results"]
        rss_link = "https://finance.yahoo.com/markets/article/tech-rebounds-as-semiconductor-stocks-jump-alphacheck-1" \
                   "35003909.html?.tsrc=rss"
        dup = dict(rows[0], id="dup1", article_url=rss_link, published_utc="2026-10-19T13:50:03Z")
        fresh = dict(rows[1], id="new1", published_utc="2026-10-19T14:00:00Z", article_url="https://example.com/a")
        self.serve("fetch_news", lambda client, syms, since, limit=50: {"TSLA": json.dumps([dup, fresh])})
        base = ["--tickers", "TSLA", "--no-sec", "--now", "2026-10-19T15:00:00Z", "--json", "--dry-run"]
        c1, off, _ = run(self.news, base + ["--offline", NFIX])
        c2, mas, err = run(self.news, base + ["--source", "massive"])
        a, b = json.loads(off), json.loads(mas)
        self.assertEqual(a["moves"], b["moves"])
        self.assertEqual(len(b["items"]), len(a["items"]) + 1)         # the duplicate URL folded into RSS's item
        extra = [i for i in b["items"] if i["source"] == "Massive news"]
        self.assertEqual([i["link"] for i in extra], ["https://example.com/a"])
        self.assertEqual(extra[0]["time"], "2026-10-19T14:00:00+00:00")
        since = [c for c in self.calls if c[0] == "fetch_news"][0][1][2]
        self.assertEqual(since.isoformat(), "2026-10-17T15:00:00+00:00")   # --hours 48 back from --now

    def test_offline_massive_files_and_seen_state(self):
        os.mkdir("n")
        for f in ("yahoo-TSLA.xml", "chart-TSLA.json"):
            shutil.copy(os.path.join(NFIX, f), "n")
        shutil.copy(os.path.join(NFIX, "chart-TSLA.json"), os.path.join("n", "massive-TSLA.json"))
        rows = [dict(_mj.fixture("news-TSLA.json")["results"][0], published_utc="2026-10-19T14:10:00Z")]
        with open(os.path.join("n", "massive-news-TSLA.json"), "w") as fh:
            json.dump(rows, fh)
        self.news.Fetcher.get = self.real_get
        args = ["--tickers", "TSLA", "--no-sec", "--now", "2026-10-19T15:00:00Z", "--json", "--offline", "n",
                "--state", "s.json", "--source", "massive"]
        code, out, _ = run(self.news, args)
        self.assertEqual(code, 0)
        first = json.loads(out)
        self.assertIn("Massive news", [i["source"] for i in first["items"]])
        self.assertEqual(first["moves"][0]["price"], 366.48)
        code, out, _ = run(self.news, args)                           # the same seen-state: nothing new
        self.assertEqual((code, json.loads(out)["items"]), (1, []))
        self.assertEqual(self.calls, [])


class CalendarOverlay(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.old = os.environ["TRADER_CALENDAR"]

    def tearDown(self):
        os.environ["TRADER_CALENDAR"] = self.old
        shutil.rmtree(self.d)

    def write(self, doc):
        p = os.path.join(self.d, "calendar.json")
        with open(p, "w") as fh:
            fh.write(doc if isinstance(doc, str) else json.dumps(doc))
        os.environ["TRADER_CALENDAR"] = p

    def test_the_overlay_extends_every_script(self):
        from mjonir import calendar as K
        self.write(K.build_calendar_doc(_mj.client(), clock="2026-11-02 23:00"))
        mods = {name: load(folder, name) for folder, name in SCRIPTS}
        for name, m in mods.items():
            self.assertIn("2028-11-24", m.NYSE_EARLY_CLOSE, name)
            if hasattr(m, "NYSE_HOLIDAYS"):
                self.assertIn("2028-11-23", m.NYSE_HOLIDAYS, name)
            if hasattr(m, "CALENDAR_YEARS"):
                self.assertEqual(m.CALENDAR_YEARS, (2026, 2027, 2028), name)
        entry, check, alerts = mods["entry"], mods["check"], mods["alerts"]
        ch = entry.parse_chart(json.dumps(doc_of(TSLA)), "TSLA")
        res = entry.evaluate(ch, entry.parse_now("2028-01-05 10:00"))
        self.assertTrue(res["calendar_known"])
        self.assertFalse(any("Holiday list covers" in ln for ln in entry.describe(res)))
        _, warns = check.window_check(check.to_eastern(check.parse_now("2028-01-05 10:00")),
                                      {"no_entries_before": "09:45", "no_entries_after": "15:30"})
        self.assertEqual(warns, [])
        self.assertTrue(alerts.market_status(alerts.parse_now("2028-03-01T10:00"))["calendar_known"])
        self.assertEqual(mods["scan"].session(dt.date(2028, 11, 24))[1], dt.time(13, 0))
        tm = mods["timemachine"]
        self.assertIn("2028-11-24", tm.NYSE_EARLY_CLOSE)

    def test_absent_or_broken_keeps_the_seeds(self):
        for doc in ("{nope", "[1, 2]", '{"covered_years": ["x"]}'):
            self.write(doc)
            for folder, name in SCRIPTS:
                m = load(folder, name)
                self.assertNotIn("2028-11-24", m.NYSE_EARLY_CLOSE, name)
                if hasattr(m, "CALENDAR_YEARS"):
                    self.assertEqual(m.CALENDAR_YEARS, (2026, 2027), name)
        entry = load("trader-entry", "entry")
        ch = entry.parse_chart(json.dumps(doc_of(TSLA)), "TSLA")
        self.assertFalse(entry.evaluate(ch, entry.parse_now("2028-01-05 10:00"))["calendar_known"])

    def test_the_overlay_is_the_same_twelve_lines_everywhere(self):
        bodies = set()
        for folder, name in SCRIPTS:
            with open(os.path.join(ROOT, folder, name + ".py"), encoding="utf-8") as fh:
                src = fh.read()
            a = src.index("def _calendar_overlay(g):")
            b = src.index("\n\n\n", a)
            body = src[a:b]
            self.assertEqual(len(body.splitlines()), 12, name)
            self.assertIn("\n_calendar_overlay(globals())\n", src, name)
            bodies.add(body)
        self.assertEqual(len(bodies), 1)


if __name__ == "__main__":
    unittest.main()
