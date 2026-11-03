"""mjonir.universe: the funnel (ticker rule, a print, price floor, ADV$ floor) and its refusals,
on the recorded grouped-daily answer and synthetic reference pages. Output read back by scan.py."""

import copy
import json
import os
import tempfile
import unittest

import _mj
from _load import load
from mjonir import calendar as K
from mjonir import config as C
from mjonir import massive as M
from mjonir import universe as U

scan = load("trader-scanner", "scan")
CAL = K.Calendar()
GROUPED = _mj.fixture("grouped-2026-10-19.json")
REF_ROW = _mj.fixture("reference-tickers-page.json")["results"][0]


def ref_page(tickers, ty, next_url=None):
    rows = [dict(REF_ROW, ticker=t, name="%s Corp" % t, type=ty) for t in tickers]
    p = {"status": "OK", "count": len(rows), "results": rows}
    if next_url:
        p["next_url"] = next_url
    return p


def grouped_for(day, drop=(), scale=1.0):
    """The recorded 2026-10-19 answer moved to another session (prices scaled), some tickers dropped."""
    g = copy.deepcopy(GROUPED)
    t = K.ms_of(K.parse_now("%s 00:00" % day)) - K.ms_of(K.parse_now("2026-10-19 00:00"))
    g["results"] = [dict(r, t=r["t"] + t, c=r["c"] * scale) for r in g["results"] if r["T"] not in drop]
    g["resultsCount"] = g["count"] = g["queryCount"] = len(g["results"])
    return g


class World(object):
    """A fake API: CS and ADRC reference walks, grouped answers for 2026-10-16 and 2026-10-19."""

    def __init__(self, cs=None, adrc=None, g16=None, g19=None):
        self.cs = cs or [ref_page(["AAPL", "TSLA", "AMC", "PLXS", "SLAB", "NVDA"], "CS", "https://api.massive.com/"
                                  "v3/reference/tickers?cursor=CS2"),
                         ref_page(["MVST", "GDRX", "BRK.B", "BCpC", "TOOLONG"], "CS")]
        self.adrc = adrc or [ref_page(["SVIA"], "ADRC")]
        self.g = {"2026-10-16": g16 or grouped_for("2026-10-16", drop=("PLXS",)),
                  "2026-10-19": g19 or GROUPED}

    def opener(self):
        def reference(url, path, q):
            if q.get("cursor") == "CS2":
                return self.cs[1]
            return self.cs[0] if q.get("type") == "CS" else self.adrc[0]

        def grouped(url, path, q):
            day = path.rsplit("/", 1)[-1]
            if day not in self.g:
                raise _mj.http_error(url, 404)
            return self.g[day]
        return _mj.FakeOpener(extra={"/v3/reference/tickers": reference, "/v2/aggs/grouped/": grouped})

    def build(self, **kw):
        args = dict(as_of="2026-10-19", min_price=5, min_adv_usd=20e6, sessions=2, min_rows={"CS": 3, "ADRC": 1})
        args.update(kw)
        return U.build(_mj.client(self.opener()), CAL, **args)


class Funnel(unittest.TestCase):
    def test_the_funnel(self):
        res = World().build()
        kept = [s for s, _ in res["kept"]]
        # AMC under $5; MVST and GDRX under $5 too; SVIA (ADRC) under $5; PLXS missed 10-16 so its ADV
        # halves to ~$26M and still clears; BRK.B has no print; BCpC and TOOLONG are not plain tickers
        self.assertEqual(kept, ["AAPL", "NVDA", "PLXS", "SLAB", "TSLA"])
        c = res["counts"]
        self.assertEqual((c["rows"], c["not a plain ticker"], c["no print on 2026-10-19"], c["price under $5"],
                          c["ADV$ under $20M"], c["keep"]), (12, 2, 1, 4, 0, 5))
        rec = res["record"]
        self.assertEqual(rec["names"]["PLXS"]["sessions_present"], 1)
        self.assertEqual(rec["window"], {"from": "2026-10-16", "to": "2026-10-19",
                                         "grouped_rows": {"2026-10-16": 29, "2026-10-19": 30}})
        self.assertEqual([w["type"] for w in rec["reference_walks"]], ["CS", "ADRC"])
        self.assertEqual(rec["rule"]["min_adv_usd"], 20e6)

    def test_the_adv_floor_counts_missing_days_as_zero(self):
        res = World().build(min_adv_usd=40e6)          # PLXS: 51.6M on one of two days = 25.8M
        self.assertNotIn("PLXS", [s for s, _ in res["kept"]])
        self.assertEqual(res["counts"]["ADV$ under $40M"], 1)

    def test_output_is_what_scan_reads(self):
        res = World().build()
        d = tempfile.mkdtemp()
        out, rec = U.write(res, os.path.join(d, "universe.txt"), os.path.join(d, "u"))
        self.assertEqual(scan.symbols_from_file(out), ["AAPL", "NVDA", "PLXS", "SLAB", "TSLA"])
        with open(out) as fh:
            self.assertEqual(fh.readline(), "AAPL|AAPL Corp\n")
        with open(rec) as fh:
            self.assertEqual(json.load(fh)["kept"], 5)
        self.assertTrue(rec.endswith("2026-10-19.json"))

    def test_floors_from_the_config(self):
        self.assertEqual(U.floors({}), (5.0, 20000000.0))
        self.assertEqual(U.floors({"universe": {"min_price": 10, "min_adv_usd": 5e7}}), (10.0, 5e7))
        d = tempfile.mkdtemp()
        p = os.path.join(d, "config.json")
        with open(p, "w") as fh:
            json.dump({"universe": {"min_price": 7}}, fh)
        self.assertEqual(U.floors(C.trader_config(p)), (7.0, 20000000.0))


class Refusals(unittest.TestCase):
    def assertRefused(self, world, words, **kw):
        with self.assertRaises(M.Refused) as cm:
            world.build(**kw)
        self.assertIn(words, str(cm.exception))

    def test_a_reference_walk_that_paginated_short(self):
        w = World()
        w.cs[1] = dict(w.cs[1], next_url="https://api.massive.com/v3/reference/tickers?cursor=CS2")
        with self.assertRaises(M.Refused):    # the cursor loops back to page 2: still paging at 50
            w.build()

    def test_a_reference_count_mismatch(self):
        w = World()
        w.cs[0] = dict(w.cs[0], count=99)
        self.assertRefused(w, "count 99")

    def test_the_type_filter_ignored(self):
        w = World(adrc=[ref_page(["SVIA"], "CS")])
        self.assertRefused(w, "asked for ADRC")

    def test_a_walk_under_its_sanity_floor(self):
        self.assertRefused(World(), "sanity floor", min_rows={"CS": 5000, "ADRC": 1})

    def test_a_partial_grouped_day(self):
        g16 = grouped_for("2026-10-16", drop=[r["T"] for r in GROUPED["results"][15:]])
        self.assertRefused(World(g16=g16), "partial answer")

    def test_a_grouped_day_without_spy(self):
        self.assertRefused(World(g16=grouped_for("2026-10-16", drop=("SPY",))), "no SPY print")

    def test_a_grouped_day_with_a_cursor(self):
        self.assertRefused(World(g16=dict(grouped_for("2026-10-16"), next_url="https://api.massive.com/x")),
                           "next_url")

    def test_not_a_session_and_nothing_cleared(self):
        self.assertRefused(World(), "not a session", as_of="2026-10-18")
        self.assertRefused(World(), "nothing cleared", min_price=10000)


if __name__ == "__main__":
    unittest.main()
