"""mjonir.outcomes: the one place outcomes are computed (chunk 2, step 2.3). Gap-through fills, the
early close scored to bar 41, both-touched, no target, the touch margins and fragile decisions."""

import os
import re
import unittest

import _mj  # noqa: F401  (sys.path, throwaway data dirs)
import synth
from _load import ROOT
from mjonir import outcomes as O


def bar(o, h, l, c):
    return {"o": o, "h": h, "l": l, "c": c}


FLAT = bar(100, 100.2, 99.8, 100)


class Touch(unittest.TestCase):
    def test_stop_first_in_one_bar(self):
        self.assertEqual(O.touch(100, 103, 97, 98, 102), ("stop", 98))                 # both touched: the stop
        self.assertEqual(O.touch(100, 103, 99, 98, 102), ("target", 102))
        self.assertIsNone(O.touch(100, 101, 99, 98, 102))
        self.assertEqual(O.touch(96, 97, 95, 98, 102), ("stop", 96))                   # gap: the open
        self.assertEqual(O.touch(96, 97, 95, 98, 102, gap_fill="stop"), ("stop", 98))  # upstream's -1R
        self.assertEqual(O.touch(100, 103, 99, 98, None), None)                         # no target
        self.assertEqual(O.touch(100, 103, 97, 102, 98, long=False), ("stop", 102))    # a sell mirrors
        self.assertEqual(O.touch(104, 105, 101, 102, 98, long=False), ("stop", 104))
        self.assertEqual(O.touch(100, 101, 97, 102, 98, long=False), ("target", 98))


class Score(unittest.TestCase):
    def test_target(self):
        bars = [FLAT, FLAT, bar(100, 101, 99.9, 100.5), bar(100.5, 102.3, 100.4, 102)]
        r = O.score_trade(bars, 0, 100.0, 98.0, 102.0, 3, cost_r=0.1)
        self.assertEqual((r["outcome"], r["exit_bar"], r["exit_price"]), ("target", 3, 102.0))
        self.assertEqual(r["gross_r"], 1.0)
        self.assertAlmostEqual(r["net_r"], 0.9)
        self.assertAlmostEqual(r["margin_target"], 0.3)
        self.assertAlmostEqual(r["decision_margin_r"], 0.15)
        self.assertFalse(r["fragile"])
        self.assertAlmostEqual(r["mfe_r"], 1.15)
        self.assertAlmostEqual(r["mae_r"], -0.1)

    def test_a_gap_through_the_stop_fills_at_the_open(self):
        s = synth.make_session("2026-10-19", 1, gap_at=20)
        e = s[10]["c"]
        stop = min([b["l"] for b in s[11:20]] + [e]) - 0.01          # untouched before the gap
        target = max(b["h"] for b in s[11:20]) + 1.0
        self.assertLess(s[20]["o"], stop)
        r = O.score_trade(s, 10, e, stop, target, 77)
        self.assertEqual((r["outcome"], r["exit_bar"], r["gap"]), ("stop", 20, True))
        self.assertEqual(r["exit_price"], s[20]["o"])
        self.assertLess(r["gross_r"], -1.0)
        up = O.score_trade(s, 10, e, stop, target, 77, gap_fill="stop")
        self.assertEqual((up["gross_r"], up["gap"]), (-1.0, False))

    def test_both_touched_is_the_stop(self):
        s = synth.make_session("2026-10-19", 2, both_touch_at=30)
        e = s[29]["c"]
        r = O.score_trade(s, 29, e, e * 0.99, e * 1.01, 77)
        self.assertEqual((r["outcome"], r["exit_bar"]), ("stop", 30))
        self.assertEqual(r["gross_r"], -1.0)

    def test_no_target_is_stop_or_close(self):
        s = synth.make_session("2026-10-19", 3)
        e = s[5]["c"]
        r = O.score_trade(s, 5, e, e * 0.5, None, 77)
        self.assertEqual((r["outcome"], r["exit_bar"], r["exit_price"]), ("close", 77, s[77]["c"]))
        self.assertIsNone(r["margin_target"])
        self.assertIsNone(r["decision_margin_r"])
        self.assertFalse(r["fragile"])
        self.assertAlmostEqual(r["gross_r"], (s[77]["c"] - e) / (e * 0.5))
        self.assertEqual(O.score_trade(s, 5, e, e * 0.5, None, 77, fill=123.0)["exit_price"], 123.0)

    def test_an_early_close_is_scored_to_bar_41(self):
        s = synth.make_session("2026-11-27", 4, early_close=True)
        self.assertEqual(len(s), 42)
        e = s[8]["c"]
        r = O.score_trade(s, 8, e, e * 0.5, e * 2, 41)
        self.assertEqual((r["outcome"], r["exit_bar"], r["exit_price"]), ("close", 41, s[41]["c"]))
        with self.assertRaises(ValueError):
            O.score_trade(s, 8, e, e * 0.5, e * 2, 77)                  # bar 77 does not exist on a half day

    def test_fragile_decisions(self):
        bars = [FLAT, bar(100, 102.04, 99.5, 101)]
        r = O.score_trade(bars, 0, 100.0, 98.0, 102.0, 1)
        self.assertEqual(r["outcome"], "target")
        self.assertAlmostEqual(r["decision_margin_r"], 0.02)
        self.assertTrue(r["fragile"])
        r = O.score_trade([FLAT, bar(100, 100.5, 97.95, 98.5)], 0, 100.0, 98.0, 102.0, 1)
        self.assertEqual(r["outcome"], "stop")
        self.assertAlmostEqual(r["margin_stop"], 0.05)
        self.assertTrue(r["fragile"])
        self.assertAlmostEqual(r["margin_target_r"], -0.75)

    def test_tuples_from_bars_5m_and_a_sell(self):
        s = synth.as_tuples(synth.make_session("2026-10-19", 5))
        e = s[6][4]
        a = O.score_trade(s, 6, e, e * 1.004, e * 0.996, 77, long=False)
        self.assertIn(a["outcome"], ("target", "stop", "close"))
        d = [{"o": t[1], "h": t[2], "l": t[3], "c": t[4]} for t in s]
        self.assertEqual(a, O.score_trade(d, 6, e, e * 1.004, e * 0.996, 77, long=False))

    def test_refusals(self):
        with self.assertRaises(ValueError):
            O.score_trade([], 0, 100, 98, 102, 0)                       # P10
        with self.assertRaises(ValueError):
            O.score_trade([FLAT, FLAT], 0, 100, 101, 102, 1)            # stop above a long's entry
        with self.assertRaises(ValueError):
            O.score_trade([FLAT, FLAT], 0, 100, 98, 102, 1, gap_fill="worst")
        r = O.score_trade([FLAT], 0, 100.0, 98.0, 102.0, 0)            # entered on the last bar
        self.assertEqual((r["outcome"], r["gross_r"]), ("close", 0.0))


class OnePlace(unittest.TestCase):
    def test_no_other_outcome_comparison(self):
        # the review's grep: nothing compares a price with the stop or the target outside outcomes.py
        pat = re.compile(r">= target|<= stop|>= tgt|<= stp")
        hits = []
        for folder in [d for d in os.listdir(ROOT) if d.startswith("trader-")] + ["mjonir"]:
            for f in os.listdir(os.path.join(ROOT, folder)):
                if f.endswith(".py") and not (folder == "mjonir" and f == "outcomes.py"):
                    with open(os.path.join(ROOT, folder, f), encoding="utf-8") as fh:
                        for n, line in enumerate(fh, 1):
                            if pat.search(line):
                                hits.append("%s/%s:%d" % (folder, f, n))
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
