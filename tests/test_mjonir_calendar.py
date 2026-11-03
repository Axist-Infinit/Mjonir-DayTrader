"""mjonir.calendar: the one clock across the DST boundaries and the Mountain box, the NYSE rules
against upstream's seeds, sessions and bar counts (78 and 42), and the vendor calendar document."""

import datetime as dt
import json
import os
import tempfile
import unittest

import _mj
from mjonir import calendar as K

D = dt.date


class Clock(unittest.TestCase):
    def test_today_et_across_the_fall_back(self):
        # 2026-11-01: 02:00 EDT becomes 01:00 EST at 06:00 UTC
        a = K.now_et("2026-11-01T05:59:00Z")
        b = K.now_et("2026-11-01T06:00:00Z")
        self.assertEqual((a.hour, a.minute, a.tzname()), (1, 59, "EDT"))
        self.assertEqual((b.hour, b.minute, b.tzname()), (1, 0, "EST"))
        self.assertEqual(K.today_et("2026-11-01T05:59:00Z"), D(2026, 11, 1))
        # the Mountain box's two bad hours: 22:30 MST on Nov 2 is 00:30 EST on Nov 3
        self.assertEqual(K.today_et("2026-11-03T05:30:00Z"), D(2026, 11, 3))
        self.assertEqual(K.today_et("2026-11-03T04:59:00Z"), D(2026, 11, 2))

    def test_today_et_across_the_spring_forward(self):
        # 2026-03-08: 02:00 EST becomes 03:00 EDT at 07:00 UTC
        self.assertEqual(K.now_et("2026-03-08T06:59:00Z").strftime("%H:%M %Z"), "01:59 EST")
        self.assertEqual(K.now_et("2026-03-08T07:00:00Z").strftime("%H:%M %Z"), "03:00 EDT")
        self.assertEqual(K.today_et("2026-03-09T03:59:00Z"), D(2026, 3, 8))
        self.assertEqual(K.today_et("2026-03-09T04:00:00Z"), D(2026, 3, 9))

    def test_now_is_parsed_like_upstream(self):
        self.assertEqual(K.parse_now("2026-10-19 10:15").isoformat(), "2026-10-19T10:15:00-04:00")
        self.assertEqual(K.parse_now("2026-12-01 10:15").isoformat(), "2026-12-01T10:15:00-05:00")
        self.assertEqual(K.parse_now("2026-10-19T14:15:00Z").isoformat(), "2026-10-19T10:15:00-04:00")
        self.assertEqual(K.parse_now("2026-10-19 10:15 ET").hour, 10)
        self.assertEqual(K.parse_now("9:45", clock="2026-10-19 08:00").isoformat(), "2026-10-19T09:45:00-04:00")
        with self.assertRaises(K.CalendarError):
            K.parse_now("tomorrow-ish")
        self.assertEqual(K.now_et(dt.datetime(2026, 10, 19, 10, 15)).utcoffset(), dt.timedelta(hours=-4))
        self.assertEqual(K.now_et(lambda: dt.datetime(2026, 10, 19, 14, 15, tzinfo=K.UTC)).hour, 10)
        real = K.now_et()
        self.assertEqual(real.tzinfo, K.ET)

    def test_ms_and_labels(self):
        t = K.ms_of(K.parse_now("2026-10-19 09:30"))
        self.assertEqual(t, 1792416600000)          # upstream's OPEN_TS, in ms
        self.assertEqual(K.et_of_ms(t).strftime("%Y-%m-%d %H:%M"), "2026-10-19 09:30")
        self.assertEqual(K.tz_label("2026-10-19"), ("EDT", -14400))
        self.assertEqual(K.tz_label("2026-11-27"), ("EST", -18000))


class Rules(unittest.TestCase):
    def test_rules_reproduce_upstreams_seed_lists(self):
        for y in (2026, 2027):
            self.assertEqual(sorted(K.rule_holidays(y)), sorted(k for k in K.SEED_HOLIDAYS if k.startswith(str(y))))
            self.assertEqual(sorted(K.rule_early_closes(y)),
                             sorted(k for k in K.SEED_EARLY_CLOSE if k.startswith(str(y))))

    def test_past_years(self):
        h = K.rule_holidays(2025)
        for d in ("2025-01-01", "2025-01-09", "2025-04-18", "2025-06-19", "2025-11-27", "2025-12-25"):
            self.assertIn(d, h)
        self.assertEqual(sorted(K.rule_early_closes(2025)), ["2025-07-03", "2025-11-28", "2025-12-24"])
        self.assertNotIn("2021-06-18", K.rule_holidays(2021))            # Juneteenth starts in 2022
        self.assertIn("2022-06-20", K.rule_holidays(2022))               # observed on the Monday
        self.assertIn("2021-12-24", K.rule_holidays(2021))               # Christmas on a Saturday
        self.assertNotIn("2021-12-31", K.rule_holidays(2021))            # New Year's on a Saturday: not observed
        self.assertNotIn("2021-12-24", K.rule_early_closes(2021))        # a holiday, not an early close
        self.assertEqual(K.easter(2026), D(2026, 4, 5))
        self.assertEqual(K.easter(2019), D(2019, 4, 21))
        self.assertIn("2028-07-03", K.rule_early_closes(2028))


class Sessions(unittest.TestCase):
    def setUp(self):
        self.cal = K.Calendar()

    def test_is_session_and_why(self):
        c = self.cal
        self.assertTrue(c.is_session("2026-10-19"))
        self.assertEqual(c.why_closed("2026-10-18"), "weekend")
        self.assertEqual(c.why_closed("2026-11-26"), "NYSE holiday: Thanksgiving Day")
        self.assertEqual(c.why_closed("2025-11-27"), "NYSE holiday: Thanksgiving Day")     # a rule year
        self.assertFalse(c.is_session("2025-01-09"))
        self.assertTrue(c.is_session(dt.datetime(2026, 10, 19, 12, 0, tzinfo=K.ET)))

    def test_expected_bars_78_and_42(self):
        c = self.cal
        self.assertEqual(c.expected_bars("2026-10-19"), 78)
        self.assertEqual(c.expected_bars("2026-11-27"), 42)
        self.assertEqual(c.expected_bars("2025-11-28"), 42)
        self.assertEqual(c.expected_bars("2025-11-28", 1), 210)
        self.assertEqual(c.expected_bars("2026-10-19", 1), 390)
        with self.assertRaises(K.CalendarError):
            c.expected_bars("2026-11-26")
        o, cl = c.session_bounds("2026-11-27")
        self.assertEqual((o.strftime("%H:%M"), cl.strftime("%H:%M")), ("09:30", "13:00"))
        self.assertIsNone(c.session_bounds("2026-10-18"))

    def test_early_close_basis(self):
        c = self.cal
        self.assertEqual(c.early_close_basis("2026-11-27"), "calendar")
        self.assertEqual(c.early_close_basis("2025-11-28", 42), "verified")
        self.assertEqual(c.early_close_basis("2025-11-28"), "rule_only")
        self.assertEqual(c.early_close_basis("2025-11-28", 78), "contradicted")
        self.assertIsNone(c.early_close_basis("2026-10-19", 78))
        self.assertEqual(c.early_close_label("2025-11-28"), "day after Thanksgiving")

    def test_ranges(self):
        c = self.cal
        self.assertEqual(c.sessions_between("2026-11-25", "2026-11-30"),
                         [D(2026, 11, 25), D(2026, 11, 27), D(2026, 11, 30)])
        self.assertEqual(c.prev_session("2026-10-19"), D(2026, 10, 16))
        self.assertEqual(c.next_session("2026-11-25"), D(2026, 11, 27))
        self.assertEqual(c.sessions_back("2026-10-19", 3), [D(2026, 10, 15), D(2026, 10, 16), D(2026, 10, 19)])
        self.assertEqual(c.sessions_back("2026-10-18", 2), [D(2026, 10, 15), D(2026, 10, 16)])
        win = c.sessions_back("2026-10-19", 60)
        self.assertEqual((win[0], len(win)), (D(2026, 7, 27), 60))   # upstream's 60d fixture starts here
        self.assertEqual(c.last_complete_session("2026-10-19 15:59"), D(2026, 10, 16))
        self.assertEqual(c.last_complete_session("2026-10-19 16:00"), D(2026, 10, 19))
        self.assertEqual(c.last_complete_session("2026-11-26 12:00"), D(2026, 11, 25))
        self.assertTrue(c.session_complete("2026-10-19", "2026-10-20 00:01"))
        self.assertFalse(c.session_complete("2026-10-19", "2026-10-19 23:59"))

    def test_rth_filter(self):
        rows = _mj.fixture("aggs-TSLA-5m-2026-10-19.json")["results"]
        rth = self.cal.rth_filter(rows)
        self.assertEqual((len(rows), len(rth)), (192, 78))
        self.assertEqual(K.et_of_ms(rth[0]["t"]).strftime("%H:%M"), "09:30")
        self.assertEqual(K.et_of_ms(rth[-1]["t"]).strftime("%H:%M"), "15:55")
        early = self.cal.rth_filter(_mj.fixture("aggs-TSLA-5m-2025-11-28.json")["results"])
        self.assertEqual(len(early), 42)
        self.assertEqual(K.et_of_ms(early[-1]["t"]).strftime("%H:%M"), "12:55")


class VendorCalendar(unittest.TestCase):
    def test_build_and_load(self):
        doc = K.build_calendar_doc(_mj.client(), clock="2026-11-02 23:00")
        self.assertEqual(doc["covered_years"], [2026, 2027, 2028])
        self.assertEqual(doc["basis"], {"2026": "seed+vendor", "2027": "seed+vendor", "2028": "rule"})
        self.assertEqual(doc["known_through"], "2027-09-06")
        self.assertEqual(doc["early_closes"]["2026-11-27"], "Thanksgiving")       # the vendor's own name
        self.assertIn("2028-11-23", doc["holidays"])
        self.assertIn("2028-07-03", doc["early_closes"])
        self.assertEqual(doc["market_now"]["market"], "closed")
        d = tempfile.mkdtemp()
        p = os.path.join(d, "calendar.json")
        with open(p, "w") as fh:
            json.dump(doc, fh)
        cal = K.Calendar.load(p)
        self.assertFalse(cal.is_session("2028-11-23"))
        self.assertEqual(cal.expected_bars("2028-11-24"), 42)
        self.assertEqual(cal.early_close_basis("2028-11-24"), "calendar")
        # TRADER_CALENDAR picks the file; a missing or broken file keeps the seeds
        old = os.environ["TRADER_CALENDAR"]
        try:
            os.environ["TRADER_CALENDAR"] = p
            self.assertIn(2028, K.Calendar.load().covered_years)
            os.environ["TRADER_CALENDAR"] = os.path.join(d, "nope.json")
            self.assertEqual(K.Calendar.load().covered_years, set(K.SEED_YEARS))
        finally:
            os.environ["TRADER_CALENDAR"] = old

    def test_an_empty_vendor_answer_is_refused(self):
        from mjonir import massive as M
        op = _mj.FakeOpener(extra={"/v1/marketstatus/upcoming": lambda url, path, q: []})
        with self.assertRaises(M.Refused):
            K.build_calendar_doc(_mj.client(op))


if __name__ == "__main__":
    unittest.main()
