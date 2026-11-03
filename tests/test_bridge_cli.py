"""mjonir.bridge: every verb against the injected client (the fake opener serving the recorded
fixtures) writes the files it names, and the exit codes are 0 ok, 1 refused, 2 unverified."""

import contextlib
import gzip
import io
import json
import os
import shutil
import tempfile
import unittest
import urllib.error

import _mj
from _load import load
from mjonir import bridge
from mjonir import config as C
from mjonir import universe as U

entry = load("trader-entry", "entry")
scan = load("trader-scanner", "scan")
alerts = load("trader-alerts", "alerts")


def grouped_1016(url, path, q):
    from mjonir import calendar as K
    t = K.ms_of(K.parse_now("2026-10-16 00:00"))
    return {"status": "OK", "adjusted": True, "resultsCount": 2,
            "results": [{"T": "SPY", "t": t, "o": 1, "h": 1, "l": 1, "c": 660.0, "v": 1},
                        {"T": "TSLA", "t": t, "o": 1, "h": 1, "l": 1, "c": 354.72, "v": 1}]}


def run(argv, opener=None):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = bridge.main(argv, client_factory=lambda: _mj.client(opener or _mj.FakeOpener(
            extra={"/v2/aggs/grouped/locale/us/market/stocks/2026-10-16": grouped_1016})))
    return code, out.getvalue(), err.getvalue()


class Verbs(unittest.TestCase):
    def setUp(self):
        self.cwd = os.getcwd()
        self.d = tempfile.mkdtemp()
        os.chdir(self.d)

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.d)

    def test_probe_three_outcomes(self):
        code, out, _ = run(["probe", "--json"])
        self.assertEqual((code, json.loads(out)["outcome"]), (0, "authenticated"))
        self.assertIn("Benzinga", json.loads(out)["not_entitled"])

        def rejected(url, headers, timeout):
            raise _mj.http_error(url, 403)

        def unreachable(url, headers, timeout):
            raise urllib.error.URLError("unreachable")
        self.assertEqual(run(["probe"], rejected)[0], 1)
        code, out, _ = run(["probe"], unreachable)
        self.assertEqual(code, 2)
        self.assertIn("UNVERIFIED", out)

    def test_calendar(self):
        code, out, _ = run(["calendar", "--out", "cal.json", "--now", "2026-11-02 23:00"])
        self.assertEqual(code, 0, out)
        with open("cal.json") as fh:
            doc = json.load(fh)
        self.assertEqual(doc["covered_years"], [2026, 2027, 2028])
        self.assertIn("covers 2026, 2027, 2028", out)

    def test_intraday_files_and_a_refused_day(self):
        code, out, err = run(["intraday", "TSLA", "--day", "2026-10-19", "--out", "d"])
        self.assertEqual(code, 0, err)
        self.assertTrue(os.path.exists(os.path.join("d", "TSLA.json")))
        out2, err2 = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out2), contextlib.redirect_stderr(err2):
            c = entry.main(["check", "TSLA", "--offline", "d", "--now", "2026-10-19 10:15"])
        self.assertEqual(c, 0)
        self.assertIn("TRIGGERED 10:15 AM at $364.18", out2.getvalue())
        code, out, err = run(["intraday", "TSLA", "--day", "2026-10-18", "--out", "d"])
        self.assertEqual(code, 1)
        self.assertIn("weekend", out + err)
        code, _, err = run(["intraday", "TSLA,ZZZZ", "--day", "2026-10-19", "--out", "w", "--bundle", "--json"])
        self.assertEqual(code, 0, err)
        p = os.path.join("w", "wall5m-2026-10-19.json.gz")
        with gzip.open(p, "rt") as fh:
            self.assertEqual(sorted(json.load(fh)), ["TSLA"])
        data, errors = scan.load_offline(p)
        self.assertEqual(list(data), ["TSLA"])
        code, out, err = run(["intraday", "ZZZZ", "YYYY", "--day", "2026-10-19", "--out", "z", "--json"])
        self.assertEqual(code, 1, err)
        self.assertEqual(sorted(json.loads(out)["failed"]), ["YYYY", "ZZZZ"])

    def test_history(self):
        code, out, err = run(["history", "TSLA", "--from", "2026-10-19", "--to", "2026-10-19", "--source", "api",
                              "--out", "h", "--json"])
        self.assertEqual(code, 0, err)
        doc = json.loads(out)
        self.assertEqual((doc["range"], doc["bars"], doc["source"]), ("1d", 78, "massive"))
        with gzip.open(os.path.join("h", "TSLA-60d5m.json.gz"), "rt") as fh:
            self.assertEqual(len(json.load(fh)["chart"]["result"][0]["timestamp"]), 78)
        code, _, err = run(["history", "TSLA", "--from", "2026-10-17", "--to", "2026-10-18", "--source", "api"])
        self.assertEqual(code, 1)
        self.assertIn("no session", err)

    def test_daily_bundle(self):
        code, out, err = run(["daily", "--symbols", "TSLA", "SPY", "--sessions", "1", "--end", "2026-10-19", "--out",
                              "dl", "--json"])
        self.assertEqual(code, 0, err)
        p = os.path.join("dl", "daily-spark-2026-10-19.json")
        self.assertEqual(json.loads(out)["out"], p)
        data, _ = scan.load_offline(p)
        self.assertEqual(sorted(data), ["SPY", "TSLA"])
        code, _, err = run(["daily", "--sessions", "1"])
        self.assertEqual(code, 1)
        self.assertIn("trader/universe.txt", err)

    def test_quotes_and_news(self):
        code, out, err = run(["quotes", "TSLA,AAPL", "ZZZZ", "--out", "q", "--now", "2026-11-02 23:30", "--json"])
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(os.listdir("q")), ["massive-AAPL.json", "massive-TSLA.json"])
        out2 = io.StringIO()
        with contextlib.redirect_stdout(out2):
            alerts.main(["quote", "TSLA", "--source", "massive", "--offline", "q", "--json"])
        self.assertEqual(json.loads(out2.getvalue())["quotes"]["TSLA"]["source"], "massive")
        code, out, err = run(["news", "TSLA", "--out", "n", "--hours", "24", "--now", "2026-10-20 10:00", "--json"])
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["since"], "2026-10-19T14:00:00Z")
        with open(os.path.join("n", "massive-news-TSLA.json")) as fh:
            self.assertEqual(len(json.load(fh)), 2)

    def test_universe(self):
        ref = _mj.fixture("reference-tickers-page.json")

        def reference(url, path, q):
            if q.get("type") == "ADRC":
                return {"status": "OK", "count": 1, "results": [dict(ref["results"][0], ticker="SVIA", type="ADRC")]}
            if q.get("cursor") == "PAGE2":
                return {"status": "OK", "count": 2, "results": [dict(ref["results"][0], ticker=t, name=t + " Inc")
                                                                for t in ("TSLA", "NVDA")]}
            return ref
        op = _mj.FakeOpener(extra={"/v3/reference/tickers": reference})
        saved = dict(U.MIN_REFERENCE_ROWS)
        U.MIN_REFERENCE_ROWS.update({"CS": 1, "ADRC": 1})
        try:
            code, out, err = run(["universe", "--as-of", "2026-10-19", "--sessions", "1", "--json"], op)
            self.assertEqual(code, 0, err)
            doc = json.loads(out)
            self.assertEqual(doc["out"], os.path.join("trader", "universe.txt"))
            self.assertEqual(scan.symbols_from_file(doc["out"]), ["AAPL", "NVDA", "TSLA"])
            self.assertTrue(os.path.exists(doc["record"]))
            self.assertEqual(doc["funnel"]["keep"], 3)
        finally:
            U.MIN_REFERENCE_ROWS.clear()
            U.MIN_REFERENCE_ROWS.update(saved)
        code, _, err = run(["universe", "--as-of", "2026-10-19", "--sessions", "1"], op)
        self.assertEqual(code, 1)                                   # 31 CS rows: under the 3,000 sanity floor
        self.assertIn("sanity floor", err)

    def test_status_names_the_variable_never_the_value(self):
        env = os.path.join(self.d, "repo.env")
        with open(env, "w") as fh:
            fh.write("MASSIVE_API_KEY=%s\n" % _mj.FAKE_KEY)
        saved_path, saved_key = C.repo_env_path, os.environ.get("MJONIR_API_KEY")
        C.repo_env_path = lambda repo=None: __import__("pathlib").Path(env)
        os.environ["MJONIR_API_KEY"] = _mj.FAKE_KEY
        try:
            code, out, err = run(["status"])
            self.assertEqual(code, 0, err)
            self.assertFalse(_mj.FAKE_KEY in out + err)
            self.assertIn("present in MJONIR_API_KEY", out)
            self.assertIn("WARNING", out)
            self.assertIn("Not entitled: options", out)
            self.assertIn("Kalex 5m: missing", out)
            code, out, _ = run(["status", "--json"])
            doc = json.loads(out)
            self.assertEqual(doc["key"]["repo_env_key_like"], ["MASSIVE_API_KEY"])
            self.assertEqual(doc["probe"]["outcome"], "authenticated")
            self.assertFalse(_mj.FAKE_KEY in out)
        finally:
            C.repo_env_path = saved_path
            if saved_key is None:
                os.environ.pop("MJONIR_API_KEY")
            else:
                os.environ["MJONIR_API_KEY"] = saved_key

    def test_no_verb_and_errors_never_carry_the_key(self):
        self.assertEqual(run([])[0], 1)

        def leaky(url, headers, timeout):
            raise ValueError("boom %s" % headers["Authorization"])
        code, out, err = run(["calendar"], leaky)
        self.assertEqual(code, 2)
        self.assertFalse(_mj.FAKE_KEY in out + err)


if __name__ == "__main__":
    unittest.main()
