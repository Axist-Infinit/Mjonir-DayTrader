"""mjonir.massive: the client on an injected opener (no network). Limits, paging refusals, retries,
the three probe outcomes, redaction, the not-entitled guard, pacing, and the snapshot units."""

import http.client
import json
import unittest
import urllib.error
import urllib.parse

import _mj
from mjonir import massive as M

KEY = _mj.FAKE_KEY


def page(results, next_url=None, status="OK", **extra):
    d = {"status": status, "resultsCount": len(results), "results": results}
    if next_url:
        d["next_url"] = next_url
    d.update(extra)
    return d


class Transport(unittest.TestCase):
    def test_every_aggs_url_sends_the_max_limit_and_asc(self):
        op = _mj.FakeOpener()
        c = _mj.client(op)
        rows = c.aggregates("TSLA", 5, "minute", "2026-10-19", "2026-10-19")
        c.aggregates("TSLA", 1, "day", "2026-07-20", "2026-10-19")
        c.aggregates("BRK.B", 5, "minute", "2026-10-19", "2026-10-19")
        self.assertEqual(len(rows), 192)
        self.assertEqual([r["t"] for r in rows], sorted(r["t"] for r in rows))
        self.assertEqual(set(rows[0]), {"t", "o", "h", "l", "c", "v", "vw", "n"})
        for url in op.calls:
            q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
            self.assertEqual((q["limit"], q["sort"], q["adjusted"]), ("50000", "asc", "true"), url)
        self.assertIn("/v2/aggs/ticker/BRK.B/range/5/minute/", op.calls[-1])

    def test_the_key_rides_in_a_header_never_in_a_url(self):
        op = _mj.FakeOpener()
        c = _mj.client(op)
        c.snapshot(["TSLA"])
        c.market_status_now()
        self.assertTrue(all(KEY not in u and "apiKey" not in u for u in op.calls))
        self.assertTrue(all(h["Authorization"] == "Bearer " + KEY for h in op.headers))
        self.assertNotIn(KEY, repr(c))

    def test_next_url_walk_is_refused_at_page_50(self):
        n = []

        def endless(url, headers, timeout):
            n.append(url)
            return json.dumps(page([{"t": len(n), "o": 1, "h": 1, "l": 1, "c": 1, "v": 1}],
                                   "https://api.massive.com/v2/next?cursor=%d" % len(n))).encode()
        c = _mj.client(endless)
        with self.assertRaises(M.Refused) as cm:
            c.aggregates("TSLA", 5, "minute", "2026-10-19", "2026-10-19")
        self.assertEqual(len(n), M.MAX_PAGES)
        self.assertIn("still paging after 50 pages", str(cm.exception))
        self.assertEqual(cm.exception.outcome, "refused")

    def test_a_cursor_to_another_host_is_not_followed(self):
        def other(url, headers, timeout):
            return json.dumps(page([], "https://evil.example/v2/x?cursor=1")).encode()
        with self.assertRaises(M.Refused):
            list(_mj.client(other).pages("/v2/x", {}))

    def test_counts_and_status_are_checked(self):
        def short(url, headers, timeout):
            return json.dumps({"status": "OK", "resultsCount": 3, "results": [{"t": 1, "o": 1, "h": 1, "l": 1,
                                                                               "c": 1, "v": 1}]}).encode()
        with self.assertRaises(M.Refused) as cm:
            _mj.client(short).aggregates("TSLA", 5, "minute", "2026-10-19", "2026-10-19")
        self.assertIn("resultsCount 3 but 1", str(cm.exception))

        def bad(url, headers, timeout):
            return json.dumps({"status": "ERROR", "error": "nope"}).encode()
        with self.assertRaises(M.Refused):
            _mj.client(bad).aggregates("TSLA", 5, "minute", "2026-10-19", "2026-10-19")

    def test_429_then_200_waits_once(self):
        sleeps, n = [], []

        def flaky(url, headers, timeout):
            n.append(url)
            if len(n) == 1:
                raise _mj.http_error(url, 429, {"Retry-After": "2"})
            return json.dumps({"market": "open"}).encode()
        c = _mj.client(flaky, sleep=sleeps.append)
        self.assertEqual(c.market_status_now(), {"market": "open"})
        self.assertEqual(sleeps, [2.0])
        self.assertEqual(len(n), 2)

    def test_5xx_retries_then_gives_up_unverified(self):
        sleeps = []

        def down(url, headers, timeout):
            raise _mj.http_error(url, 503)
        with self.assertRaises(M.MassiveError) as cm:
            _mj.client(down, sleep=sleeps.append).market_status_now()
        self.assertEqual(cm.exception.status, 503)
        self.assertEqual(cm.exception.outcome, "unverified")
        self.assertEqual(len(sleeps), 2)

    def test_401_and_403_are_rejections_not_retried(self):
        for code in (401, 403):
            calls = []

            def no(url, headers, timeout):
                calls.append(url)
                raise _mj.http_error(url, code)
            with self.assertRaises(M.MassiveError) as cm:
                _mj.client(no).market_status_now()
            self.assertEqual((cm.exception.status, cm.exception.outcome, len(calls)), (code, "refused", 1))
            self.assertEqual(_mj.client(no).probe()["outcome"], "rejected")

    def test_unreachable_is_unverified(self):
        def gone(url, headers, timeout):
            raise urllib.error.URLError("Name or service not known")
        with self.assertRaises(M.MassiveError) as cm:
            _mj.client(gone).market_status_now()
        self.assertEqual(cm.exception.outcome, "unverified")
        self.assertIsNone(cm.exception.status)
        self.assertEqual(_mj.client(gone).probe()["outcome"], "unverified")
        self.assertEqual(_mj.client().probe()["outcome"], "authenticated")

    def test_a_symbol_with_a_space_never_leaks_the_key(self):
        def leaky(url, headers, timeout):
            # what http.client does with a space: quote the whole request back, credentials and all
            raise http.client.InvalidURL("URL can't contain control characters. %r ?apiKey=%s %s"
                                         % (url, KEY, headers.get("Authorization")))
        with self.assertRaises(M.MassiveError) as cm:
            _mj.client(leaky).get("/v2/aggs/ticker/NOPE NOPE/range/5/minute/2026-10-19/2026-10-19")
        msg = str(cm.exception)
        self.assertFalse(KEY in msg, "the key leaked into the message")
        self.assertIn("InvalidURL", msg)
        self.assertIn("<redacted>", msg)
        # the real urllib on a space: refused before any connection (a local address all the same)
        c = M.Client(key=KEY, base_url="https://127.0.0.1:9", pace=M.Pace(10 ** 9), sleep=lambda s: None,
                     max_retries=1)
        with self.assertRaises(M.MassiveError) as cm:
            c.get("/v2/aggs/ticker/NOPE NOPE/range/5/minute/2026-10-19/2026-10-19")
        self.assertFalse(KEY in str(cm.exception))
        # and aggregates() quotes the symbol, so the URL is well formed
        op = _mj.FakeOpener()
        _mj.client(op).aggregates("NOPE NOPE", 5, "minute", "2026-10-19", "2026-10-19")
        self.assertIn("/NOPE%20NOPE/", op.calls[0])

    def test_no_key_no_client(self):
        import os
        saved = {k: os.environ.pop(k) for k in list(os.environ) if k in M.C.KEY_NAMES or k == "INFINIT_ROOT"}
        os.environ["INFINIT_ROOT"] = "/nonexistent-mjonir-test"
        try:
            if M.C.api_key() is None:
                with self.assertRaises(M.MassiveError) as cm:
                    M.Client()
                self.assertIn("~/Infinit/.env", str(cm.exception))
        finally:
            os.environ.pop("INFINIT_ROOT")
            os.environ.update(saved)


class NotEntitled(unittest.TestCase):
    def test_options_indices_benzinga_are_never_tried(self):
        op = _mj.FakeOpener()
        c = _mj.client(op)
        for call in (lambda: c.get("/v3/snapshot/options/AAPL"),
                     lambda: c.get("/v3/reference/options/contracts", {"underlying_ticker": "AAPL"}),
                     lambda: c.get("/benzinga/v1/earnings"),
                     lambda: c.aggregates("I:SPX", 1, "day", "2026-10-01", "2026-10-19"),
                     lambda: c.aggregates("O:TSLA261120C00400000", 1, "day", "2026-10-01", "2026-10-19"),
                     lambda: c.snapshot(["TSLA", "I:NDX"])):
            with self.assertRaises(M.NotEntitled):
                call()
        self.assertEqual(op.calls, [])
        self.assertEqual(c.aggregates("O", 1, "day", "2026-10-19", "2026-10-19"), [])   # Realty Income is fine


class Pacing(unittest.TestCase):
    def test_token_bucket(self):
        t = [0.0]
        slept = []

        def sleep(s):
            slept.append(round(s, 6))
            t[0] += s
        p = M.Pace(60, clock=lambda: t[0], sleep=sleep, burst=2)
        for _ in range(4):
            p.take()
        self.assertEqual(slept, [1.0, 1.0])        # 2 free, then one a second
        self.assertEqual(M.Pace(1200).capacity, 20.0)
        with self.assertRaises(ValueError):
            M.Pace(0)

    def test_snapshot_chunks_of_200(self):
        op = _mj.FakeOpener()
        _mj.client(op).snapshot(["S%d" % i for i in range(450)] + ["TSLA"])
        self.assertEqual(len(op.calls), 3)
        sizes = [len(dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(u).query))["tickers"].split(","))
                 for u in op.calls]
        self.assertEqual(sizes, [200, 200, 51])


class Shapes(unittest.TestCase):
    def test_snapshot_units_on_the_recorded_fixture(self):
        rows = {r["ticker"]: r for r in _mj.fixture("snapshot-TSLA-AAPL.json")["tickers"]}
        t = M.snapshot_times(rows["TSLA"])
        self.assertEqual(t["units"], {"min.t": "ms", "lastTrade.t": "ns", "lastQuote.t": "ns", "updated": "ns"})
        self.assertEqual(t["surprises"], [])
        self.assertEqual(t["min_t_ms"], rows["TSLA"]["min"]["t"])
        self.assertEqual(t["last_trade_ms"], rows["TSLA"]["lastTrade"]["t"] // 1000000)
        # all four within the same two minutes once converted (the hazard is a factor of 10^6)
        self.assertLess(max(v for k, v in t.items() if k.endswith("_ms")) -
                        min(v for k, v in t.items() if k.endswith("_ms")), 120000)
        odd = dict(rows["TSLA"], min=dict(rows["TSLA"]["min"], t=rows["TSLA"]["min"]["t"] * 1000000))
        self.assertEqual(M.snapshot_times(odd)["surprises"], ["min.t is ns, documented ms"])
        self.assertEqual(M.snapshot_times(odd)["min_t_ms"], rows["TSLA"]["min"]["t"])
        self.assertIsNone(M.snapshot_times({})["last_trade_ms"])

    def test_quote_none_when_it_cannot_ask(self):
        def nbbo(url, headers, timeout):
            return json.dumps({"status": "OK", "results": {"p": 403.75, "P": 404.38, "t": 1793667598035312045}}).encode()
        self.assertEqual(_mj.client(nbbo).quote("TSLA"), {"bid": 403.75, "ask": 404.38, "t_ms": 1793667598035})

        def down(url, headers, timeout):
            raise urllib.error.URLError("down")
        self.assertIsNone(_mj.client(down).quote("TSLA"))

        def empty(url, headers, timeout):
            return json.dumps({"status": "OK", "results": {"p": 0, "P": 404.38, "t": 1}}).encode()
        self.assertIsNone(_mj.client(empty).quote("TSLA"))   # a zero bid is no quote, never 0

    def test_grouped_refusals(self):
        good = _mj.fixture("grouped-2026-10-19.json")
        rows = M.check_grouped("2026-10-19", good)
        self.assertIn("SPY", rows)
        self.assertEqual(set(rows["TSLA"]), {"t", "o", "h", "l", "c", "v", "vw", "n"})
        cases = [
            (dict(good, next_url="https://api.massive.com/x"), "next_url"),
            (dict(good, resultsCount=good["resultsCount"] + 1), "resultsCount"),
            (dict(good, status="ERROR"), "status"),
            (dict(good, adjusted=False), "UNADJUSTED"),
            (dict(good, results=[r for r in good["results"] if r["T"] != "SPY"],
                  resultsCount=good["resultsCount"] - 1), "no SPY"),
            (dict(good, results=good["results"] + [good["results"][0]], resultsCount=good["resultsCount"] + 1),
             "twice"),
            ("not json", "not a JSON object"),
        ]
        for payload, words in cases:
            with self.assertRaises(M.Refused) as cm:
                M.check_grouped("2026-10-19", payload)
            self.assertIn(words, str(cm.exception))
        with self.assertRaises(M.Refused) as cm:
            M.check_grouped("2026-10-20", good)
        self.assertIn("dated another day", str(cm.exception))
        self.assertIn("SPY", _mj.client().grouped_daily("2026-10-19"))

    def test_reference_refusals(self):
        p1 = _mj.fixture("reference-tickers-page.json")
        p2 = {"status": "OK", "count": 1, "results": [dict(p1["results"][0], ticker="ZZZZ")]}
        rows, meta = M.check_reference([p1, p2], want_type="CS", min_rows=5)
        self.assertEqual((meta["rows"], meta["pages"]), (31, 2))
        bad = [
            ([p1], "cursor still open"),
            ([dict(p1, count=29), p2], "count 29"),
            ([dict(p1, status="ERROR"), p2], "status"),
            ([p1, dict(p2, results=[dict(p2["results"][0], type="ETF")])], "type 'ETF'"),
            ([p1, dict(p2, results=[dict(p2["results"][0], active=False)])], "ignored the filter"),
            ([p1, dict(p2, results=[p1["results"][0]])], "listed twice"),
            ([dict(p1, results=[], count=0)], "a cursor and no rows"),
        ]
        for pages, words in bad:
            with self.assertRaises(M.Refused) as cm:
                M.check_reference(pages, want_type="CS")
            self.assertIn(words, str(cm.exception))
        with self.assertRaises(M.Refused) as cm:
            M.check_reference([p1, p2], min_rows=100)
        self.assertIn("sanity floor", str(cm.exception))
        full = {"status": "OK", "count": 2, "results": p1["results"][:2]}
        with self.assertRaises(M.Refused) as cm:
            M.check_reference([full], page_limit=2)
        self.assertIn("exactly full", str(cm.exception))
        pages = _mj.client().reference_pages({"type": "CS"})
        self.assertEqual(len(pages), 2)

    def test_news_and_splits(self):
        op = _mj.FakeOpener()
        c = _mj.client(op)
        self.assertEqual(len(c.news("TSLA", since_utc="2026-10-19T00:00:00Z", limit=5)), 2)
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(op.calls[-1]).query))
        self.assertEqual((q["ticker"], q["published_utc.gte"], q["order"]), ("TSLA", "2026-10-19T00:00:00Z", "desc"))
        self.assertEqual(c.splits("TSLA"), [])


if __name__ == "__main__":
    unittest.main()
