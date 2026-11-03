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


class Verdicts(unittest.TestCase):
    def test_the_reel_cannot_judge(self):
        v = S.verdict_history({"target": 13, "stop": 15, "triggered": 33}, 1.0, 0.13)
        self.assertEqual((v["state"], v["reason"]), ("unverified", "n_below_floor"))
        self.assertEqual(v["text"], "Cannot judge: 13 of 28 decided fires hit the target (46.4%, 95% Wilson "
                                    "[29.5%, 64.2%]); n is below the 40-fire floor. Net break-even at 1R after "
                                    "costs is 56.5%.")

    def test_the_four_classes(self):
        v = S.verdict_history({"target": 30, "stop": 30, "triggered": 70}, 1.0, 0.0)
        self.assertEqual((v["state"], v["reason"]), ("unverified", "straddles"))
        self.assertTrue(v["text"].startswith("Edge not distinguishable from break-even: 30 of 60"))
        v = S.verdict_history({"target": 10, "stop": 50, "triggered": 60}, 1.0, 0.13)
        self.assertEqual((v["state"], v["reason"]), ("fail", "below"))
        self.assertTrue(v["text"].startswith("Below break-even: 10 of 60"))
        v = S.verdict_history({"target": 50, "stop": 10, "triggered": 60}, 1.0, 0.13)
        self.assertEqual((v["state"], v["reason"]), ("pass", "above"))
        self.assertTrue(v["text"].endswith("A past sample is not a forward result."))
        v = S.verdict_history({"target": 0, "stop": 0, "triggered": 3}, 1.0, 0.13)
        self.assertEqual((v["state"], v["reason"]), ("unverified", "no_history"))
        self.assertIn("with costs off", S.verdict_history({"target": 1, "stop": 1, "triggered": 2}, 2.0, 0.0,
                                                          costs_on=False)["text"])

    def test_no_target_reads_the_net_expectancy(self):
        ex = {"n": 45, "mean": 0.1, "lo": 0.02, "hi": 0.2}
        v = S.verdict_history({"triggered": 45, "expectancy": ex}, None, 0.1)
        self.assertEqual((v["state"], v["reason"]), ("pass", "above"))
        v = S.verdict_history({"triggered": 45, "expectancy": dict(ex, lo=-0.1)}, None, 0.1)
        self.assertEqual(v["reason"], "straddles")
        v = S.verdict_history({"triggered": 45, "expectancy": dict(ex, mean=-0.2, lo=-0.3, hi=-0.1)}, None, 0.1)
        self.assertEqual((v["state"], v["reason"]), ("fail", "below"))
        v = S.verdict_history({"triggered": 12, "expectancy": dict(ex, n=12)}, None, 0.1)
        self.assertEqual(v["reason"], "n_below_floor")
        self.assertEqual(S.verdict_history({"triggered": 0, "expectancy": None}, None, 0.1)["reason"], "no_history")

    def test_control_verdict(self):
        d = {"delta": 0.2, "lo": 0.05, "hi": 0.35, "n_sessions": 50}
        self.assertEqual(S.verdict_control(d, 45)["state"], "pass")
        self.assertEqual(S.verdict_control(d, 39)["reason"], "n_below_floor")
        self.assertEqual(S.verdict_control(dict(d, delta=-0.2, lo=-0.3, hi=-0.01), 10)["state"], "fail")
        self.assertEqual(S.verdict_control(dict(d, lo=-0.1), 45)["reason"], "straddles")
        self.assertEqual(S.verdict_control(None, 45)["reason"], "no_control")

    def test_banned_words(self):
        for t in S.all_templates():
            self.assertEqual(S.banned_words(t), [], t)
        samples = [S.verdict_history({"target": k, "stop": s, "triggered": k + s + 2}, r, c)["text"]
                   for k, s, r, c in ((13, 15, 1.0, 0.13), (30, 30, 1.0, 0), (10, 50, 2.0, 0.2), (50, 10, 1.5, 0.1))]
        for t in samples:
            self.assertEqual(S.banned_words(t), [], t)
        for bad in ("Close to a coin flip", "Leans toward the target", "Strongly toward the stop",
                    "a profitable rule", "this rule has an edge", "Edge: yes"):
            self.assertTrue(S.banned_words(bad), bad)
        self.assertEqual(S.banned_words("Edge not distinguishable from zero: 45 fires"), [])


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
