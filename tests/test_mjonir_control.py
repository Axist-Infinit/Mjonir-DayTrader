"""mjonir.control: eligible bars, identifier-only seeds (order-free, a deleted session changes nothing
else), the control trade's geometry, skips counted, and the delta-0 pin (chunk 2, step 2.5)."""

import unittest

import _mj  # noqa: F401  (sys.path, throwaway data dirs)
import synth
from mjonir import control as CT
from mjonir import outcomes as O
from mjonir import stats as S

DATES = ["2026-10-%02d" % d for d in (5, 6, 7, 8, 9, 12, 13, 14)]


def sessions():
    return {d: synth.make_session(d, i) for i, d in enumerate(DATES)}


class Eligible(unittest.TestCase):
    def test_after_the_range_inside_the_window_before_last(self):
        self.assertEqual(CT.eligible_bars(3, 10), list(range(3, 10)))
        self.assertEqual(CT.eligible_bars(3, 77, entry_until=20), list(range(3, 21)))
        self.assertEqual(CT.eligible_bars(3, 41, entry_until=77), list(range(3, 41)))
        self.assertEqual(CT.eligible_bars(3, 3), [])
        self.assertEqual(CT.baseline_entry_bar(3), 2)


class Seeds(unittest.TestCase):
    def draws(self, days, order):
        out = {}
        for d in order:
            S_ = days[d]
            e = S_[5]["c"]
            got, _ = CT.draw_controls(S_, "TSLA", d, 19, 3, 3, 77, e, e * 0.99, 1.0)
            out[d] = [(c["bar"], round(c["net_r"], 12)) for c in got]
        return out

    def test_identifier_seeds_are_order_free(self):
        days = sessions()
        a = self.draws(days, DATES)
        b = self.draws(days, list(reversed(DATES)))
        self.assertEqual(a, b)
        dropped = [d for d in DATES if d != DATES[3]]
        c = self.draws(days, dropped)
        self.assertEqual({d: a[d] for d in dropped}, c)          # deleting a session changes no other
        self.assertNotEqual(self.draws(days, DATES)[DATES[0]],
                            {d: [(c_["bar"], round(c_["net_r"], 12)) for c_ in CT.draw_controls(
                                days[d], "TSLA", d, 7, 3, 3, 77, days[d][5]["c"], days[d][5]["c"] * 0.99, 1.0)[0]]
                             for d in DATES[:1]}[DATES[0]])        # another seed, other bars
        self.assertEqual(CT.session_rng(19, "TSLA", "2026-10-05").random(),
                         CT.session_rng(19, "TSLA", "2026-10-05").random())

    def test_skips_are_counted(self):
        s = sessions()[DATES[0]]
        e = s[5]["c"]
        self.assertEqual(CT.draw_controls(s, "X", DATES[0], 19, 3, 3, 77, e, e * 0.9999, 1.0), ([], {"risk_floor": 3}))
        self.assertEqual(CT.draw_controls(s, "X", DATES[0], 19, 3, 3, 3, e, e * 0.99, 1.0), ([], {"no_eligible_bar": 3}))


class Geometry(unittest.TestCase):
    def test_the_rules_risk_percent_and_target_multiple(self):
        s = sessions()[DATES[1]]
        e, stop = s[6]["c"], s[6]["c"] * 0.985
        t = CT.control_trade(s, 20, e, stop, 2.0, 77)
        c = s[20]["c"]
        self.assertAlmostEqual((t["entry"] - t["stop"]) / t["entry"], (e - stop) / e)
        self.assertAlmostEqual(t["target"], c + 2.0 * (c - t["stop"]))
        nt = CT.control_trade(s, 20, e, stop, None, 77)
        self.assertIsNone(nt["target"])
        self.assertIn(nt["outcome"], ("stop", "close"))

    def test_on_the_rules_own_bar_it_is_the_rules_trade(self):
        # the pin: the control forced to the rule's bar scores exactly the rule's trade, so the delta is 0
        days = sessions()
        rule_by, ctrl_by = {}, {}
        for d, s in days.items():
            e = s[5]["c"]
            stop = e * 0.99
            target = e + 1.0 * (e - stop)
            rule = O.score_trade(s, 5, e, stop, target, 77, 0.1)
            got, _ = CT.draw_controls(s, "TSLA", d, 19, 3, 3, 77, e, stop, 1.0,
                                      cost_fn=lambda entry, risk: 0.1, force_bar=5)
            self.assertEqual([g["stop"] for g in got], [stop] * 3)
            self.assertEqual([g["net_r"] for g in got], [rule["net_r"]] * 3)
            rule_by[d], ctrl_by[d] = [rule["net_r"]], [g["net_r"] for g in got]
        one = S.paired_delta_ci(rule_by, {d: v[:1] for d, v in ctrl_by.items()})
        self.assertEqual((one["delta"], one["lo"], one["hi"]), (0.0, 0.0, 0.0))          # one draw: exactly 0
        three = S.paired_delta_ci(rule_by, ctrl_by)                                      # mean of 3: float noise
        for k in ("delta", "lo", "hi"):
            self.assertAlmostEqual(three[k], 0.0, places=12)


if __name__ == "__main__":
    unittest.main()
