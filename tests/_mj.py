"""Shared pieces for the tests/test_mjonir_*.py files: the package on sys.path, the recorded Massive
fixtures, and a fake opener that serves them by URL (no network, no key).

Fixtures in tests/fixtures/mjonir/ (recorded once from Massive on Mon 2026-11-02, 23:xx ET, market
closed, by a throwaway script that redacted the key by name and value and was deleted after):

aggs-TSLA-5m-2026-10-19.json          TSLA 5-minute aggregates of the reel's day, 04:00 to 19:55 ET
                                      (premarket and post-market rows kept: the RTH filter has work)
aggs-TSLA-5m-2025-11-28.json          the day after Thanksgiving 2025, a 1:00 p.m. early close (42 bars)
aggs-TSLA-1d-2026-07-20_2026-10-19.json  TSLA daily bars over the time machine's window
snapshot-TSLA-AAPL.json               two snapshot rows, recorded outside hours (post-market minute)
marketstatus-upcoming.json            the vendor's next holidays (2026-11-26 to 2027-09-06)
marketstatus-now.json                 the market closed
reference-tickers-page.json           one CS reference page trimmed to 30 rows, count set to 30, cursor
                                      replaced by PAGE2
grouped-2026-10-19.json               the grouped-daily answer trimmed to 30 rows (SPY and TSLA kept)
news-TSLA.json                        two Massive news rows, image fields dropped
"""

import atexit
import copy
import json
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.parse

from _load import FIX, ROOT

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
# Nothing a test does may write trader/data under the repo: the cache goes to a throwaway folder.
DATA_DIR = tempfile.mkdtemp(prefix="mjonir-tests-")
os.environ["MJONIR_DATA_DIR"] = DATA_DIR
atexit.register(shutil.rmtree, DATA_DIR, True)

from mjonir import massive as M  # noqa: E402

MFIX = os.path.join(FIX, "mjonir")
FAKE_KEY = "k3yF4keV4lue0123456789ABCDEFghij"   # 32 mixed characters, like the real one; not a key


def fixture(name):
    with open(os.path.join(MFIX, name), encoding="utf-8") as fh:
        return json.load(fh)


def http_error(url, code, headers=None):
    return urllib.error.HTTPError(url, code, "fake %d" % code, headers or {}, None)


class FakeOpener(object):
    """Serves the recorded fixtures by path; records every URL and header it was asked for."""

    def __init__(self, extra=None):
        self.calls = []
        self.headers = []
        self.extra = extra or {}

    def __call__(self, url, headers, timeout):
        self.calls.append(url)
        self.headers.append(dict(headers))
        parts = urllib.parse.urlsplit(url)
        path, q = parts.path, dict(urllib.parse.parse_qsl(parts.query))
        for prefix, fn in self.extra.items():
            if path.startswith(prefix):
                out = fn(url, path, q)
                return out if isinstance(out, bytes) else json.dumps(out).encode()
        return json.dumps(self.route(path, q, url)).encode()

    def route(self, path, q, url):
        bits = path.strip("/").split("/")
        if path.startswith("/v2/aggs/ticker/"):
            sym, mult, span, a, b = bits[3], bits[5], bits[6], bits[7], bits[8]
            if span == "day":
                doc = fixture("aggs-TSLA-1d-2026-07-20_2026-10-19.json") if sym == "TSLA" else {"status": "OK",
                                                                                                  "results": []}
                return _date_slice(doc, a, b)
            name = {("TSLA", "2026-10-19"): "aggs-TSLA-5m-2026-10-19.json",
                    ("TSLA", "2025-11-28"): "aggs-TSLA-5m-2025-11-28.json"}.get((sym, a))
            if name and a == b:
                return fixture(name)
            return {"status": "OK", "resultsCount": 0, "results": []}
        if path.startswith("/v2/aggs/grouped/"):
            if bits[-1] == "2026-10-19":
                return fixture("grouped-2026-10-19.json")
            raise http_error(url, 404)
        if path.startswith("/v2/snapshot/locale/us/markets/stocks/tickers"):
            doc = fixture("snapshot-TSLA-AAPL.json")
            want = set((q.get("tickers") or "").split(","))
            doc["tickers"] = [r for r in doc["tickers"] if r["ticker"] in want]
            doc["count"] = len(doc["tickers"])
            return doc
        if path == "/v1/marketstatus/upcoming":
            return fixture("marketstatus-upcoming.json")
        if path == "/v1/marketstatus/now":
            return fixture("marketstatus-now.json")
        if path == "/v3/reference/tickers":
            if q.get("cursor") == "PAGE2":
                return {"status": "OK", "count": 1, "results": [dict(fixture("reference-tickers-page.json")
                                                                     ["results"][0], ticker="ZZZZ", name="Page Two Inc")]}
            return fixture("reference-tickers-page.json")
        if path == "/v2/reference/news":
            return fixture("news-TSLA.json")
        if path == "/v3/reference/splits":
            return {"status": "OK", "results": []}
        raise http_error(url, 404)


def _date_slice(doc, a, b):
    """The daily fixture cut to [a, b] (New York dates), as the API would answer."""
    from mjonir import calendar as K
    doc = copy.deepcopy(doc)
    rows = [r for r in doc.get("results") or [] if a <= K.et_of_ms(r["t"]).date().isoformat() <= b]
    doc["results"] = rows
    doc["resultsCount"] = doc["queryCount"] = len(rows)
    return doc


def client(opener=None, sleep=None, **kw):
    """A Client on the fake opener, with a bucket so fast it never waits."""
    return M.Client(key=FAKE_KEY, base_url="https://api.massive.com", opener=opener or FakeOpener(),
                    sleep=sleep or (lambda s: None), pace=M.Pace(10 ** 9, sleep=lambda s: None), **kw)
