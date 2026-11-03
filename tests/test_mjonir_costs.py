"""mjonir.costs: tier edges, the half spread, the TSLA reel's arithmetic, the spread gate and the card
(chunk 2, step 2.2)."""

import json
import os
import unittest

import _mj  # noqa: F401  (sys.path, throwaway data dirs)
from _load import ROOT
from mjonir import costs as C

TIERS = C.DEFAULTS["slippage_tiers_bps"]
NOW_MS = 1792419300000       # 2026-10-19 10:15 New York


class Tiers(unittest.TestCase):
    def test_the_highest_floor_cleared(self):
        self.assertEqual(C.tier_bps(2e10, TIERS), (4.0, None))
        self.assertEqual(C.tier_bps(100000000, TIERS), (4.0, None))          # exactly on the floor clears it
        self.assertEqual(C.tier_bps(99999999.99, TIERS), (8.0, None))
        self.assertEqual(C.tier_bps(30000000, TIERS), (8.0, None))
        self.assertEqual(C.tier_bps(29999999, TIERS), (15.0, None))
        self.assertEqual(C.tier_bps(0, TIERS), (15.0, None))

    def test_unknown_adv_is_the_most_expensive_tier_and_flagged(self):
        self.assertEqual(C.tier_bps(None, TIERS), (15.0, "adv_unverified"))
        self.assertEqual(C.tier_bps(5, [[10, 2], [100, 1]]), (2.0, "adv_below_tiers"))
        self.assertEqual(C.tier_bps(5e6, list(reversed(TIERS))), (15.0, None))   # order of the tiers is free


class Spread(unittest.TestCase):
    def test_measured_stale_missing_crossed(self):
        q = {"bid": 364.10, "ask": 364.20, "t_ms": NOW_MS - 5000}
        bps, st = C.half_spread_bps(q, NOW_MS, 60)
        self.assertEqual(st, "measured")
        self.assertAlmostEqual(bps, 0.05 / 364.15 * 1e4)
        self.assertEqual(C.half_spread_bps(dict(q, t_ms=NOW_MS - 61000), NOW_MS, 60), (None, "stale"))
        self.assertEqual(C.half_spread_bps(dict(q, t_ms=NOW_MS + 120000), NOW_MS, 60), (None, "stale"))
        self.assertEqual(C.half_spread_bps(None, NOW_MS, 60), (None, "missing"))
        self.assertEqual(C.half_spread_bps(dict(q, bid=0), NOW_MS, 60), (None, "missing"))
        self.assertEqual(C.half_spread_bps(dict(q, bid=365.0), NOW_MS, 60), (None, "crossed"))

    def test_the_gate(self):
        g = C.spread_gate(1.0, "measured", 364.18, 5.86, 0.10)
        self.assertEqual(g["state"], "pass")
        self.assertAlmostEqual(g["spread_usd"], 0.0728, places=4)
        self.assertEqual(C.spread_gate(10.0, "measured", 364.18, 5.86, 0.10)["state"], "block")   # 0.73 > 0.586
        self.assertEqual(C.spread_gate(None, "stale", 364.18, 5.86, 0.10)["state"], "unverified")
        self.assertEqual(C.spread_gate(3.0, "default", 364.18, 5.86, 0.10)["state"], "unverified")


class Arithmetic(unittest.TestCase):
    def test_the_reel_worked_check(self):
        side = C.side_cost_per_share(364.18, 7, 1.0, 8)
        self.assertAlmostEqual(side, 364.18 * 7 / 1e4 + 0.125)
        rt = C.round_trip_cost_per_share(364.18, 7, 1.0, 8)
        self.assertEqual(round(rt, 2), 0.76)
        self.assertEqual(round(C.cost_r(rt, 5.86), 2), 0.13)
        self.assertAlmostEqual(C.net_r(1.0, 0.13), 0.87)
        self.assertEqual(round(C.net_reward_risk(364.18, 358.32, 370.04, rt), 3), 0.770)
        self.assertEqual(round(C.net_reward_risk(364.18, 358.32, 375.90, rt), 3), 1.656)
        self.assertIsNone(C.net_reward_risk(364.18, 358.32, None, rt))
        self.assertEqual(round(C.net_reward_risk(364.18, 370.04, 358.32, rt, long=False), 3), 0.770)

    def test_card(self):
        card = C.cost_card(364.18, 358.32, 370.04, 8, adv_usd=2.0e10)
        self.assertEqual((card["slippage_bps"], card["half_spread_bps"], card["per_side_bps"]), (4.0, 3.0, 7.0))
        self.assertEqual(round(card["cost_r"], 2), 0.13)
        self.assertEqual(round(card["round_trip_usd"], 2), 6.08)
        self.assertEqual((card["reward_risk_gross"], round(card["reward_risk_net"], 2)), (1.0, 0.77))
        self.assertEqual(card["flags"], ["spread_missing"])
        self.assertEqual(card["spread_gate"]["state"], "unverified")
        self.assertIn("0.130 R", C.card_line(card))
        live = C.cost_card(364.18, 358.32, 370.04, 8, adv_usd=2.0e10, now_ms=NOW_MS,
                           quote={"bid": 364.17, "ask": 364.19, "t_ms": NOW_MS - 1000})
        self.assertEqual((live["spread_basis"], live["spread_gate"]["state"], live["flags"]), ("measured", "pass", []))
        self.assertLess(live["cost_r"], card["cost_r"])
        no_adv = C.cost_card(364.18, 358.32, 370.04, 8)
        self.assertEqual((no_adv["slippage_bps"], no_adv["flags"]), (15.0, ["adv_unverified", "spread_missing"]))
        nt = C.cost_card(364.18, 358.32, None, 8, adv_usd=2.0e10)
        self.assertEqual((nt["reward_risk_gross"], nt["reward_risk_net"]), (None, None))

    def test_off_by_config_costs_nothing(self):
        card = C.cost_card(364.18, 358.32, 370.04, 8, cfg={"costs": C.OFF})
        self.assertTrue(card["off"])
        self.assertEqual((card["round_trip_per_share"], card["cost_r"], card["spread_gate"]), (0.0, 0.0, None))
        self.assertEqual(card["reward_risk_net"], 1.0)
        self.assertIsNone(C.model_of(card))
        self.assertEqual(C.trade_cost_r(364.18, 5.86, None), 0.0)

    def test_model_and_trade_cost(self):
        card = C.cost_card(364.18, 358.32, 370.04, 8, adv_usd=2.0e10)
        m = C.model_of(card)
        self.assertEqual(m, {"per_side_bps": 7.0, "commission_usd": 1.0, "shares": 8, "max_loss_usd": None})
        self.assertAlmostEqual(C.trade_cost_r(364.18, 5.86, m), card["cost_r"], places=5)
        # sized by the max loss: a trade with half the risk carries twice the shares, half the commission a share
        sized = C.model_of(C.cost_card(364.18, 358.32, 370.04, 8, adv_usd=2.0e10, max_loss_usd=50))
        self.assertAlmostEqual(C.trade_cost_r(364.18, 5.86, sized), card["cost_r"], places=5)
        half = C.trade_cost_r(364.18, 2.93, sized)
        self.assertAlmostEqual(half, (2 * 364.18 * 7 / 1e4 + 2 * 1.0 / 17) / 2.93)

    def test_shares_basis(self):
        self.assertEqual(C.shares_basis(5.86)[0], 8)            # floor(50 / 5.86)
        self.assertEqual(C.shares_basis(5.86, 100)[0], 17)
        self.assertEqual(C.shares_basis(80.0)[0], 1)

    def test_settings_refuse_nonsense(self):
        for bad in ({"spread_source": "nbbo"}, {"commission_usd": -1}, {"slippage_tiers_bps": [[0, -2]]},
                    {"slippage_tiers_bps": "4bp"}, {"spread_unverified": "ignore"}):
            with self.assertRaises(C.CostError, msg=bad):
                C.settings({"costs": bad})
        self.assertEqual(C.settings({})["commission_usd"], 1.0)
        self.assertEqual(C.settings({"commission_usd": 0})["commission_usd"], 0.0)   # the block itself
        with self.assertRaises(C.CostError):
            C.cost_card(364.18, 365.0, 370.04, 8)
        with self.assertRaises(C.CostError):
            C.cost_card(364.18, 358.32, 370.04, 0)


class ExampleConfig(unittest.TestCase):
    def test_the_example_ships_the_defaults(self):
        with open(os.path.join(ROOT, "trader-budget", "config.example.json")) as fh:
            cfg = json.load(fh)
        self.assertEqual(cfg["costs"], C.DEFAULTS)
        self.assertEqual(C.settings(cfg)["slippage_tiers_bps"], [[1e8, 4.0], [3e7, 8.0], [0.0, 15.0]])


if __name__ == "__main__":
    unittest.main()
