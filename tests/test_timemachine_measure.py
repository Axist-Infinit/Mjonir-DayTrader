"""The time machine's measurement (chunk 2, steps 2.4 and 2.5): the SIM_* pin with costs off and the stop
filled at the stop, the reel net of costs, early closes used, incomplete sessions dropped, the year table,
fragile decisions, the one-tick flips, gap fills, the control and the baseline, data.source from the
document, the bars_5m path, and no-target plans."""

import datetime as dt
import gzip
import hashlib
import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

import _mj  # noqa: F401  (sys.path, throwaway data dirs)
import synth
from _load import FIX, load
from mjonir import bars as B
from mjonir import calendar as K
from mjonir import costs as C
from mjonir import stats as S
from mjonir import yahoo_shape as Y

tm = load("trader-timemachine", "timemachine")

TSLA = os.path.join(FIX, "trader-timemachine", "TSLA-60d5m.json.gz")
with gzip.open(TSLA, "rt", encoding="utf-8") as _fh:
    TEXT = _fh.read()
PLAN_PATH = os.path.join(FIX, "trader-budget", "plan-tsla.json")
with open(PLAN_PATH) as _fh:
    PLAN = json.load(_fh)
NOW = "2026-10-19 10:50"
# upstream's fingerprints of the reel's refs/sim-out.json (tests/test_timemachine.py)
SIM_BANDS = "b9b7c006a733c68b"
SIM_PATHS = "90f313ef40c576a0"
SIM_TRADES = "0058bef72b0dcdee"
SIM_HIST = {"lo": 351.75, "hi": 377.39,
            "bins": [107, 109, 128, 199, 252, 331, 465, 571, 689, 694, 757, 811, 761, 732, 686, 558, 503, 452,
                     327, 244, 160, 125, 102, 78]}
CARD = C.cost_card(364.18, 358.32, 370.04, 8, adv_usd=2.0e10, max_loss_usd=50.0)   # TSLA's 4 bp tier


def sha(x):
    return hashlib.sha256(json.dumps(x).encode("utf-8")).hexdigest()[:16]


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = tm.main(argv)
    return code, out.getvalue(), err.getvalue()


# ---------------------------------------------------------------- synthetic opening-range breakouts

def orb_session(day, outcome, early=False):
    """A session with a known outcome: OR 99..101 (mid 100), bar 4 closes 101.5 (entry; stop 100.00;
    1R target 103.00), then bar 5 decides: target, stop, gap (opens 99.0, through the stop), fragile
    (high 103.01: a 0.0067 R touch) or close (nothing hit)."""
    d = K.as_date(day)
    n = 42 if early else 78
    rows = [(100, 101, 99, 100), (100, 100.8, 99.2, 100.2), (100.2, 100.9, 99.5, 100.4),
            (100.4, 100.9, 100.2, 100.6), (100.6, 101.6, 100.5, 101.5)]
    fifth = {"target": (101.5, 103.3, 101.4, 103.1), "stop": (101.4, 101.5, 99.8, 99.9),
             "gap": (99.0, 99.2, 98.8, 99.0), "fragile": (101.5, 103.01, 101.4, 102.9),
             "close": (101.5, 101.9, 101.1, 101.6)}[outcome]
    rows.append(fifth)
    level = fifth[3]
    while len(rows) < n:
        rows.append((level, level + 0.05, level - 0.05, level))
    bars = []
    for i, (o, h, l, c) in enumerate(rows):
        t = K.ms_of(dt.datetime.combine(d, dt.time(9, 30), tzinfo=K.ET) + dt.timedelta(minutes=5 * i))
        bars.append({"t": t, "date": d.isoformat(), "slot": i, "o": o, "h": h, "l": l, "c": c, "v": 1000})
    return bars


def history(plan_day, outcomes, early_days=(), mjonir=None):
    """Chart text for sessions[i] with outcomes[i] (oldest first) ending the day before plan_day, plus the
    plan day itself (a target session)."""
    cal = K.Calendar()
    days = cal.sessions_back(plan_day, len(outcomes) + 1)
    sess = [orb_session(d, o, early=d.isoformat() in early_days) for d, o in zip(days[:-1], outcomes)]
    sess.append(orb_session(days[-1], "target"))
    return synth.chart_text("SYN", sess, mjonir=mjonir), days


def syn_plan(day, **kw):
    raw = {"symbol": "SYN", "side": "buy", "date": day, "setup": "orb", "entry": 101.5, "stop": 100.0,
           "target": 103.0, "entry_time": "9:55 AM", "opening_range": {"minutes": 15}, "stop_rule": "or_mid"}
    raw.update(kw)
    return tm.normalize_plan(raw)


def syn(day, outcomes, now=None, **kw):
    text, days = history(day, outcomes, kw.pop("early_days", ()), kw.pop("mjonir", None))
    plan = syn_plan(day, **kw.pop("plan", {}))
    return tm.time_machine(text, plan, tm.parse_now(now or (day + " 15:59")), **dict({"replays": 200}, **kw))


class SimPin(unittest.TestCase):
    def test_no_costs_gap_fill_stop_sessions_60_is_upstream_bit_for_bit(self):
        d = tempfile.mkdtemp()
        try:
            out = os.path.join(d, "tm.json")
            code, text, err = run(["run", "--plan", PLAN_PATH, "--offline", TSLA, "--now", NOW, "--no-costs",
                                   "--gap-fill", "stop", "--sessions", "60", "--write", out])
            self.assertEqual(code, 0, err)
            with open(out) as fh:
                doc = json.load(fh)
        finally:
            shutil.rmtree(d)
        m, h = doc["mc"], doc["history"]
        self.assertEqual(sha(m["bands"]), SIM_BANDS)
        self.assertEqual(sha(m["sample_paths"]), SIM_PATHS)
        self.assertEqual(m["hist"], SIM_HIST)
        slim = [{"date": t["date"], "entry": t["entry"], "outcome": t["outcome"], "R": t["R"]} for t in h["trades"]]
        self.assertEqual(sha(slim), SIM_TRADES)
        self.assertEqual((m["p_target"], m["p_stop"], m["avg_R"], h["avg_R"]), (0.2938, 0.2548, 0.034, -0.062))
        self.assertEqual(doc["costs"], {"on": False, "card": None, "model": None, "gap_fill": "stop",
                                        "control_draws": 3})


class TheReelNetOfCosts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = tm.time_machine(TEXT, tm.normalize_plan(PLAN), tm.parse_now(NOW), replays=2000, costs=CARD)

    def test_the_history_verdict_cannot_judge(self):
        v = self.doc["verdict_history"]
        self.assertEqual((v["state"], v["reason"], v["k"], v["n"]), ("unverified", "n_below_floor", 13, 28))
        self.assertEqual(v["text"], "Cannot judge: 13 of 28 decided fires hit the target (46.4%, 95% Wilson "
                                    "[29.5%, 64.2%]); n is below the 40-fire floor. Net break-even at 1R after "
                                    "costs is 56.5%.")
        self.assertNotIn("verdict", self.doc)
        for key in ("verdict_history", "verdict_control"):
            self.assertEqual(S.banned_words(self.doc[key]["text"]), [], key)

    def test_net_is_gross_minus_each_trades_cost_once(self):
        h = self.doc["history"]
        self.assertEqual((h["triggered"], h["target"], h["stop"], h["close"]), (33, 13, 15, 5))
        for t in h["trades"]:
            self.assertAlmostEqual(t["net_R"], round(t["R"], 2) - t["cost_r"], places=1)
            self.assertGreater(t["cost_r"], 0)
        self.assertAlmostEqual(h["net"]["mean"], h["gross"]["mean"] - h["cost_r_mean"], places=3)
        self.assertEqual((h["net"]["n"], h["gross"]["n"]), (33, 33))
        self.assertLess(h["net"]["lo"], h["net"]["mean"])
        self.assertEqual(round(h["gross"]["mean"], 3), -0.062)

    def test_fragile_and_one_tick(self):
        h = self.doc["history"]
        self.assertEqual(h["fragile"], len(h["fragile_dates"]))
        self.assertIn("2026-08-06", h["fragile_dates"])            # the chunk 1 vendor flip: a 2-cent touch
        sv = h["sensitivity"]
        self.assertEqual((sv["of"], sv["up"]["dates"], sv["down"]["flips"]), (33, ["2026-08-06"], 0))
        text = "\n".join(tm.report(self.doc))
        self.assertIn("One-tick sensitivity: the entry 1 cent higher flips 1 outcome, 1 cent lower flips 0 (of 33).",
                      text)
        self.assertIn("decided by under 0.05 R (fragile)", text)

    def test_no_average_without_its_interval_and_n(self):
        import re
        text = "\n".join(tm.report(self.doc))
        for line in text.splitlines():
            if re.search(r"[Aa]verage R ", line) and not line.strip().startswith("Average R:"):  # the MC block
                self.assertIn("95 % bootstrap interval", line, line)
                self.assertRegex(line, r"n \d+\)", line)

    def test_the_control_and_the_baseline(self):
        h = self.doc["history"]
        c = h["control"]
        self.assertEqual((c["draws"], c["trades"] + sum(c["skipped"].values())), (3, 3 * 33))
        self.assertEqual(c["delta"]["n_sessions"], c["sessions"])
        self.assertEqual(self.doc["verdict_control"]["n_decided"], 28)
        self.assertIn(self.doc["verdict_control"]["state"], ("pass", "fail", "unverified"))
        b = h["baseline"]
        self.assertEqual(b["sessions"], 59)
        self.assertEqual(b["trades"] + b["skipped"], 59)
        self.assertIn("never a verdict", b["note"])
        text = "\n".join(tm.report(self.doc))
        self.assertIn("Baseline, buy any morning strength", text)
        self.assertIn("a diagnostic, not a verdict", text)

    def test_the_data_source_is_the_documents_own(self):
        d = self.doc["data"]
        self.assertEqual((d["source"], d["adjustment"]["adjusted"]), ("yahoo", None))
        self.assertEqual((d["early_close_used"], d["incomplete_dropped"]), ([], []))
        self.assertEqual(self.doc["source"], "yahoo")

    def test_the_mc_is_a_shape_line(self):
        self.assertTrue(self.doc["mc_shape"].startswith(tm.SHAPE))
        self.assertIn("avg_R_net", self.doc["mc"])
        self.assertAlmostEqual(self.doc["mc"]["avg_R_net"], self.doc["mc"]["avg_R"] - CARD["cost_r"], places=3)


class Synthetic(unittest.TestCase):
    OUT = ["target", "stop", "close", "target", "stop"] * 5        # 25 sessions

    def test_outcomes_and_net(self):
        doc = syn("2026-10-19", self.OUT, costs=None, gap_fill="stop")
        h = doc["history"]
        self.assertEqual((h["triggered"], h["target"], h["stop"], h["close"]), (25, 10, 10, 5))
        self.assertEqual(h["trades"][0]["R"], 1.0)
        self.assertEqual(h["trades"][1]["R"], -1.0)
        self.assertEqual(h["trades"][0]["entry"], 101.5)
        self.assertEqual((h["fragile"], h["sensitivity"]["flips"]), (0, 0))
        self.assertEqual(doc["verdict_history"]["reason"], "n_below_floor")

    def test_a_gap_through_the_stop(self):
        out = ["gap"] + self.OUT[1:]
        opened = syn("2026-10-19", out, costs=None)["history"]["trades"][0]
        self.assertEqual((opened["outcome"], opened["gap"]), ("stop", True))
        self.assertEqual(opened["R"], round((99.0 - 101.5) / 1.5, 2))
        at_stop = syn("2026-10-19", out, costs=None, gap_fill="stop")["history"]["trades"][0]
        self.assertEqual((at_stop["R"], at_stop["gap"]), (-1.0, False))

    def test_fragile_and_the_flip(self):
        doc = syn("2026-10-19", ["fragile"] + self.OUT[1:], costs=None)
        h = doc["history"]
        first = h["trades"][0]
        self.assertEqual((first["outcome"], first["fragile"]), ("target", True))
        self.assertAlmostEqual(first["margin_r"], 0.01 / 1.5, places=4)
        self.assertEqual(h["fragile"], 1)
        self.assertEqual(h["sensitivity"]["up"]["dates"], [first["date"]])     # 1 cent higher: the target moves 2
        self.assertEqual(h["sensitivity"]["down"]["flips"], 0)

    def test_costs_on_by_default_with_adv_unverified(self):
        doc = syn("2026-10-19", self.OUT)
        card = doc["costs"]["card"]
        self.assertTrue(doc["costs"]["on"])
        self.assertEqual((card["slippage_bps"], card["flags"][0]), (15.0, "adv_unverified"))
        self.assertEqual(doc["costs"]["gap_fill"], "open")
        h = doc["history"]
        self.assertLess(h["net"]["mean"], h["gross"]["mean"])
        self.assertIn("after costs", doc["verdict_history"]["text"])

    def test_early_close_sessions_are_used_and_scored_to_the_1_pm_close(self):
        # 2026-11-27 (an NYSE 1:00 PM close) inside the history of a 2026-12-04 plan
        out = ["close"] * 25
        doc = syn("2026-12-04", out, early_days=("2026-11-27",), costs=None)
        d = doc["data"]
        self.assertEqual(d["early_close_used"], [{"date": "2026-11-27", "bars": 42, "last_bar": 41}])
        self.assertEqual(d["incomplete_dropped"], [])
        self.assertEqual(doc["mc"]["pool_sessions"], 24)              # the pool keeps 78-bar sessions only
        self.assertEqual(doc["history"]["sessions"], 25)
        t = [x for x in doc["history"]["trades"] if x["date"] == "2026-11-27"][0]
        self.assertEqual((t["last_bar"], t["early_close"]), (41, True))
        self.assertEqual(doc["history"]["early_close_trades"], 1)
        flat = syn("2026-12-04", out, early_days=("2026-11-27",), costs=None, until="15:55")
        self.assertEqual(flat["data"]["early_close_used"][0]["last_bar"], 40)    # 15:55 -> 12:55
        self.assertIn("Used 1 early-close session", "\n".join(tm.report(doc)))

    def test_a_short_day_off_the_calendar_is_dropped(self):
        short_day = "2026-09-25"                                        # a Friday with 42 bars, not on the calendar
        text, _ = history("2026-10-19", self.OUT, early_days=(short_day,))
        doc = tm.time_machine(text, syn_plan("2026-10-19"), tm.parse_now("2026-10-19 15:59"), replays=100,
                              costs=None)
        self.assertEqual(doc["data"]["incomplete_dropped"], [{"date": short_day, "bars": 42}])
        self.assertEqual(doc["data"]["early_close_used"], [])

    def test_the_year_table_and_its_sign_flip_note(self):
        days = K.Calendar().sessions_back("2026-01-30", 26)[:-1]
        out = ["target" if d.year == 2025 else "stop" for d in days]
        doc = syn("2026-01-30", out, costs=None)
        y = doc["history"]["by_year"]
        self.assertEqual(sorted(y), ["2025", "2026"])
        self.assertGreater(y["2025"]["net"]["mean"], 0)
        self.assertLess(y["2026"]["net"]["mean"], 0)
        self.assertEqual(y["2025"]["n"] + y["2026"]["n"], 25)
        self.assertTrue(doc["history"]["by_year_note"].startswith("the sign of the net average flips between years"))
        self.assertIn("By year, net R a trade: 2025 +", "\n".join(tm.report(doc)))

    def test_the_control_forced_to_the_rules_bar_is_delta_zero(self):
        text, _ = history("2026-10-19", self.OUT)
        plan = syn_plan("2026-10-19")
        bars = tm.parse_bars(tm.chart_result(text, "SYN"), tm.parse_now("2026-10-19 15:59"))[1]
        full, early, short = tm.classify_sessions(tm.split_sessions(bars), "2026-10-19")
        rule = tm.resolve_rule(plan, tm.split_sessions(bars)["2026-10-19"])
        model = C.model_of(C.cost_card(101.5, 100.0, 103.0, 10, adv_usd=5e7))
        h = tm.history_replay(full, rule, 77, "buy", model, "open", 1, "SYN", 19, control_bar="rule")
        self.assertEqual((h["control"]["delta"]["delta"], h["control"]["delta"]["lo"],
                          h["control"]["delta"]["hi"]), (0.0, 0.0, 0.0))
        r = tm.history_replay(full, rule, 77, "buy", model, "open", 3, "SYN", 19)
        self.assertEqual(r["control"]["trades"], 75)
        again = tm.history_replay(full, rule, 77, "buy", model, "open", 3, "SYN", 19)
        self.assertEqual(r["control"], again["control"])            # seeded

    def test_no_target_plan_reads_the_net_expectancy(self):
        doc = syn("2026-10-19", self.OUT, costs=None, plan={"target": None, "exit": "close"})
        self.assertIsNone(doc["plan"].get("target"))
        self.assertEqual(doc["mc"]["p_target"], 0.0)
        self.assertIn("no target", doc["mc_shape"])
        self.assertEqual(doc["history"]["target"], 0)
        v = doc["verdict_history"]
        self.assertEqual((v["state"], v["reason"], v["basis"]), ("unverified", "n_below_floor", "net expectancy vs 0"))
        text = "\n".join(tm.report(doc))
        self.assertIn("no target, out by 4:00 PM", text)
        with self.assertRaises(tm.TMError):
            syn_plan("2026-10-19", exit="close")                      # a target given with exit close
        with self.assertRaises(tm.TMError):
            syn_plan("2026-10-19", target=None)                        # no target without exit close


class BarsPath(unittest.TestCase):
    """--source massive: history through bars.bars_5m (one store), data.source and the basis from info."""

    def setUp(self):
        self.saved = B.bars_5m

    def tearDown(self):
        B.bars_5m = self.saved

    def test_fetch_history_bars_stamps_the_store(self):
        cal = K.Calendar()
        days = cal.sessions_back("2026-10-19", 26)
        sess = [orb_session(d, o) for d, o in zip(days, ["target", "stop", "close"] * 9)]
        B.bars_5m = synth.make_store(sess, source="kalex", as_of="2026-07-15")
        doc = Y.fetch_history_bars(None, cal, "SYN", days[0], days[-1])
        mj = doc["chart"]["result"][0]["meta"]["mjonir"]
        self.assertEqual((mj["source"], mj["store"], mj["adjusted"], mj["as_of"]), ("kalex", "kalex", True,
                                                                                     "2026-07-15"))
        out = tm.time_machine(Y.to_text(doc), syn_plan("2026-10-19"), tm.parse_now("2026-10-19 15:59"), replays=100,
                              costs=None, source="massive")
        self.assertEqual((out["source"], out["data"]["source"]), ("kalex", "kalex"))
        self.assertEqual(out["data"]["adjustment"]["basis"], "adjusted as of 2026-07-15")
        B.bars_5m = synth.make_store(sess, source="api", as_of="2026-11-02")
        out = tm.time_machine(Y.to_text(Y.fetch_history_bars(None, cal, "SYN", days[0], days[-1])),
                              syn_plan("2026-10-19"), tm.parse_now("2026-10-19 15:59"), replays=100, costs=None,
                              source="massive")
        self.assertEqual((out["source"], out["data"]["source"]), ("massive", "api"))   # never the --source flag


if __name__ == "__main__":
    unittest.main()
