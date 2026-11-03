"""scan.py rvol and mjonir/rvol.py (docs/PREREG_RVOL_ORB.md, plan step 3.4), offline: a synthetic store stands in
for Massive (mjonir.rvol.make_fetch is replaced), so no test asks the network or opens a real store."""

import contextlib
import datetime as dt
import io
import json
import math
import os
import shutil
import tempfile
import unittest

import _mj  # noqa: F401
import synth
from _load import load
from mjonir import calendar as K
from mjonir import rvol as R
from mjonir import yahoo_shape as Y

scan = load("trader-scanner", "scan")
record = load("trader-record", "record")
entry = load("trader-entry", "entry")

DAY = dt.date(2026, 10, 19)
CAL = K.Calendar()
FLOORS = {"min_price": 5.0, "min_adv_usd": 2e7, "min_avg_volume": 1e6}


def sessions_before(day, n):
    return CAL.sessions_back(CAL.prev_session(day), n)


class Store(object):
    """A synthetic market: daily rows (grouped), 9:30 bars for D and the 14 sessions before, a snapshot."""

    def __init__(self, names, day=DAY):
        self.day = day
        self.adv_days = sessions_before(day, R.ADV_N)
        self.hist_days = sessions_before(day, R.RVOL_N)
        self.daily = {}         # {date: {SYM: {o,h,l,c,v}}}
        self.bars = {}          # {SYM: {date_iso: {o,h,l,c,v}}}
        self.snap = {}
        self.split_rows = []
        self.calls = {"grouped": [], "snapshot": 0, "first_bars": []}
        for i, sym in enumerate(sorted(names)):
            self.add(sym, price=20.0 + i, daily_v=2000000.0, hist_v=[1000.0 + 10 * k for k in range(R.RVOL_N)],
                     d_bar=(20.0 + i, 20.5 + i, 19.8 + i, 20.2 + i, 5000.0 + 100 * i))

    def add(self, sym, price, daily_v, hist_v, d_bar, days=None):
        for d in (self.adv_days if days is None else days):
            self.daily.setdefault(d, {})[sym] = {"o": price, "h": price * 1.01, "l": price * 0.99, "c": price,
                                                 "v": daily_v}
        per = {}
        for d, v in zip(self.hist_days, hist_v):
            if v is not None:
                per[d.isoformat()] = {"o": price, "h": price, "l": price, "c": price, "v": v}
        if d_bar is not None:
            o, h, l, c, v = d_bar
            per[self.day.isoformat()] = {"o": o, "h": h, "l": l, "c": c, "v": v}
        self.bars[sym] = per
        self.snap[sym] = (d_bar[4] if d_bar else 0.0) * 3

    # the Fetch interface
    def grouped(self, day):
        self.calls["grouped"].append(day)
        return dict(self.daily.get(day, {}))

    def splits(self, since):
        return list(self.split_rows)

    def snapshot(self, day):
        self.calls["snapshot"] += 1
        return dict(self.snap), {"rows": len(self.snap), "other_day": 0}

    def first_bars(self, symbols, days):
        self.calls["first_bars"].append((list(symbols), list(days)))
        want = set(d.isoformat() for d in days)
        return dict((s, dict((k, v) for k, v in self.bars[s].items() if k in want)) for s in symbols
                    if s in self.bars), {}

    def requests(self):
        return 0


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = scan.main(argv)
    return code, out.getvalue(), err.getvalue()


class Rules(unittest.TestCase):
    def test_the_rvol_arithmetic(self):
        st = Store(["AAA", "BBB"])
        st.add("XYZ", 30.0, 2e6, [100.0 + k for k in range(R.RVOL_N)], (30.0, 31.0, 29.9, 30.6, 2000.0))
        doc = R.scan(st, CAL, DAY, sorted(st.bars), FLOORS, live=True)
        row = [r for r in doc["rows"] if r["symbol"] == "XYZ"][0]
        mean = sum(100.0 + k for k in range(R.RVOL_N)) / R.RVOL_N
        self.assertEqual(row["rvol"], 2000.0 / mean)
        self.assertEqual(row["rank"], 1)
        self.assertEqual((row["direction"], row["fire"]), ("up", True))
        self.assertEqual(row["first_bar"], {"o": 30.0, "h": 31.0, "l": 29.9, "c": 30.6, "v": 2000.0})
        self.assertAlmostEqual(row["adv_usd"], 30.0 * 2e6)
        self.assertEqual(row["price"], 30.0)
        self.assertEqual(sorted(row), sorted(["symbol", "rvol", "rank", "first_bar", "direction", "adv_usd", "price",
                                              "fire", "volume_x"]))
        # the stage-2 history is the 14 sessions strictly before D, and D itself
        syms, days = st.calls["first_bars"][0]
        self.assertEqual(days, st.hist_days + [DAY])

    def test_thirteen_prior_sessions_are_excluded_and_counted(self):
        st = Store(["AAA", "BBB"])
        hist = [100.0] * R.RVOL_N
        hist[5] = None          # one of the 14 prior 9:30 bars is missing
        st.add("SHORT", 30.0, 2e6, hist, (30.0, 31.0, 29.9, 30.6, 9000.0))
        doc = R.scan(st, CAL, DAY, sorted(st.bars), FLOORS)
        self.assertNotIn("SHORT", [r["symbol"] for r in doc["rows"]])
        self.assertEqual(doc["funnel"]["rvol_history_short"], 1)
        self.assertEqual(doc["funnel"]["eligible"], 2)
        # and a zero volume counts the same as a missing bar
        st2 = Store(["AAA"])
        st2.add("ZERO", 30.0, 2e6, [0.0] + [100.0] * (R.RVOL_N - 1), (30.0, 31.0, 29.9, 30.6, 9000.0))
        self.assertEqual(R.scan(st2, CAL, DAY, sorted(st2.bars), FLOORS)["funnel"]["rvol_history_short"], 1)

    def test_the_floors_never_read_the_day_itself(self):
        st = Store(["AAA"])
        st.add("THIN", 50.0, 500000.0, [100.0] * R.RVOL_N, (50.0, 51.0, 49.9, 50.6, 9000.0))   # $25M, 500k shares
        a = R.scan(st, CAL, DAY, sorted(st.bars), FLOORS)
        # plant a huge volume on D in every daily source the fake holds: the floors must not move
        st.daily[DAY] = {"THIN": {"o": 30.0, "h": 30.0, "l": 30.0, "c": 30.0, "v": 9e12},
                         "AAA": {"o": 1.0, "h": 1.0, "l": 1.0, "c": 1.0, "v": 1.0}}
        st.snap["THIN"] = 9e12
        b = R.scan(st, CAL, DAY, sorted(st.bars), FLOORS)
        self.assertEqual(a["funnel"], b["funnel"])
        self.assertEqual(a["stage1"]["passed_floors"], b["stage1"]["passed_floors"])
        self.assertEqual(b["funnel"]["below_adv_shares"], 1)
        self.assertNotIn(DAY, st.calls["grouped"])
        self.assertEqual(sorted(set(st.calls["grouped"])), st.adv_days)
        self.assertTrue(all(d < DAY for d in st.calls["grouped"]))

    def test_ranking_ties_by_ticker_and_the_doji(self):
        st = Store([])
        hist = [100.0] * R.RVOL_N
        st.add("BBB", 30.0, 2e6, hist, (30.0, 31.0, 29.0, 30.5, 500.0))    # rvol 5, up
        st.add("AAA", 30.0, 2e6, hist, (30.0, 31.0, 29.0, 29.5, 500.0))    # rvol 5, down: ties go by ticker
        st.add("DOJ", 30.0, 2e6, hist, (30.0, 31.0, 29.0, 30.0, 900.0))    # rvol 9, a doji
        st.add("TNY", 30.0, 2e6, hist, (30.0, 31.0, 29.0, 30.0 + 1e-9, 100.0))  # rvol 1, up by a hair (unrounded)
        doc = R.scan(st, CAL, DAY, sorted(st.bars), FLOORS, top=3)
        self.assertEqual([r["symbol"] for r in doc["rows"]], ["DOJ", "AAA", "BBB"])
        self.assertEqual([r["rank"] for r in doc["rows"]], [1, 2, 3])
        self.assertEqual([r["direction"] for r in doc["rows"]], ["doji", "down", "up"])
        self.assertEqual(doc["fires"], ["BBB"])     # ranked first, direction second: the doji is not up
        doc = R.scan(st, CAL, DAY, sorted(st.bars), FLOORS, top=20)
        self.assertEqual(doc["fires"], ["BBB", "TNY"])
        self.assertEqual(R.direction(30.0, 30.0), "doji")
        self.assertFalse(R.is_up(30.0, 30.0))
        self.assertTrue(R.is_up(30.0, 30.0 + 1e-9))

    def test_the_guards_and_the_floors(self):
        st = Store([])
        hist = [100.0] * R.RVOL_N
        st.add("OK", 30.0, 2e6, hist, (30.0, 31.0, 29.0, 30.5, 500.0))
        st.add("CHEAP", 4.0, 9e6, hist, (4.0, 4.1, 3.9, 4.05, 500.0))
        st.add("ILLIQ", 6.0, 2e6, hist, (6.0, 6.1, 5.9, 6.05, 500.0))          # 12M a day
        st.add("GAP", 30.0, 2e6, hist, (80.0, 81.0, 79.0, 80.5, 500.0))        # opens 2.67x the prior close
        st.add("SPLIT", 30.0, 2e6, hist, (30.0, 31.0, 29.0, 30.5, 500.0))
        st.add("NOBAR", 30.0, 2e6, hist, None)
        st.add("YOUNG", 30.0, 2e6, hist, (30.0, 31.0, 29.0, 30.5, 500.0), days=st.adv_days[1:])   # 19 sessions
        st.split_rows = [{"ticker": "SPLIT", "execution_date": st.adv_days[3].isoformat()},
                         {"ticker": "OK", "execution_date": (st.adv_days[0] - dt.timedelta(days=3)).isoformat()}]
        doc = R.scan(st, CAL, DAY, sorted(st.bars), FLOORS, live=False)
        f = doc["funnel"]
        self.assertEqual({k: f[k] for k in R.CAUSES}, {
            "insufficient_history": 1, "split_guard": 1, "below_price": 1, "below_adv_usd": 1, "below_adv_shares": 0,
            "no_first_bar": 1, "gap_guard": 1, "rvol_history_short": 0})
        self.assertEqual([r["symbol"] for r in doc["rows"]], ["OK"])

    def test_rows_false_counts_the_same_and_computes_nothing_per_name(self):
        st = Store(["AAA", "BBB"])
        st.add("SHORT", 30.0, 2e6, [None] + [100.0] * (R.RVOL_N - 1), (30.0, 31.0, 29.9, 30.6, 9000.0))
        passed = dict((s, {"price": 25.0, "adv_usd": 5e7, "adv_shares": 2e6}) for s in ("AAA", "BBB", "SHORT"))
        firsts = dict((s, st.bars[s][DAY.isoformat()]) for s in passed)

        def history(sym):
            return [(st.bars[sym].get(d.isoformat()) or {}).get("v") for d in st.hist_days]
        full, c_full = R.bar_stage(passed, firsts, history)
        names, c_names = R.bar_stage(passed, firsts, history, rows=False)
        self.assertEqual(c_full, c_names)
        self.assertEqual(names, ["AAA", "BBB"])
        self.assertEqual([r["symbol"] for r in full], names)

    def test_names_with_no_snapshot_row_are_counted(self):
        st = Store(["AAA", "BBB", "CCC"])
        del st.snap["BBB"]
        st.snap["CCC"] = 0.0
        doc = R.scan(st, CAL, DAY, sorted(st.bars), FLOORS)
        s1 = doc["stage1"]
        self.assertEqual((s1["no_snapshot"], s1["zero_volume"], s1["with_volume"], s1["shortlist"]), (1, 1, 1, 1))

    def test_a_replay_shortlist_reads_the_days_volume_for_stage_one_only(self):
        st = Store(["AAA", "BBB", "CCC"])
        st.daily[DAY] = dict((s, {"o": 1, "h": 1, "l": 1, "c": 1, "v": v}) for s, v in
                             (("AAA", 9e6), ("BBB", 1e6), ("CCC", 5e6)))
        said = []
        doc = R.scan(st, CAL, DAY, sorted(st.bars), FLOORS, live=False, shortlist=2, say=said.append)
        self.assertEqual(st.calls["snapshot"], 0)
        self.assertIn(DAY, st.calls["grouped"])
        self.assertIn("whole-session volume", doc["stage1"]["basis"])
        self.assertEqual(st.calls["first_bars"][0][0], ["AAA", "CCC"])
        self.assertEqual((doc["stage1"]["shortlist"], doc["params"]["shortlist"]), (2, 2))
        self.assertIn("5-minute bars for 2 names", said[0])
        doc = R.scan(Store(["AAA", "BBB", "CCC"]), CAL, DAY, ["AAA", "BBB", "CCC"], FLOORS, live=False,
                     say=said.append)
        self.assertEqual((doc["stage1"]["shortlist"], doc["params"]["shortlist"]), (3, None))
        self.assertIn("5-minute bars for 3 names", said[1])

    def test_first_bar_from_5m_rows(self):
        s = synth.make_session(DAY, 3)
        rows = synth.as_tuples(s)
        fb = R.first_bar(rows, DAY)
        self.assertEqual(fb, {"o": s[0]["o"], "h": s[0]["h"], "l": s[0]["l"], "c": s[0]["c"], "v": float(s[0]["v"])})
        self.assertIsNone(R.first_bar(rows[1:], DAY))


class Cli(unittest.TestCase):
    NAMES = ("fetch_daily_rows", "fetch_adv_usd")

    def setUp(self):
        self.cwd = os.getcwd()
        self.d = tempfile.mkdtemp()
        os.chdir(self.d)
        self.saved_fetch = R.make_fetch
        self.saved = dict((n, getattr(Y, n)) for n in self.NAMES)
        self.store = Store(["AAA", "BBB", "CCC"])
        self.store.add("UPP", 30.0, 2e6, [100.0] * R.RVOL_N, (30.0, 31.0, 29.8, 30.6, 5000.0))
        self.store.add("DWN", 40.0, 2e6, [100.0] * R.RVOL_N, (40.0, 40.2, 39.0, 39.2, 4000.0))
        R.make_fetch = lambda cal=None: self.store
        # trader-exit's datr stop and cost card ask Massive for daily bars and the ADV: a synthetic answer
        Y.fetch_daily_rows = self.daily_rows
        Y.fetch_adv_usd = lambda client, cal, symbol, asof, n=20: 6e7
        self.rec = os.path.join(self.d, "rec")

    def tearDown(self):
        R.make_fetch = self.saved_fetch
        for n, f in self.saved.items():
            setattr(Y, n, f)
        os.chdir(self.cwd)
        shutil.rmtree(self.d)

    @staticmethod
    def daily_rows(client, cal, symbol, start, end):
        out = []
        for d in CAL.sessions_between(start, end):     # the rows depend on the date, not on the range asked
            t = K.ms_of(dt.datetime.combine(d, dt.time(9, 30), tzinfo=K.ET))
            out.append((t, 30.0, 30.0 + 0.5 + 0.01 * (d.toordinal() % 7), 29.5, 30.0, 2e6))
        return out

    def test_refused_before_935_and_under_yahoo(self):
        code, out, err = run(["rvol", "--source", "massive", "--symbols", "AAA", "--now", "2026-10-19 09:34"])
        self.assertEqual(code, 1)
        self.assertIn("9:35", err)
        self.assertEqual(self.store.calls["grouped"], [])          # refused before any question
        code, out, err = run(["rvol", "--symbols", "AAA", "--now", "2026-10-19 09:40"])
        self.assertEqual(code, 1)
        self.assertIn("--source massive", err)
        code, out, err = run(["rvol", "--source", "massive", "--symbols", "AAA", "--now", "2026-10-18 10:00"])
        self.assertEqual(code, 1)
        self.assertIn("weekend", err)
        code, out, err = run(["rvol", "--source", "massive", "--symbols", "AAA", "--date", "2026-10-20",
                              "--now", "2026-10-19 10:00"])
        self.assertEqual((code, "after today" in err), (1, True))
        code, out, err = run(["rvol", "--source", "massive", "--symbols", "AAA,BBB", "--now", "2026-10-19 09:35",
                              "--no-record", "--json"])
        self.assertEqual(code, 0, err)

    def test_the_json_and_the_files(self):
        code, out, err = run(["rvol", "--source", "massive", "--symbols", "AAA,BBB,CCC,UPP,DWN", "--now",
                              "2026-10-19 09:40", "--no-record", "--json"])
        self.assertEqual(code, 0, err)
        doc = json.loads(out)
        self.assertEqual(doc["mode"], "rvol")
        self.assertEqual(doc["setup"], "rvol_orb5")
        self.assertEqual(doc["floors_from"]["min_avg_volume"], "the default (no floors.min_avg_volume in the config)")
        self.assertEqual([r["symbol"] for r in doc["rows"]][:2], ["UPP", "DWN"])
        self.assertEqual(doc["fires"], ["UPP", "CCC", "BBB", "AAA"])      # rank order
        with open("trader/rvol.json") as fh:
            self.assertEqual(json.load(fh)["rows"], doc["rows"])
        with open("trader/watchlist.json") as fh:
            wl = json.load(fh)
        self.assertEqual([h["symbol"] for h in wl["hits"]], ["UPP", "CCC", "BBB", "AAA"])
        self.assertTrue(all(h["setup"] == "rvol_orb5" and h["setups"] == ["rvol_orb5"] for h in wl["hits"]))
        self.assertIn("section 11", doc["live_vs_study"])
        self.assertIn("not a signal", doc["note"])

    def test_the_watchlist_keeps_the_other_hits(self):
        os.makedirs("trader")
        with open("trader/watchlist.json", "w") as fh:
            json.dump({"created_by": "trader-scanner", "mode": "daily", "hits": [
                {"symbol": "UPP", "setups": ["breakout_20d"], "price": 29.0},
                {"symbol": "OLD", "setups": ["rvol_orb5"], "setup": "rvol_orb5", "price": 9.0},
                {"symbol": "KEEP", "setups": ["bull_flag", "rvol_orb5"], "price": 9.0, "rvol": {"rank": 3}}]}, fh)
        code, out, err = run(["rvol", "--source", "massive", "--symbols", "UPP,DWN", "--now", "2026-10-19 09:40",
                              "--no-record"])
        self.assertEqual(code, 0, err)
        with open("trader/watchlist.json") as fh:
            wl = json.load(fh)
        self.assertEqual(wl["mode"], "daily")
        by = dict((h["symbol"], h) for h in wl["hits"])
        self.assertEqual(sorted(by), ["KEEP", "UPP"])
        self.assertEqual(by["UPP"]["setups"], ["breakout_20d", "rvol_orb5"])
        self.assertEqual(by["KEEP"]["setups"], ["bull_flag"])
        self.assertNotIn("rvol", by["KEEP"])
        self.assertEqual(wl["rvol"]["fires"], ["UPP"])
        self.assertIn("section 11", out)
        self.assertIn("not a signal", out)

    def test_a_replay_has_no_stage_one_and_records_nothing(self):
        code, out, err = run(["rvol", "--source", "massive", "--symbols", "UPP,DWN,AAA", "--date", "2026-10-19",
                              "--now", "2026-10-20 12:00", "--record-dir", self.rec, "--json"])
        self.assertEqual(code, 0, err)
        doc = json.loads(out)
        self.assertFalse(doc["live"])
        self.assertEqual(self.store.calls["snapshot"], 0)
        self.assertTrue(doc["stage1"]["basis"].startswith("replay"))
        self.assertIn("not recorded", err)
        self.assertIn("Stage 2: 5-minute bars for 3 names", err)      # the request count, before stage 2
        self.assertFalse(os.path.exists(os.path.join(self.rec, "triggers.jsonl")))
        self.store.daily[DAY] = dict((s, {"o": 1, "h": 1, "l": 1, "c": 1, "v": 1e6}) for s in self.store.bars)
        code, out, err = run(["rvol", "--source", "massive", "--symbols", "UPP,DWN,AAA", "--date", "2026-10-19",
                              "--now", "2026-10-20 12:00", "--shortlist", "2", "--no-record"])
        self.assertEqual(code, 0, err)
        self.assertIn("Stage 1 (replay, --shortlist 2)", out)
        self.assertIn("Stage 2: 5-minute bars for 2 names", err)

    def test_a_late_live_scan_records_nothing(self):
        code, out, err = run(["rvol", "--source", "massive", "--symbols", "UPP,DWN", "--now", "2026-10-19 09:46",
                              "--record-dir", self.rec])
        self.assertEqual(code, 0, err)
        self.assertIn("after 9:45 AM", err)
        self.assertFalse(os.path.exists(os.path.join(self.rec, "triggers.jsonl")))

    def test_the_record_rows_and_n_or(self):
        code, out, err = run(["rvol", "--source", "massive", "--symbols", "UPP,DWN", "--now", "2026-10-19 09:40",
                              "--record-dir", self.rec])
        self.assertEqual(code, 0, err)
        self.assertIn("record: recorded UPP 2026-10-19 09:35", err)
        with open(os.path.join(self.rec, "triggers.jsonl")) as fh:
            rows = [json.loads(x) for x in fh]
        self.assertEqual([r["symbol"] for r in rows], ["UPP"])          # the fire only, not the down bar
        t = rows[0]
        self.assertEqual((t["kind"], t["setup"], t["date"]), ("trigger", "rvol_orb5", "2026-10-19"))
        self.assertEqual((t["trigger"]["time"], t["trigger"]["bar_index"], t["trigger"]["price"]), ("09:35", 0, 30.6))
        self.assertEqual((t["trigger"]["or_high"], t["trigger"]["or_low"]), (31.0, 29.8))
        self.assertEqual(t["trigger"]["rvol"], 50.0)
        self.assertEqual(t["trigger"]["volume_x"], 15000.0 / 2e6)
        rule = t["rule"]
        self.assertEqual((rule["setup"], rule["or_minutes"], rule["stop_rule"], rule["stop_param"], rule["target_r"],
                          rule["exit"], rule["flat_by"]), ("rvol_orb5", 5, "datr", 0.1, None, "close", "15:55"))
        self.assertEqual(int(rule["or_minutes"]) // 5, 1)                 # record.py's n_or
        p = t["plan"]
        self.assertEqual((p["entry"], p["target"], p["exit"], p["entry_bar"]), (30.6, None, "close", 0))
        self.assertIn("datr:0.10", t["plan"]["basis"])
        # the datr stop: a tenth of the mean of 14 true ranges from 15 daily rows before the day, floored to the cent
        rows15 = self.daily_rows(None, None, "UPP", CAL.sessions_back(CAL.prev_session(DAY), 15)[0],
                                 CAL.prev_session(DAY))
        trs = [max(h - lo, abs(h - rows15[i][4]), abs(lo - rows15[i][4]))
               for i, (_, _o, h, lo, _c, _v) in enumerate(rows15[1:])]
        atr = sum(trs) / len(trs)
        self.assertAlmostEqual(p["stop"], math.floor(round((30.6 - 0.1 * atr) * 100, 6)) / 100.0)
        # a second scan appends nothing (one trigger per id)
        run(["rvol", "--source", "massive", "--symbols", "UPP,DWN", "--now", "2026-10-19 09:41", "--record-dir",
             self.rec])
        with open(os.path.join(self.rec, "triggers.jsonl")) as fh:
            self.assertEqual(len(fh.readlines()), 1)
        # scored after the close: the entry is bar 0 and the control's opening range is one bar (n_or 1)
        s = synth.make_session(DAY, 7, start=30.6)
        s[0].update(o=30.0, h=31.0, l=29.8, c=30.6)
        folder = os.path.join(self.d, "charts")
        os.makedirs(folder)
        with open(os.path.join(folder, "UPP.json"), "w") as fh:
            fh.write(synth.chart_text("UPP", [s]))
        got = record.score_day("2026-10-19", offline=folder, draws=1, now_utc=entry.parse_now("2026-10-19 16:30"),
                               record_dir=self.rec)
        self.assertEqual(got["pending"], 0)
        with open(os.path.join(self.rec, "scores.jsonl")) as fh:
            scores = [json.loads(x) for x in fh]
        with open(os.path.join(self.rec, "triggers.jsonl")) as fh:
            ctrl = [json.loads(x) for x in fh if '"control"' in x]
        self.assertEqual(scores[0]["entry_bar"], 0)
        self.assertEqual(scores[0]["last_bar"], 76)
        self.assertEqual(ctrl[0]["control"]["n_or"], 1)
        self.assertGreaterEqual(ctrl[0]["control"]["bar_index"], 1)

    def test_a_plan_trader_exit_refuses_is_recorded_without_one(self):
        def quiet(client, cal, symbol, start, end):       # a 0.001 daily range: a tenth of it is under 0.05%
            return [(t, 30.0, 30.0005, 29.9995, 30.0, 2e6) for (t, _o, _h, _l, _c, _v) in self.daily_rows(
                client, cal, symbol, start, end)]
        Y.fetch_daily_rows = quiet
        code, out, err = run(["rvol", "--source", "massive", "--symbols", "UPP,DWN", "--now", "2026-10-19 09:40",
                              "--record-dir", self.rec])
        self.assertEqual(code, 0, err)
        with open(os.path.join(self.rec, "triggers.jsonl")) as fh:
            rows = [json.loads(x) for x in fh]
        self.assertEqual([r["symbol"] for r in rows], ["UPP"])
        self.assertIsNone(rows[0]["plan"])
        self.assertIn("trader-exit refused the setup's own plan", rows[0]["plan_note"])
        self.assertIn("0.05%", rows[0]["plan_note"])

    def test_floors_come_from_the_config(self):
        with open("cfg.json", "w") as fh:
            json.dump({"floors": {"min_price": 7, "min_adv_usd": 30000000, "min_avg_volume": 1500000}}, fh)
        floors, src = scan.rvol_floors(scan.read_config("cfg.json"), R)
        self.assertEqual(floors, {"min_price": 7.0, "min_adv_usd": 3e7, "min_avg_volume": 1.5e6})
        self.assertEqual(src, {"min_price": "floors.min_price", "min_adv_usd": "floors.min_adv_usd",
                               "min_avg_volume": "floors.min_avg_volume"})
        floors, src = scan.rvol_floors({"universe": {"min_price": 6}}, R)
        self.assertEqual(floors, {"min_price": 6.0, "min_adv_usd": R.ADV_USD_MIN, "min_avg_volume": R.ADV_SH_MIN})
        self.assertEqual(src["min_price"], "universe.min_price")
        with open(os.path.join(os.path.dirname(os.path.abspath(scan.__file__)), "..", "trader-budget",
                               "config.example.json")) as fh:
            ex = json.load(fh)
        self.assertEqual(scan.rvol_floors(ex, R)[0], {"min_price": R.P_MIN, "min_adv_usd": R.ADV_USD_MIN,
                                                     "min_avg_volume": R.ADV_SH_MIN})


if __name__ == "__main__":
    unittest.main()
