"""Chunk 3.2: risk in percent of the trade notional (mjonir/limits.py, trader-budget/size.py, trader-risk/check.py).
The derivation and the stricter of two, the sizing formula, each new check in its three states, the streak pause
cleared by the calendar, the realized daily and weekly loss read from the forward record, risk.json's basis.
No network."""

import ast
import contextlib
import hashlib
import io
import json
import math
import os
import random
import shutil
import tempfile
import unittest

import _mj  # noqa: F401  (sys.path, throwaway data dirs, no key)
from _load import FIX, ROOT, load
from mjonir import costs as C
from mjonir import ledger as L
from mjonir import limits as LM

size = load("trader-budget", "size")
check = load("trader-risk", "check")
ticket = load("trader-broker", "ticket")

EXAMPLE = os.path.join(ROOT, "trader-budget", "config.example.json")
PLAN = os.path.join(FIX, "trader-budget", "plan-tsla.json")
ADV = 12729948354                         # the stored Massive ADV of TSLA before 2026-10-19 (chunk 2 acceptance)
NOW = "2026-10-19 10:16"


def example(**over):
    with open(EXAMPLE) as fh:
        c = json.load(fh)
    c.update(over)
    return c


def plan_2r(**over):
    """The reel's 2R plan with its cost card (4 bp tier, 3 bp default half spread, $1 a side)."""
    with open(PLAN) as fh:
        p = json.load(fh)
    p.update(target=375.90, target_r=2.0, reward_risk=2.0, target_label="2R (two times the risk)")
    p["costs"] = C.cost_card(364.18, 358.32, 375.90, 8, adv_usd=ADV, max_loss_usd=50.0)
    p.update(over)
    return p


def run(mod, argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = mod.main(argv)
    return code, out.getvalue(), err.getvalue()


class Derive(unittest.TestCase):
    def test_the_example(self):
        lim = LM.derive_limits(example())
        self.assertEqual(lim["mode"], "notional")
        for k, v in (("trade_notional_usd", 100000.0), ("max_loss_usd", 1000.0), ("daily_loss_usd", 1000.0),
                     ("weekly_loss_usd", 2000.0), ("max_trades_per_day", 3), ("max_consecutive_losses", 3),
                     ("pause_sessions_after_streak", 1), ("max_order_usd", 100000.0), ("position_cap_usd", 100000.0)):
            self.assertEqual(lim[k], v, k)
        self.assertEqual(lim["warnings"], [])
        self.assertEqual(lim["floors"], {"min_price": 5.0, "min_adv_usd": 2e7, "max_chase_pct": 0.5,
                                         "no_averaging_down": True})

    def test_the_example_has_no_equity_figure_and_keeps_upstreams_keys(self):
        c = example()
        for k in ("budget", "cash_buffer_pct", "max_position_pct", "max_order_usd"):
            self.assertNotIn(k, c)
        for k in ("max_loss_per_trade_usd", "max_daily_loss_usd", "max_trades_per_day"):
            self.assertIn(k, c)
            self.assertIsNone(c[k])
        self.assertEqual((c["min_reward_risk_basis"], c["allow_no_target"], c["block_on_unverified"], c["pdt_guard"]),
                         ("net", True, True, False))
        self.assertEqual(c["costs"], C.DEFAULTS)

    def test_the_stricter_of_two_with_a_warning_naming_both(self):
        lim = LM.derive_limits(example(max_loss_per_trade_usd=50, max_daily_loss_usd=5000, max_trades_per_day=2,
                                       max_order_usd=4000, budget=5000, max_position_pct=75))
        self.assertEqual((lim["max_loss_usd"], lim["daily_loss_usd"], lim["max_trades_per_day"], lim["max_order_usd"],
                          lim["position_cap_usd"]), (50.0, 1000.0, 2, 4000.0, 3750.0))
        w = "\n".join(lim["warnings"])
        self.assertIn("max_loss_per_trade_usd $50 and sizing.max_loss_pct_of_notional 1% of the $100,000 trade "
                      "notional = $1,000 are both set: the stricter, $50, applies", w)
        self.assertIn("max_daily_loss_usd $5,000 and limits_pct.daily_loss 1% of $100,000 = $1,000 are both set: the "
                      "stricter, $1,000, applies", w)
        self.assertIn("max_trades_per_day 2 and limits_pct.max_trades_per_day 3", w)
        self.assertIn("budget $5,000", w)
        self.assertEqual(len(lim["warnings"]), 5)
        self.assertEqual(lim["from"]["max_loss_usd"], "max_loss_per_trade_usd")

    def test_percent_arithmetic(self):
        lim = LM.derive_limits(example(sizing={"trade_notional_usd": 25000, "max_loss_pct_of_notional": 0.5},
                                       limits_pct={"daily_loss": 1.5, "weekly_loss": 3}))
        self.assertEqual((lim["max_loss_usd"], lim["daily_loss_usd"], lim["weekly_loss_usd"]), (125.0, 375.0, 750.0))
        self.assertEqual(lim["max_trades_per_day"], LM.LIMITS_PCT_DEFAULTS["max_trades_per_day"])   # absent key

    def test_legacy_and_bad_configs(self):
        lim = LM.derive_limits({"budget": 5000, "max_loss_per_trade_usd": 50})
        self.assertEqual((lim["mode"], lim["max_loss_usd"], lim["daily_loss_usd"]), ("legacy", 50.0, None))
        for bad, key in (({"limits_pct": {"daily_loss": 1}}, "add the sizing block"),
                         ({"sizing": {"trade_notional_usd": 0, "max_loss_pct_of_notional": 1}}, "trade_notional_usd"),
                         ({"sizing": {"trade_notional_usd": 1e5, "max_loss_pct_of_notional": 101}},
                          "max_loss_pct_of_notional"),
                         ({"sizing": {"trade_notional_usd": 1e5, "max_loss_pct_of_notional": 1},
                           "limits_pct": {"max_consecutive_losses": 2.5}}, "max_consecutive_losses"),
                         ({"floors": {"no_averaging_down": "yes"}}, "no_averaging_down"),
                         ({"sizing": {"trade_notional_usd": "lots", "max_loss_pct_of_notional": 1}}, "trade_notional")):
            with self.assertRaises(LM.LimitsError) as cm:
                LM.derive_limits(bad)
            self.assertIn(key, str(cm.exception))

    def test_python_3_8(self):
        for name in ("limits.py", "ledger.py"):
            with open(os.path.join(ROOT, "mjonir", name), encoding="utf-8") as fh:
                ast.parse(fh.read(), feature_version=(3, 8))


class Sizing(unittest.TestCase):
    def test_the_reel_on_100k(self):
        s = size.size_trade(plan_2r(), example(), today="2026-10-19")
        slip = 2 * 364.18 * 7.0 / 1e4
        want = int(math.floor(min(100000 / 364.18, (1000 - 2.0) / (5.86 + slip))))
        self.assertEqual((s["qty"], want), (156, 156))
        self.assertEqual(s["bound_by"], "max loss")
        z = s["sizing"]
        self.assertEqual((z["notional_usd"], z["notional_pct"], z["risk_usd"], z["risk_pct"], z["max_loss_usd"],
                          z["max_loss_pct"], z["cap_usd"]), (56812.08, 56.81, 914.16, 0.914, 995.7, 0.996, 1000.0))
        self.assertIsNone(s["refusal"])
        self.assertEqual(s["reward_risk_net"], 1.75)
        o = size.bracket_order(s)
        self.assertEqual((o["qty"], o["order_class"]), ("156", "bracket"))
        self.assertIn("bound by your $1,000 max loss per trade", o["why"])
        self.assertEqual(o["plan"]["costs"]["adv_usd"], ADV)

    def test_the_report_prints_the_percent_lines(self):
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, "plan.json")
            with open(p, "w") as fh:
                json.dump(plan_2r(), fh)
            code, out, err = run(size, ["--plan", p, "--config", EXAMPLE, "--portfolio", os.path.join(d, "none"),
                                        "--now", NOW])
            self.assertEqual(code, 0, err)
            code, out2, _ = run(size, ["--plan", p, "--config", EXAMPLE, "--portfolio", os.path.join(d, "none"),
                                       "--now", NOW, "--budget", "5000"])
            self.assertIn("--budget is not used: this config sizes by sizing.trade_notional_usd", out2)
            self.assertIn("Size: 156 shares", out2)
            for line in ("Size: 156 shares of TSLA = $56,812.08 at 364.18, 56.81% of the $100,000 trade notional.",
                         "Risk $914.16 at the stop before costs (0.914% of the notional); max loss net of costs "
                         "$995.70 (0.996% of the notional; the cap is $1,000, 1.000%).",
                         "Net max loss: 156 x (5.86 + 0.5099) + $2 = $995.70.",
                         "the $100,000 trade notional / 364.18"):
                self.assertIn(line, out)
        finally:
            shutil.rmtree(d)

    def test_the_notional_binds_on_a_tight_stop(self):
        p = plan_2r(entry=50.0, stop=49.95, target=50.10, risk_per_share=0.05)
        p["costs"] = C.cost_card(50.0, 49.95, 50.10, 8, adv_usd=ADV, max_loss_usd=50.0)
        s = size.size_trade(p, example(min_reward_risk=0), today="2026-10-19")
        self.assertEqual((s["qty"], s["bound_by"]), (2000, "notional"))
        self.assertIn("$100,000 trade notional", size.bracket_order(s)["why"])

    def test_a_legacy_dollar_cap_is_stricter(self):
        s = size.size_trade(plan_2r(), example(max_loss_per_trade_usd=50), today="2026-10-19")
        self.assertEqual(s["qty"], 7)          # chunk 2's net sizing at $50
        self.assertIn("the stricter, $50, applies", s["limits_basis"]["warnings"][0])
        self.assertIn("Note: max_loss_per_trade_usd $50", size.plan_report(s, size.bracket_order(s)))

    def test_refusals_keep_their_words(self):
        s = size.size_trade(plan_2r(entry=3000.0, stop=1500.0, target=6000.0, risk_per_share=1500.0), example(),
                            today="2026-10-19")
        self.assertEqual(s["qty"], 0)
        self.assertIn("more than your $1,000 max loss", s["refusal"])
        s = size.size_trade(plan_2r(target=370.04, target_r=1.0), example(), today="2026-10-19")
        self.assertIn("net reward:risk", s["refusal"])
        self.assertIn("under your minimum 1", s["refusal"])

    def test_the_formula_on_random_plans(self):
        rng = random.Random(7)
        for _ in range(300):
            e = round(rng.uniform(6, 900), 2)
            r = round(e * rng.uniform(0.0006, 0.03), 2)
            bps = rng.choice([4.0, 7.0, 11.0, 18.0])
            com = rng.choice([0.0, 1.0, 4.95])
            card = {"per_side_bps": bps, "commission_usd": com, "off": False, "adv_usd": None}
            p = plan_2r(entry=e, stop=round(e - r, 2), target=round(e + 3 * r, 2), risk_per_share=r, costs=card)
            cfg = example(min_reward_risk=0)
            s = size.size_trade(p, cfg, today="2026-10-19")
            slip = 2 * e * bps / 1e4
            risk = round(e - round(e - r, 2), 2)
            want = int(math.floor(min(round(100000 / e, 9), (1000 - 2 * com) / (risk + slip) + 1e-9)))
            self.assertIn(s["qty"], (want, want - 1), (e, r, bps, com))
            if s["qty"]:
                self.assertLessEqual(s["max_loss"], 1000.005, (e, r, bps, com))
                self.assertLessEqual(s["cost"], 100000.0)
            if s["qty"] < want:     # one less only when the net max loss at `want` is over the cap
                self.assertGreater(round(want * (risk + slip) + 2 * com, 2), 1000.005)


def rec_trade(rec, date, net_r, qty=100, risk=5.0, time="10:00", scored=True, max_loss=None, taken=True):
    tp, sp = L.paths(rec)
    tid = hashlib.sha256(("%s%s%s%s" % (date, time, net_r, qty)).encode()).hexdigest()[:16]
    L.append_rows(tp, [{"id": tid, "kind": "trigger", "date": date, "symbol": "X", "setup": "orb",
                        "trigger": {"time": time}, "plan": {"risk_per_share": risk},
                        "decision": {"taken": taken, "qty": qty, "max_loss_usd": max_loss},
                        "recorded_at": date + "T14:00:00Z"}])
    if scored:
        L.append_rows(sp, [{"id": tid, "kind": "trigger", "outcome": "stop" if net_r < 0 else "target",
                            "net_r": net_r, "scored_at": date + "T21:00:00Z"}])
    return tid


class Checks(unittest.TestCase):
    """Each new check in its three states, on the reel's 156-share order under the example config."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.rec = os.path.join(self.d, "record")
        os.makedirs(self.rec)
        open(L.paths(self.rec)[0], "a").close()          # an empty, existing record
        self.order = size.bracket_order(size.size_trade(plan_2r(), example(), today="2026-10-19"))

    def tearDown(self):
        shutil.rmtree(self.d)

    def run_check(self, now=NOW, cfg=None, prices=None, portfolio=None, order=None, rec="default", **kw):
        n = check.parse_now(now)
        times = None if prices is None else {k: n for k in prices}
        return check.check([order or self.order], cfg or example(), portfolio, prices or {}, None, None, n, times,
                           record_dir=self.rec if rec == "default" else rec, **kw)

    def states(self, res):
        return {c["name"]: c["state"] for c in res["results"][0]["checks"]}

    def reason(self, res, name):
        return [c["reason"] for c in res["results"][0]["checks"] if c["name"] == name][0]

    def test_every_check_is_there_with_three_outcomes_only(self):
        res = self.run_check(prices={"TSLA": 364.18})
        st = self.states(res)
        for name in ("price_floor", "adv_floor", "chase", "averaging_down", "daily_loss", "weekly_loss", "loss_streak",
                     "spread", "format", "loss", "reward_risk", "window", "trades", "duplicate"):
            self.assertIn(name, st)
        self.assertTrue(set(st.values()) <= {"pass", "block", "unverified"})
        self.assertEqual({k: v for k, v in st.items() if v != "pass"}, {"spread": "unverified"})
        self.assertEqual(res["results"][0]["verdict"], "BLOCK")       # block_on_unverified: the spread
        self.assertEqual(self.run_check(prices={"TSLA": 364.18},
                                        cfg=example(block_on_unverified=False))["results"][0]["verdict"], "PASS")

    def test_price_floor(self):
        self.assertEqual(self.states(self.run_check())["price_floor"], "pass")
        cheap = dict(self.order, plan=dict(self.order["plan"], entry=4.0, stop=3.9, target=4.2),
                     stop_loss_stop_price="3.90", take_profit_limit_price="4.20", qty="10")
        res = self.run_check(order=cheap, cfg=example(block_on_unverified=False))
        self.assertEqual(self.states(res)["price_floor"], "block")
        self.assertIn("price floor: TSLA at 4.00 is under the $5 price floor", "\n".join(res["results"][0]["reasons"]))
        bare = {"symbol": "TSLA", "side": "buy", "qty": "5", "type": "market", "time_in_force": "day",
                "stop_loss_stop_price": "358.32", "take_profit_limit_price": "375.90", "order_class": "bracket"}
        self.assertEqual(self.states(self.run_check(order=bare))["price_floor"], "unverified")

    def test_adv_floor(self):
        self.assertEqual(self.states(self.run_check())["adv_floor"], "pass")
        thin = dict(self.order, plan=dict(self.order["plan"], costs=dict(self.order["plan"]["costs"], adv_usd=5e6)))
        self.assertEqual(self.states(self.run_check(order=thin))["adv_floor"], "block")
        none = dict(self.order, plan=dict(self.order["plan"], costs=None))
        self.assertEqual(self.states(self.run_check(order=none))["adv_floor"], "unverified")
        self.assertIn("the plan carries no cost card; --source massive asks Massive",
                      self.reason(self.run_check(order=none), "adv_floor"))
        noadv = dict(self.order, plan=dict(self.order["plan"], costs=dict(self.order["plan"]["costs"], adv_usd=None)))
        self.assertIn("(the plan's cost card has none; --source massive asks Massive)",
                      self.reason(self.run_check(order=noadv), "adv_floor"))
        self.assertEqual(self.states(self.run_check(order=none, adv_fn=lambda s: 3e8))["adv_floor"], "pass")

        def broken(sym):
            raise check.RiskError("no key")
        res = self.run_check(order=none, adv_fn=broken)
        self.assertEqual(self.states(res)["adv_floor"], "unverified")
        self.assertIn("Massive could not answer: no key", self.reason(res, "adv_floor"))

    def test_chase(self):
        self.assertEqual(self.states(self.run_check(prices={"TSLA": 365.90}))["chase"], "pass")
        res = self.run_check(prices={"TSLA": 366.20})
        self.assertEqual(self.states(res)["chase"], "block")
        self.assertIn("is 0.55% over the trigger 364.18, past the 0.5% chase limit (366.00)", self.reason(res, "chase"))
        self.assertEqual(self.states(self.run_check())["chase"], "unverified")
        lim = dict(self.order, type="limit", limit_price="366.50")
        self.assertEqual(self.states(self.run_check(order=lim))["chase"], "block")
        ms = check.parse_now(NOW)
        t_ms = int((ms - check.datetime.datetime(1970, 1, 1)).total_seconds() * 1000)
        quote = {"bid": 364.30, "ask": 364.40, "t_ms": t_ms}
        res = self.run_check(quote_fn=lambda s: quote)
        self.assertEqual(self.states(res)["chase"], "pass")
        self.assertIn("the live ask", self.reason(res, "chase"))

    def test_averaging_down(self):
        self.assertEqual(self.states(self.run_check())["averaging_down"], "pass")
        pf = {"cash": 50000, "positions": [{"ticker": "TSLA", "shares": 10,
                                            "lots": [{"date": "2026-10-16", "shares": 10, "cost": 3800.0}]}]}
        res = self.run_check(portfolio=pf, prices={"TSLA": 364.50})
        self.assertEqual(self.states(res)["averaging_down"], "block")
        self.assertIn("held at 380.00 a share and trades at 364.50", self.reason(res, "averaging_down"))
        pf_up = {"cash": 50000, "positions": [{"ticker": "TSLA", "shares": 10,
                                               "lots": [{"date": "2026-10-16", "shares": 10, "cost": 3500.0}]}]}
        self.assertEqual(self.states(self.run_check(portfolio=pf_up, prices={"TSLA": 364.50}))["averaging_down"], "pass")
        pf_nolots = {"cash": 50000, "positions": [{"ticker": "TSLA", "shares": 10}]}
        self.assertEqual(self.states(self.run_check(portfolio=pf_nolots))["averaging_down"], "unverified")

    def test_daily_loss_is_realized_from_the_record(self):
        self.assertEqual(self.states(self.run_check())["daily_loss"], "pass")
        rec_trade(self.rec, "2026-10-19", -1.0, qty=1, risk=3.0, time="09:50")             # -$3 realized
        rec_trade(self.rec, "2026-10-19", -9.0, taken=False, time="09:40")                  # skipped: not counted
        res = self.run_check()
        self.assertEqual(self.states(res)["daily_loss"], "pass")      # 3 + 995.70 <= 1000
        self.assertIn("realized -$3 net over 1 scored trade(s) since 2026-10-19", self.reason(res, "daily_loss"))
        rec_trade(self.rec, "2026-10-19", 0.0, scored=False, max_loss=4.0, time="09:55")    # planned, open
        res = self.run_check()
        self.assertIn("$4 planned on 1 open trade(s)", self.reason(res, "daily_loss"))
        self.assertEqual(self.states(res)["daily_loss"], "block")     # 3 + 4 + 995.70 > 1000
        self.assertIn("daily loss: realized -$3", "\n".join(res["results"][0]["reasons"]))
        rec_trade(self.rec, "2026-10-19", 3.0, qty=1, risk=5.0, time="10:30")              # +$15: nets the loss
        self.assertEqual(self.states(self.run_check())["daily_loss"], "pass")        # max(0, -12) + 4 + 995.70

    def test_daily_loss_unverified_without_a_record(self):
        res = self.run_check(rec=os.path.join(self.d, "nowhere"))
        st = self.states(res)
        self.assertEqual((st["daily_loss"], st["weekly_loss"], st["loss_streak"]), ("unverified",) * 3)
        self.assertIn("no record at", self.reason(res, "daily_loss"))
        with open(L.paths(self.rec)[0], "a") as fh:
            fh.write("{broken\n")
        res = self.run_check()
        self.assertEqual(self.states(res)["daily_loss"], "unverified")
        self.assertIn("unreadable", self.reason(res, "daily_loss"))
        self.assertIn("line 1", res["basis"]["record_error"])
        rec2 = os.path.join(self.d, "r2")
        rec_trade(rec2, "2026-10-19", -1.0, qty=None, time="09:50")
        self.assertEqual(self.states(self.run_check(rec=rec2))["daily_loss"], "unverified")

    def test_weekly_loss_from_monday(self):
        rec_trade(self.rec, "2026-10-16", -2.0, qty=100, risk=5.0)       # last week: not counted
        rec_trade(self.rec, "2026-10-19", -1.6, qty=100, risk=5.0)       # -$800 Monday
        rec_trade(self.rec, "2026-10-20", -0.6, qty=100, risk=5.0)       # -$300 Tuesday
        res = self.run_check(now="2026-10-21 10:16")
        st = self.states(res)
        self.assertEqual((st["daily_loss"], st["weekly_loss"]), ("pass", "block"))
        self.assertIn("realized -$1,100 net over 2 scored trade(s) since 2026-10-19", self.reason(res, "weekly_loss"))
        self.assertEqual(self.states(self.run_check(now="2026-10-26 10:16"))["weekly_loss"], "pass")

    def test_the_streak_pause_clears_after_one_session(self):
        for i, day in enumerate(("2026-10-14", "2026-10-15", "2026-10-16")):
            rec_trade(self.rec, day, -0.2, qty=1, risk=1.0)
        st = lambda now: self.states(self.run_check(now=now))["loss_streak"]     # noqa: E731
        self.assertEqual(st("2026-10-16 10:16"), "block")       # the day of the third loss
        self.assertEqual(st("2026-10-19 10:16"), "block")       # the next session (a weekend between)
        self.assertEqual(st("2026-10-20 10:16"), "pass")        # one session has passed: cleared
        self.assertIn("paused for 1 session(s) after it (1 passed)",
                      self.reason(self.run_check(now="2026-10-19 10:16"), "loss_streak"))
        rec_trade(self.rec, "2026-10-20", 0.5, qty=1, risk=1.0)
        self.assertEqual(st("2026-10-21 10:16"), "pass")

    def test_the_pause_counts_sessions_by_the_calendar(self):
        for day in ("2026-11-23", "2026-11-24", "2026-11-25"):
            rec_trade(self.rec, day, -0.2, qty=1, risk=1.0)
        # Thanksgiving (Thu 2026-11-26) is not a session: Friday is the first one after the streak
        self.assertEqual(self.states(self.run_check(now="2026-11-27 10:16"))["loss_streak"], "block")
        self.assertEqual(self.states(self.run_check(now="2026-11-30 10:16"))["loss_streak"], "pass")

    def test_legacy_configs_do_not_run_the_percent_checks(self):
        with open(os.path.join(FIX, "trader-budget", "config-upstream.json")) as fh:
            up = json.load(fh)
        res = check.check([self.order], up, None, {}, None, None, check.parse_now(NOW), None, record_dir=self.rec)
        names = [c["name"] for c in res["results"][0]["checks"]]
        self.assertEqual(names, ["spread"])
        self.assertIsNone(res["basis"]["trade_notional_usd"])
        self.assertEqual(res["basis"]["limits"]["mode"], "legacy")

    def test_risk_json_keeps_the_fingerprint_and_adds_the_basis(self):
        orders = os.path.join(self.d, "orders.json")
        with open(orders, "w") as fh:
            json.dump({"orders": [self.order]}, fh)
        rec_trade(self.rec, "2026-10-16", 0.4, qty=1, risk=1.0)
        out = os.path.join(self.d, "risk.json")
        code, text, err = run(check, ["--orders", orders, "--config", EXAMPLE, "--portfolio", os.path.join(self.d, "n"),
                                      "--prices", os.path.join(self.d, "n"), "--state", os.path.join(self.d, "n"),
                                      "--now", NOW, "--out", out, "--record-dir", self.rec])
        self.assertEqual(code, 1, err)        # the spread and the chase are unverified: blocked by the example
        self.assertIn("every check:", text)
        with open(out) as fh:
            doc = json.load(fh)
        self.assertEqual(doc["results"][0]["fingerprint"], check.fingerprint(self.order))
        self.assertEqual(doc["basis"]["trade_notional_usd"], 100000.0)
        self.assertEqual(doc["basis"]["limits"]["max_loss_usd"], 1000.0)
        self.assertIsNotNone(doc["basis"]["record_as_of"])
        self.assertEqual(doc["basis"]["record_dir"], self.rec)

    def test_the_loss_cap_is_the_derived_one(self):
        big = dict(self.order, qty="170")
        res = self.run_check(order=big, prices={"TSLA": 364.5}, cfg=example(block_on_unverified=False))
        self.assertEqual(self.states(res)["loss"], "block")
        self.assertIn("over your $1,000 max loss per trade", "\n".join(res["results"][0]["reasons"]))


class ShareBasis(unittest.TestCase):
    """M2: trader-exit, the time machine and the record spread the commission over the same share basis, the
    percent config's derived max loss (costs.max_loss_basis), else the legacy key, else upstream's $50."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.chdir(self.d)
        self.exitp = load("trader-exit", "exit")
        self.exitp.cost_inputs = lambda sym, day, now: (ADV, "served", None, "no live quote (served)")
        self.tm = load("trader-timemachine", "timemachine")
        self.record = load("trader-record", "record")
        with open(os.path.join(FIX, "trader-budget", "config-upstream.json")) as fh:
            self.legacy = json.load(fh)

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.d)

    def exit_card(self, cfg_path, target="2R"):
        code, out, err = run(self.exitp, ["plan", "--symbol", "TSLA", "--entry", "364.18", "--or-high", "362.18",
                                          "--or-low", "354.47", "--time", "10:15", "--entry-bar", "8", "--date",
                                          "2026-10-19", "--now", "2026-10-19 10:16", "--target", target,
                                          "--config", cfg_path, "--json"])
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def test_the_basis(self):
        self.assertEqual(C.max_loss_basis(example()), 1000.0)
        self.assertEqual(C.max_loss_basis(example(max_loss_per_trade_usd=50)), 50.0)     # the stricter
        self.assertEqual(C.max_loss_basis(self.legacy), 50.0)
        self.assertEqual(C.max_loss_basis({}), C.DEFAULT_MAX_LOSS_USD)
        self.assertEqual(C.max_loss_basis({"max_loss_per_trade_usd": 80}), 80.0)
        with self.assertRaises(C.CostError):
            C.max_loss_basis(example(sizing={"trade_notional_usd": -1, "max_loss_pct_of_notional": 1}))

    def test_exit_writes_the_170_share_card_under_the_percent_config(self):
        plan = self.exit_card(EXAMPLE)
        card = plan["costs"]
        self.assertEqual((card["shares"], card["max_loss_usd"], card["shares_basis"]),
                         (170, 1000.0, "floor(1000.00 max loss / 5.86 risk) = 170 shares"))
        self.assertAlmostEqual(card["cost_r"], 0.089013, places=6)
        self.assertAlmostEqual(plan["reward_risk_net"], 1.7548, places=4)     # (11.72 - 0.5216) / (5.86 + 0.5216)
        legacy = os.path.join(self.d, "legacy.json")
        with open(legacy, "w") as fh:
            json.dump(self.legacy, fh)
        self.assertEqual(self.exit_card(legacy)["costs"]["shares"], 8)

    def test_the_three_cards_agree(self):
        with open(PLAN) as fh:
            bare = json.load(fh)                       # the reel's plan file at 2R: no cost card
        bare.update(target=375.90, target_r=2.0, reward_risk=2.0)
        legacy = os.path.join(self.d, "legacy.json")
        with open(legacy, "w") as fh:
            json.dump(self.legacy, fh)
        for cfg, path, shares in ((example(), EXAMPLE, 170), (self.legacy, legacy, 8)):
            ex = self.exit_card(path)["costs"]
            tmc = self.tm.cost_card_for(self.tm.normalize_plan(bare), "auto", cfg, adv_usd=ADV)
            rec, how = self.record.card_for(bare, cfg)
            tm_unverified = self.tm.cost_card_for(self.tm.normalize_plan(bare), "auto", cfg)
            self.assertEqual((ex["shares"], tmc["shares"], rec["shares"]), (shares,) * 3)
            self.assertEqual(ex["cost_r"], tmc["cost_r"])
            self.assertEqual((rec["cost_r"], rec["per_side_bps"]), (tm_unverified["cost_r"], tm_unverified["per_side_bps"]))
            self.assertEqual(C.model_of(ex)["max_loss_usd"], C.model_of(tmc)["max_loss_usd"])


class TicketPortfolio(unittest.TestCase):
    def test_a_percent_config_starts_the_paper_account_at_one_notional(self):
        d = tempfile.mkdtemp()
        try:
            pf = os.path.join(d, "portfolio.json")
            ticket.apply_fill(pf, example(), "TSLA", "buy", 156, 364.20, "2026-10-19")
            with open(pf) as fh:
                self.assertEqual(json.load(fh)["cash"], round(100000 - 156 * 364.20, 2))
        finally:
            shutil.rmtree(d)


if __name__ == "__main__":
    unittest.main()
