"""mjonir.stats: the Wilson pin, the decided rate, the net break-even, the seeded bootstraps, the verdict
templates and the banned words (chunk 2, step 2.1)."""

import ast
import os
import unittest

import _mj  # noqa: F401  (sys.path, throwaway data dirs)
from _load import ROOT
from mjonir import stats as S


class Wilson(unittest.TestCase):
    def test_the_reel_pin(self):
        lo, hi = S.wilson(13, 28)
        self.assertEqual((round(lo, 4), round(hi, 4)), (0.2953, 0.6419))

    def test_edges(self):
        self.assertEqual(S.wilson(0, 0), (0.0, 0.0))
        lo, hi = S.wilson(0, 10)
        self.assertEqual(lo, 0.0)
        self.assertGreater(hi, 0.0)
        lo, hi = S.wilson(10, 10)
        self.assertEqual(hi, 1.0)
        # the house's floor: at p = 0.5 the Wilson half-width is 14.8 points at n = 40 (the plan said 14.6)
        lo, hi = S.wilson(20, 40)
        self.assertEqual(round(100 * (hi - lo) / 2, 1), 14.8)
        self.assertEqual(S.N_FLOOR, 40)

    def test_decided_rate_counts_target_and_stop_only(self):
        d = S.decided_rate(["target"] * 13 + ["stop"] * 15 + ["close"] * 5)
        self.assertEqual((d["k"], d["n"]), (13, 28))
        self.assertAlmostEqual(d["p"], 13 / 28)
        self.assertEqual((round(d["lo"], 4), round(d["hi"], 4)), (0.2953, 0.6419))
        self.assertEqual(S.decided_rate(["close", "close"]), {"k": 0, "n": 0, "p": None, "lo": None, "hi": None})

    def test_net_break_even(self):
        self.assertEqual(S.net_break_even(1.0, 0.0), 0.5)
        self.assertAlmostEqual(S.net_break_even(2.0, 0.0), 1 / 3)
        self.assertAlmostEqual(S.net_break_even(1.0, 0.13), 0.565)
        # a decided fire at the break-even rate nets zero after costs
        p, t, c = S.net_break_even(1.5, 0.2), 1.5, 0.2
        self.assertAlmostEqual(p * (t - c) + (1 - p) * (-1 - c), 0.0)


class Bootstrap(unittest.TestCase):
    RS = [1.0, -1.0, -1.0, 0.4, 1.0, -1.0, 0.2, -0.3, 1.0, -1.0, -1.0, 1.0, 0.7]

    def test_seeded_and_reproducible(self):
        a = S.expectancy_ci(self.RS)
        self.assertEqual(a, S.expectancy_ci(list(self.RS)))
        self.assertEqual((a["n"], a["draws"], a["seed"]), (13, 2000, 19))
        self.assertAlmostEqual(a["mean"], sum(self.RS) / 13)
        self.assertLess(a["lo"], a["mean"])
        self.assertGreater(a["hi"], a["mean"])
        self.assertNotEqual(S.expectancy_ci(self.RS, seed=7)["lo"], a["lo"])

    def test_empty_is_refused(self):
        with self.assertRaises(ValueError):
            S.expectancy_ci([])
        with self.assertRaises(ValueError):
            S.paired_delta_ci({"d1": [1.0]}, {"d2": [0.0]})

    def test_one_trade_has_a_zero_width_interval(self):
        a = S.expectancy_ci([0.5])
        self.assertEqual((a["lo"], a["hi"]), (0.5, 0.5))

    def test_paired_delta_resamples_sessions(self):
        rule = {"d%02d" % i: r for i, r in enumerate(self.RS)}
        same = S.paired_delta_ci(rule, {k: [v, v, v] for k, v in rule.items()})
        for key in ("delta", "lo", "hi"):
            self.assertAlmostEqual(same[key], 0.0, places=12)
        self.assertEqual(same["n_sessions"], 13)
        worse = {k: [v - 0.5, v - 0.3, v - 0.4] for k, v in rule.items()}
        d = S.paired_delta_ci(rule, worse)
        self.assertAlmostEqual(d["delta"], 0.4)
        self.assertGreater(d["lo"], 0)
        # a session without a control is not paired
        part = dict(worse)
        part.pop("d00")
        self.assertEqual(S.paired_delta_ci(rule, part)["n_sessions"], 12)
        self.assertEqual(d, S.paired_delta_ci(dict(reversed(list(rule.items()))), worse))   # order-free


def ex(n, mean, lo, hi):
    return {"n": n, "mean": mean, "lo": lo, "hi": hi}


class Verdicts(unittest.TestCase):
    """One statistic sets the history verdict: the net expectancy interval over every fire against 0. The
    decided rate is a diagnostic appended for a plan with a target (review 2c)."""

    def test_the_reel_cannot_judge(self):
        v = S.verdict_history({"target": 13, "stop": 15, "triggered": 33,
                               "expectancy": ex(33, -0.261, -0.592, 0.074)}, 1.0, 0.1986)
        self.assertEqual((v["state"], v["reason"], v["n"]), ("unverified", "n_below_floor", 33))
        self.assertEqual(v["text"], "Cannot judge: 33 fires, net average -0.261 R a trade (95% bootstrap [-0.592, "
                                    "+0.074]); n is below the 40-fire floor. Decided: 13 of 28 hit the target (46.4%, "
                                    "95% Wilson [29.5%, 64.2%]) against a net break-even of 59.9% at 1R after costs "
                                    "(the history's own mean round trip, 0.199 R).")
        self.assertEqual((v["decided"]["k"], v["decided"]["n"], round(v["decided"]["break_even"], 4)),
                         (13, 28, 0.5993))

    def test_the_two_year_reading(self):
        # the stored two-year run's numbers (docs/reviews/chunk2.md 4.4), recomputed under the 2c rule
        v = S.verdict_history({"target": 130, "stop": 116, "triggered": 285,
                               "expectancy": ex(285, -0.12523, -0.23468, -0.01593)}, 1.0, 0.18140)
        self.assertEqual((v["state"], v["reason"]), ("fail", "below"))
        self.assertEqual(v["text"], "Below zero: 285 fires, net average -0.125 R a trade (95% bootstrap [-0.235, "
                                    "-0.016]); the whole interval is under 0. Decided: 130 of 246 hit the target "
                                    "(52.8%, 95% Wilson [46.6%, 59.0%]) against a net break-even of 59.1% at 1R after "
                                    "costs (the history's own mean round trip, 0.181 R).")
        # chunk 3a review M2: the README now quotes the two-year reading under the example (percent) config,
        # docs/reviews/chunk3a.md section 7; recomputed here from that run's own numbers
        v3 = S.verdict_history({"target": 127, "stop": 116, "triggered": 281,
                                "expectancy": ex(281, -0.08823, -0.19327, 0.02325)}, 1.0, 0.1418)
        self.assertEqual((v3["state"], v3["reason"]), ("unverified", "straddles"))
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
            readme = " ".join(fh.read().split())
        self.assertIn(v3["text"], readme)                                 # the README quotes it verbatim

    def test_the_states_come_from_the_expectancy_only(self):
        # a decided rate far above its break-even does not pass a history whose net interval straddles 0
        hist = {"target": 50, "stop": 10, "triggered": 80}
        v = S.verdict_history(dict(hist, expectancy=ex(80, 0.05, -0.02, 0.12)), 1.0, 0.13)
        self.assertEqual((v["state"], v["reason"]), ("unverified", "straddles"))
        self.assertTrue(v["text"].startswith("Edge not distinguishable from zero: 80 fires"))
        v = S.verdict_history(dict(hist, expectancy=ex(80, 0.2, 0.05, 0.35)), 1.0, 0.13)
        self.assertEqual((v["state"], v["reason"]), ("pass", "above"))
        self.assertTrue(v["text"].endswith("A past sample is not a forward result."))
        v = S.verdict_history(dict(hist, expectancy=ex(80, -0.2, -0.35, -0.05)), 1.0, 0.13)
        self.assertEqual((v["state"], v["reason"]), ("fail", "below"))
        self.assertTrue(v["text"].startswith("Below zero: 80 fires"))
        self.assertEqual(S.verdict_history({"triggered": 0, "expectancy": None}, 1.0, 0.13)["text"],
                         "Cannot judge: the rule never fired in this history.")
        off = S.verdict_history(dict(hist, expectancy=ex(80, 0.2, 0.05, 0.35)), 2.0, 0.0, costs_on=False)
        self.assertIn("against a break-even of 33.3% at 2R with costs off.", off["text"])
        none = S.verdict_history({"target": 0, "stop": 0, "triggered": 5, "expectancy": ex(5, 0.1, -0.2, 0.4)},
                                 1.0, 0.13)
        self.assertTrue(none["text"].endswith(" No fire was decided; every one exited at the close."))

    def test_no_target_has_no_decided_line(self):
        v = S.verdict_history({"triggered": 45, "expectancy": ex(45, 0.1, 0.02, 0.2)}, None, 0.1)
        self.assertEqual((v["state"], v["reason"], v["decided"]), ("pass", "above", None))
        self.assertNotIn("Decided", v["text"])
        self.assertEqual(S.verdict_history({"triggered": 12, "expectancy": ex(12, 0.1, 0.02, 0.2)}, None,
                                           0.1)["reason"], "n_below_floor")

    def test_control_verdict_is_floored_on_its_sessions(self):
        d = {"delta": 0.2, "lo": 0.05, "hi": 0.35, "n_sessions": 50}
        self.assertEqual(S.verdict_control(d)["state"], "pass")
        self.assertTrue(S.verdict_control(d)["text"].endswith("the whole interval is over 0. A past sample is not a "
                                                              "forward result."))
        self.assertEqual(S.verdict_control(dict(d, n_sessions=39))["reason"], "n_below_floor")
        low = S.verdict_control({"delta": -0.293, "lo": -0.581, "hi": -0.013, "n_sessions": 33})
        self.assertEqual((low["state"], low["reason"]), ("unverified", "n_below_floor"))   # either sign
        self.assertEqual(low["text"], "Cannot judge against the random-entry control: net delta -0.293 R a trade "
                                      "(95% bootstrap [-0.581, -0.013]) over 33 paired sessions; 33 is below the "
                                      "40-session floor.")
        below = S.verdict_control(dict(d, delta=-0.2, lo=-0.3, hi=-0.01))
        self.assertEqual(below["state"], "fail")
        self.assertTrue(below["text"].endswith("the whole interval is under 0."))
        self.assertEqual(S.verdict_control(dict(d, lo=-0.1))["reason"], "straddles")
        self.assertEqual(S.verdict_control(None)["reason"], "no_control")

    def test_banned_words(self):
        for t in S.all_templates():
            self.assertEqual(S.banned_words(t), [], t)
        hist = {"target": 13, "stop": 15, "triggered": 33}
        samples = [S.verdict_history(dict(hist, expectancy=e), r, c)["text"]
                   for e, r, c in ((ex(33, -0.2, -0.5, 0.1), 1.0, 0.13), (ex(70, 0.0, -0.1, 0.1), 1.0, 0),
                                   (ex(70, -0.3, -0.4, -0.1), 2.0, 0.2), (ex(70, 0.3, 0.1, 0.4), 1.5, 0.1))]
        for t in samples:
            self.assertEqual(S.banned_words(t), [], t)
        for bad in ("Close to a coin flip", "Leans toward the target", "Strongly toward the stop",
                    "a profitable rule", "this rule has an edge", "Edge: yes"):
            self.assertTrue(S.banned_words(bad), bad)
        self.assertEqual(S.banned_words("Edge not distinguishable from zero: 45 fires"), [])


class Years(unittest.TestCase):
    def test_the_year_criterion_has_three_states(self):
        v = S.verdict_years({"2021": (39, 0.2), "2022": (10, -0.3)})
        self.assertEqual((v["state"], v["reason"], v["years"]), ("unverified", "no_year_at_floor", []))
        self.assertEqual(v["text"], "Cannot judge the years: no calendar year holds 40 fires.")
        v = S.verdict_years({"2021": (40, 0.01), "2022": (55, 0.2), "2023": (12, -0.5)})
        self.assertEqual((v["state"], v["years"]), ("pass", ["2021", "2022"]))   # a year under the floor is not read
        v = S.verdict_years({"2021": (40, 0.01), "2022": (55, 0.0)})
        self.assertEqual((v["state"], v["reason"], v["years"]), ("fail", "below", ["2022"]))
        self.assertIn("(2022)", v["text"])

    def test_the_sign_flip_note(self):
        self.assertIsNone(S.sign_flip_note({"2021": (5, 0.1), "2022": (7, 0.2), "2023": (3, 0.0)}))
        self.assertEqual(S.sign_flip_note({"2022": (7, -0.25), "2021": (5, 0.1), "2023": (2, None)}),
                         "The sign of the net average flips between years: 2021 +0.100 (n 5), 2022 -0.250 (n 7).")
        for t in (S.Y_NONE, S.Y_ABOVE, S.Y_BELOW, S.Y_FLIP):
            self.assertIn(t, S.all_templates())


class PythonEight(unittest.TestCase):
    def test_the_measurement_modules_parse_as_python_3_8(self):
        # the trader scripts (3.8 syntax) import these four on every run
        for name in ("stats", "costs", "outcomes", "control"):
            path = os.path.join(ROOT, "mjonir", name + ".py")
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8") as fh:
                src = fh.read()
            ast.parse(src, feature_version=(3, 8))
            for bad in ("zoneinfo", "from __future__ import annotations", "removeprefix", "removesuffix"):
                self.assertNotIn(bad, src, name)
            self.assertNotRegex(src, r"(?<![\w.])(list|dict|tuple|set)\[", name)
            for line in src.splitlines():
                self.assertFalse(line.strip().startswith("import ") and "mjonir" not in line
                                 and line.split()[1].split(".")[0] not in
                                 ("math", "random", "re", "statistics", "json"), line)


if __name__ == "__main__":
    unittest.main()
