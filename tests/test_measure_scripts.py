"""Chunk 2, step 2.6: costs in trader-exit, trader-budget, trader-risk and trader-broker. Gross and net
reward:risk and the net refusal, the cost card in the plan, the datr stop, the no-target (Zarattini) plan,
the net max loss, the OTO order, the spread gate and the no-target check in three states, and the
flatten reminder. No network: Massive answers are served."""

import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest

import _mj  # noqa: F401  (sys.path, throwaway data dirs)
from _load import FIX, load
from mjonir import costs as C
from mjonir import yahoo_shape as Y

exitp = load("trader-exit", "exit")
size = load("trader-budget", "size")
check = load("trader-risk", "check")
ticket = load("trader-broker", "ticket")

PLAN = os.path.join(FIX, "trader-budget", "plan-tsla.json")
CFG = os.path.join(os.path.dirname(FIX), "..", "trader-budget", "config.example.json")
NOW = "2026-10-19 10:16"
QNOW = check.parse_now("2026-10-19 10:16")
ADV = 2.0e10                                   # TSLA clears the 100M floor: the 4 bp tier
DAILY = _mj.fixture("aggs-TSLA-1d-2026-07-20_2026-10-19.json")["results"]


def run(mod, argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = mod.main(argv)
    return code, out.getvalue(), err.getvalue()


def example_cfg(**over):
    with open(CFG) as fh:
        c = json.load(fh)
    c.update(over)
    return c


def reel_plan(**over):
    with open(PLAN) as fh:
        p = json.load(fh)
    p.update(over)
    return p


def card(target=370.04, shares=8):
    return C.cost_card(364.18, 358.32, target, shares, adv_usd=ADV, max_loss_usd=50.0)


class ExitPlan(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.chdir(self.d)
        os.mkdir("trader")
        self.saved = (exitp.cost_inputs, Y.fetch_daily_rows)
        exitp.cost_inputs = lambda sym, day, now: (ADV, "served", None, "no live quote (served)")

    def tearDown(self):
        exitp.cost_inputs, Y.fetch_daily_rows = self.saved
        os.chdir(self.cwd)
        shutil.rmtree(self.d)

    def plan(self, *args):
        return run(exitp, ["plan", "--symbol", "TSLA", "--entry", "364.18", "--or-high", "362.18", "--or-low",
                           "354.47", "--time", "10:15", "--entry-bar", "8", "--date", "2026-10-19", "--now", NOW]
                   + list(args))

    def test_the_1r_reel_is_refused_net_of_costs(self):
        code, out, err = self.plan("--target", "1R", "--json")
        self.assertEqual(code, 1)
        self.assertIn("net reward:risk 0.77 (gross 1.0, after a 0.7599 a share round trip, 0.130 R) is under your "
                      "min_reward_risk 1: refused", err)

    def test_the_2r_plan_passes_with_its_cost_card(self):
        code, out, err = self.plan("--target", "2R", "--json")
        self.assertEqual(code, 0, err)
        p = json.loads(out)
        self.assertEqual((p["exit"], p["target"], p["reward_risk_gross"]), ("target", 375.9, 2.0))
        self.assertEqual(round(p["reward_risk_net"], 2), 1.66)
        k = p["costs"]
        self.assertEqual((k["slippage_bps"], k["shares"], k["shares_basis"]),
                         (4.0, 8, "floor(50.00 max loss / 5.86 risk) = 8 shares"))
        self.assertEqual(round(k["cost_r"], 3), 0.130)
        code, text, _ = self.plan("--target", "2R")
        self.assertIn("Reward:risk   2.0 gross, 1.66 net", text)
        self.assertIn("Costs: 0.7599 a share round trip = 0.130 R (4 bp slippage tier", text)

    def test_gross_basis_and_no_costs_keep_upstreams_warning(self):
        with open(os.path.join("trader", "config.json"), "w") as fh:
            json.dump({"min_reward_risk_basis": "gross"}, fh)
        code, out, _ = self.plan("--target", "1R", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["warnings"], [])               # gross 1.0 is not under 1.0
        os.remove(os.path.join("trader", "config.json"))
        code, out, _ = self.plan("--target", "1R", "--json", "--no-costs")
        p = json.loads(out)
        self.assertEqual((code, p["costs"], p["reward_risk_net"]), (0, None, 1.0))

    def test_shares_spread_the_commission(self):
        code, out, _ = self.plan("--target", "2R", "--json", "--shares", "170")
        k = json.loads(out)["costs"]
        self.assertEqual((k["shares"], k["shares_basis"]), (170, "--shares 170"))
        self.assertLess(k["cost_r"], 0.13)

    def test_the_zarattini_form(self):
        Y.fetch_daily_rows = lambda client, cal, sym, start, end: [
            (r["t"], r["o"], r["h"], r["l"], r["c"], r["v"]) for r in DAILY
            if start.isoformat() <= exitp.to_eastern(exitp.utc_of(r["t"] // 1000)).date().isoformat() <= end.isoformat()]
        code, out, err = self.plan("--target", "none", "--exit", "close", "--stop", "datr:0.10", "--json")
        self.assertEqual(code, 0, err)
        p = json.loads(out)
        rows = [r for r in DAILY if r["t"] < DAILY[-1]["t"]][-15:]           # the 15 sessions before 10-19
        trs = [max(r["h"] - r["l"], abs(r["h"] - q["c"]), abs(r["l"] - q["c"])) for q, r in zip(rows, rows[1:])]
        atr = sum(trs) / 14
        self.assertAlmostEqual(p["atr"], atr, places=4)
        self.assertEqual((p["atr_bars"], p["stop_rule"], p["exit"], p["target"], p["target_r"]),
                         (14, "datr", "close", None, None))
        self.assertEqual(p["stop"], float(exitp.floor_cents(364.18 - 0.10 * round(atr, 6))))
        self.assertIsNone(p["reward_risk_net"])
        self.assertIn("No target", p["warnings"][-1])
        code, text, _ = self.plan("--target", "none", "--stop", "datr:0.10")     # --target none implies close
        self.assertEqual(code, 0)
        self.assertIn("Target        none: out at the stop or at the flat-by close", text)
        self.assertIn("Reward:risk   not measured (no target)", text)

    def test_datr_without_massive_is_refused_unverified(self):
        code, _, err = self.plan("--stop", "datr:0.10")
        self.assertEqual(code, 1)
        self.assertIn("datr stop needs Massive daily bars", err)
        self.assertIn("unverified", err)

    def test_the_live_quote_follows_the_now_clock(self):
        exitp.cost_inputs = self.saved[0]                  # the real one, with Massive served below
        asked = []
        saved = (Y.fetch_adv_usd, Y.fetch_quote, exitp.SOURCE)
        Y.fetch_adv_usd = lambda client, cal, sym, asof, n=20: ADV
        Y.fetch_quote = lambda client, sym: asked.append(sym) or {"bid": 1.0, "ask": 1.01, "t_ms": 0}
        exitp.SOURCE = "massive"
        try:
            real = exitp.utc_now()
            today = exitp.to_eastern(real).date()
            past = exitp.datetime.date(2026, 10, 19)
            self.assertIsNone(exitp.cost_inputs("TSLA", past, exitp.parse_now("2026-10-19 10:16"))[2])
            self.assertIsNone(exitp.cost_inputs("TSLA", today, exitp.parse_now("2026-10-19 10:16"))[2])
            self.assertEqual(asked, [])                      # a replay's --now never asks the NBBO of now
            self.assertIsNotNone(exitp.cost_inputs("TSLA", today, real)[2])
            self.assertEqual(asked, ["TSLA"])
        finally:
            Y.fetch_adv_usd, Y.fetch_quote, exitp.SOURCE = saved

    def test_exit_and_target_must_agree(self):
        self.assertIn("--exit close has no target", self.plan("--exit", "close", "--target", "2R")[2])
        self.assertIn("use --exit close", self.plan("--exit", "target", "--target", "none")[2])


class Size(unittest.TestCase):
    def test_the_net_max_loss(self):
        s = size.size_trade(reel_plan(target=375.90), example_cfg(), today="2026-10-19")
        # no cost card in the plan: ADV unverified, 15 bp + 3 bp a side
        self.assertEqual((s["qty"], s["costs"]["per_side_bps"]), (6, 18.0))
        self.assertEqual(s["limits"][0]["shares"], 6)
        self.assertAlmostEqual(s["max_loss"], round(6 * (5.86 + 2 * 364.18 * 18 / 1e4) + 2, 2))
        self.assertEqual(s["max_loss_gross"], 35.16)
        with_card = size.size_trade(reel_plan(target=375.90, costs=card(375.90)), example_cfg(), today="2026-10-19")
        self.assertEqual((with_card["qty"], with_card["costs"]["from"]), (7, "the plan's cost card"))
        self.assertLessEqual(with_card["max_loss"], 50)
        o = size.bracket_order(with_card)
        self.assertEqual((o["order_class"], o["qty"], o["plan"]["max_loss"]), ("bracket", "7", with_card["max_loss"]))
        self.assertIn("round trip", o["why"])

    def test_the_basis_must_be_net_or_gross(self):
        with self.assertRaises(size.SizeError) as cm:
            size.size_trade(reel_plan(), example_cfg(min_reward_risk_basis="nett"), today="2026-10-19")
        self.assertIn("net or gross", str(cm.exception))

    def test_the_1r_reel_is_refused_on_net(self):
        s = size.size_trade(reel_plan(costs=card()), example_cfg(), today="2026-10-19")
        self.assertIn("net reward:risk 0.76", s["refusal"])               # 7 shares: the commission a share moves it
        self.assertIsNone(size.bracket_order(s))
        self.assertIsNone(size.size_trade(reel_plan(), example_cfg(), today="2026-10-19", no_costs=True)["refusal"])

    def test_a_no_target_plan_writes_an_oto_order(self):
        p = reel_plan(target=None, target_r=None, exit="close", reward_risk=None, costs=card(None))
        s = size.size_trade(p, example_cfg(), today="2026-10-19")
        self.assertIsNone(s["refusal"])
        self.assertIn("min_reward_risk refusal is skipped", s["notes"][0])
        o = size.bracket_order(s)
        self.assertEqual((o["order_class"], o["stop_loss_stop_price"], o["plan"]["exit"]), ("oto", "358.32", "close"))
        self.assertNotIn("take_profit_limit_price", o)
        self.assertIn("no take-profit: flatten by 15:55", o["why"])
        text = size.plan_report(s, o)
        self.assertIn("Proposed OTO order", text)
        self.assertIn("stop-loss 358.32, no take-profit", text)


class Risk(unittest.TestCase):
    def order(self, **over):
        s = size.size_trade(reel_plan(target=375.90, costs=card(375.90)), example_cfg(), today="2026-10-19")
        o = size.bracket_order(s)
        o.update(over)
        return o

    def test_net_loss_and_net_reward_risk_block_the_upstream_reel(self):
        with open(os.path.join(FIX, "trader-risk", "orders-tsla.json")) as fh:
            reel = json.load(fh)["orders"][0]
        r = check.check([reel], example_cfg(), now=QNOW)["results"][0]
        self.assertEqual(r["verdict"], "BLOCK")
        why = " | ".join(r["reasons"])
        self.assertIn("loss: 8 shares x (5.86 risk + 1.3110 round trip) + $2 commissions = $59.37", why)
        self.assertIn("reward:risk: net 0.58 (gross 1.00", why)
        self.assertEqual((r["max_loss_gross"], r["reward_risk"]), (46.88, 1.0))
        r = check.check([reel], example_cfg(), now=QNOW, no_costs=True)["results"][0]
        self.assertEqual((r["verdict"], r["max_loss"]), ("PASS", 46.88))

    def test_the_sized_2r_order_passes_with_the_spread_unverified(self):
        r = check.check([self.order()], example_cfg(), now=QNOW)["results"][0]
        self.assertEqual(r["verdict"], "PASS", r["reasons"])
        self.assertEqual([(c["name"], c["state"]) for c in r["checks"]], [("spread", "unverified")])
        self.assertIn("spread unverified", " ".join(r["warnings"]))
        self.assertLessEqual(r["max_loss"], 50)
        self.assertEqual(r["reward_risk_net"], 1.64)                     # 7 shares: $2 / 7 a share
        r = check.check([self.order()], example_cfg(costs=dict(C.DEFAULTS, spread_unverified="block")),
                        now=QNOW)["results"][0]
        self.assertEqual(r["verdict"], "BLOCK")
        self.assertIn("spread: unverified", " ".join(r["reasons"]))

    def test_the_live_spread_gate(self):
        t = int((QNOW - check.datetime.datetime(1970, 1, 1)).total_seconds() * 1000)
        tight = lambda sym: {"bid": 364.17, "ask": 364.19, "t_ms": t - 2000}     # noqa: E731
        wide = lambda sym: {"bid": 363.80, "ask": 364.60, "t_ms": t - 2000}      # noqa: E731
        stale = lambda sym: {"bid": 364.17, "ask": 364.19, "t_ms": t - 600000}   # noqa: E731
        res = {}
        for name, fn in (("tight", tight), ("wide", wide), ("stale", stale), ("none", lambda sym: None)):
            r = check.check([self.order()], example_cfg(), now=QNOW, quote_fn=fn)["results"][0]
            res[name] = (r["verdict"], [c["state"] for c in r["checks"] if c["name"] == "spread"][0])
        self.assertEqual(res, {"tight": ("PASS", "pass"), "wide": ("BLOCK", "block"),
                               "stale": ("PASS", "unverified"), "none": ("PASS", "unverified")})

    def test_the_no_target_check_in_three_states(self):
        p = reel_plan(target=None, target_r=None, exit="close", reward_risk=None, costs=card(None))
        oto = size.bracket_order(size.size_trade(p, example_cfg(), today="2026-10-19"))
        r = check.check([oto], example_cfg(), now=QNOW)["results"][0]
        self.assertEqual(r["verdict"], "BLOCK")
        self.assertIn("allow_no_target is false", " ".join(r["reasons"]))
        r = check.check([oto], example_cfg(allow_no_target=True), now=QNOW)["results"][0]
        self.assertEqual(r["verdict"], "PASS", r["reasons"])
        self.assertIn(("target", "pass"), [(c["name"], c["state"]) for c in r["checks"]])
        bare = dict(oto, plan=dict(oto["plan"], exit=None, flat_by=None), order_class="oto")
        r = check.check([bare], example_cfg(allow_no_target=True), now=QNOW)["results"][0]
        self.assertIn(("target", "unverified"), [(c["name"], c["state"]) for c in r["checks"]])
        self.assertIn("unverified: no target and no exit rule", " ".join(r["warnings"]))
        r = check.check([bare], example_cfg(allow_no_target=True, block_on_unverified=True), now=QNOW)["results"][0]
        self.assertEqual(r["verdict"], "BLOCK")

    def test_oto_format(self):
        p = reel_plan(target=None, target_r=None, exit="close", reward_risk=None, costs=card(None))
        oto = size.bracket_order(size.size_trade(p, example_cfg(), today="2026-10-19"))
        cfg = example_cfg(allow_no_target=True)
        self.assertIn("needs stop_loss_stop_price", " ".join(check.check(
            [dict(oto, stop_loss_stop_price=None)], cfg, now=QNOW)["results"][0]["reasons"]))
        self.assertIn("with a take-profit too it is a bracket", " ".join(check.check(
            [dict(oto, take_profit_limit_price="380.00")], cfg, now=QNOW)["results"][0]["reasons"]))
        self.assertIn("whole shares only", " ".join(check.check(
            [dict(oto, qty="2.5")], cfg, now=QNOW)["results"][0]["reasons"]))
        self.assertNotIn("advanced order", " ".join(check.check([oto], cfg, now=QNOW)["results"][0]["warnings"]))


class Ticket(unittest.TestCase):
    def oto(self):
        p = reel_plan(target=None, target_r=None, exit="close", reward_risk=None, costs=card(None))
        return size.bracket_order(size.size_trade(p, example_cfg(), today="2026-10-19"))

    def test_order_class_of(self):
        with open(os.path.join(FIX, "trader-risk", "orders-tsla.json")) as fh:
            reel = json.load(fh)["orders"][0]
        self.assertEqual(ticket.order_class_of(reel), "bracket")
        self.assertEqual(ticket.order_class_of(self.oto()), "oto")
        self.assertEqual(ticket.order_class_of({"symbol": "KO", "side": "buy", "notional": "100"}), "simple")

    def test_the_oto_ticket_carries_the_flatten_reminder(self):
        o = self.oto()
        self.assertIn("no take-profit: flat by 15:55", ticket.plain(o))
        text, _ = ticket.render(o, 1, 1, {}, None, {"orders": []}, "2026-10-19")
        self.assertIn("No take-profit on this order: flatten by 15:55 New York (ticket.py flatten --symbol TSLA).", text)
        self.assertIn("There is no take-profit.", text)
        tj = ticket.ticket_json(o, 1, {}, None, {"orders": []}, "2026-10-19")
        self.assertEqual((tj["order_class"], tj["bracket"]), ("oto", False))
        self.assertIn("flatten by 15:55", tj["flatten_reminder"])

    def test_the_flatten_reminder_after_a_placed_oto(self):
        d = tempfile.mkdtemp()
        try:
            orders, cfgp = os.path.join(d, "orders.json"), os.path.join(d, "config.json")
            risk, state = os.path.join(d, "risk.json"), os.path.join(d, "broker.json")
            o = self.oto()
            with open(orders, "w") as fh:
                json.dump({"orders": [o]}, fh)
            c = example_cfg(allow_no_target=True)
            with open(cfgp, "w") as fh:
                json.dump(c, fh)
            res = check.check([o], c, now=QNOW)
            self.assertEqual(res["results"][0]["verdict"], "PASS", res["results"][0]["reasons"])
            with open(risk, "w") as fh:
                json.dump(res, fh)
            base = ["--orders", orders, "--config", cfgp, "--risk", risk, "--state", state, "--now", NOW]
            code, text, err = run(ticket, ["approve", "--index", "1", "--reply", "yes"] + base)
            self.assertEqual(code, 0, err)
            self.assertIn("No take-profit on this order: flatten by 15:55", text)
            code, text, err = run(ticket, ["result", "--index", "1", "--status", "placed"] + base)
            self.assertEqual(code, 0, err)
            self.assertIn("When the stop-loss fills later", text)
            self.assertIn("No take-profit on this order: flatten by 15:55", text)
        finally:
            shutil.rmtree(d)


if __name__ == "__main__":
    unittest.main()
