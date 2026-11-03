"""Massive REST client (Polygon-compatible), ported from ~/Odyssey/odyssey/bars/massive.py. Stdlib only.

The guards are not optional:

* ``limit=50000`` and ``sort=asc`` on every aggregates request, and every page's ``resultsCount``
  checked against its rows. A short ``limit`` truncates silently under ``status: OK``.
* ``next_url`` is followed up to ``MAX_PAGES`` (50); a cursor still open past that is a REFUSAL,
  never a partial answer (P11). A cursor pointing at another host is refused too (the key would go
  with it).
* The key travels in the ``Authorization: Bearer`` header, never in a URL. Every error message still
  goes through ``config.redact`` (by name and by value): an exception that quotes a URL or a header
  must never carry the credential.
* Paced by a token bucket (default 1,200 requests a minute, shared by every client in the process);
  a 429 backs off and retries.
* Options (``/v3/snapshot/options``, ``/v3/reference/options``, ``O:`` tickers), indices (``I:``)
  and Benzinga paths are not entitled on this key: they are refused locally, never tried.

Three outcomes for a failure, never two: a REFUSAL (P11, or HTTP 401/403/404: the API answered
and the answer is no), or UNVERIFIED (the host could not be reached, timeouts, 5xx after retries).
"""

import json
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from . import config as C
from .calendar import ET

#: Polygon's documented ceiling for aggregates. Anything smaller silently truncates.
MAX_LIMIT = 50000
#: ``next_url`` hops before refusing (Odyssey audit 2.15).
MAX_PAGES = 50
RETRY_STATUS = (429, 500, 502, 503, 504)
#: Tickers per snapshot request (a comma list in the query string: the ceiling is URL length).
SNAPSHOT_CHUNK = 200
#: Statuses a complete answer carries (a delayed plan still answers a completed session whole).
OK_STATUSES = ("OK", "DELAYED")
DEFAULT_RATE = 1200
CALENDAR_SYMBOL = "SPY"

GROUPED_PATH = "/v2/aggs/grouped/locale/us/market/stocks/%s"
REFERENCE_PATH = "/v3/reference/tickers"
REFERENCE_PAGE_LIMIT = 1000
SNAPSHOT_PATH = "/v2/snapshot/locale/us/markets/stocks/tickers"

#: Paths this key is not entitled to. Refused before any request (CLAUDE.md hazard 15).
NOT_ENTITLED = ("/v3/snapshot/options", "/v3/reference/options", "/v3/snapshot/indices",
                "/benzinga", "/options/")
NOT_ENTITLED_WORDS = "options, indices (I:) and Benzinga are not entitled on this key: never tried"


class MassiveError(RuntimeError):
    """A market-data failure. ``status`` carries the HTTP code when there was one, so a REJECTED
    key (401/403) is never reported as an unreachable host, or the other way round."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status

    @property
    def outcome(self):
        """'refused' (the API answered no) or 'unverified' (nothing was learned)."""
        if self.status is not None and 400 <= self.status < 500 and self.status != 429:
            return "refused"
        return "unverified"


class Refused(MassiveError):
    """The answer came back but does not carry what was asked (P11): a cursor past the page cap, a
    count that disagrees with the rows, a status we do not know, another day's rows."""

    @property
    def outcome(self):
        return "refused"


class NotEntitled(Refused):
    """An endpoint this key does not carry (options, indices, Benzinga). Refused locally."""


# ---------------------------------------------------------------- pacing

class Pace(object):
    """A token bucket: ``per_minute`` requests a minute, bursts of up to one second's worth.
    Thread-safe; ``clock`` and ``sleep`` are injectable for tests."""

    def __init__(self, per_minute=DEFAULT_RATE, clock=time.monotonic, sleep=time.sleep, burst=None):
        if per_minute <= 0:
            raise ValueError("per_minute must be above 0")
        self.interval = 60.0 / float(per_minute)
        self.capacity = float(burst if burst is not None else max(1, per_minute // 60))
        self.tokens = self.capacity
        self.clock, self.sleep = clock, sleep
        self.last = clock()
        self.lock = threading.Lock()
        self.waited = 0.0

    def take(self):
        while True:
            with self.lock:
                now = self.clock()
                self.tokens = min(self.capacity, self.tokens + (now - self.last) / self.interval)
                self.last = now
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return
                wait = (1.0 - self.tokens) * self.interval
            self.waited += wait
            self.sleep(wait)


_SHARED_PACE = None
_SHARED_LOCK = threading.Lock()


def shared_pace():
    """The one bucket every default client in the process shares."""
    global _SHARED_PACE
    with _SHARED_LOCK:
        if _SHARED_PACE is None:
            _SHARED_PACE = Pace(DEFAULT_RATE)
        return _SHARED_PACE


def _urlopen(url, headers, timeout):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


# ---------------------------------------------------------------- units

def _unit_of(v):
    """Epoch unit by magnitude: s (~1e9), ms (~1e12), us (~1e15), ns (~1e18)."""
    v = abs(int(v))
    if v >= 10 ** 17:
        return "ns"
    if v >= 10 ** 14:
        return "us"
    if v >= 10 ** 11:
        return "ms"
    return "s"


_TO_MS = {"ns": lambda v: int(v) // 1000000, "us": lambda v: int(v) // 1000, "ms": int,
          "s": lambda v: int(v) * 1000}
#: What the snapshot documents (and the recorded fixture shows): ``min.t`` in milliseconds,
#: ``lastTrade.t``, ``lastQuote.t`` and ``updated`` in NANOseconds (CLAUDE.md hazard 5).
SNAPSHOT_UNITS = {"min.t": "ms", "lastTrade.t": "ns", "lastQuote.t": "ns", "updated": "ns"}


def snapshot_times(row):
    """One snapshot row -> {min_t_ms, last_trade_ms, last_quote_ms, updated_ms, units, surprises}.

    The ONE place the units hazard is handled: each stamp is converted by its magnitude, and a
    stamp whose unit differs from ``SNAPSHOT_UNITS`` is listed in ``surprises`` (the caller labels
    the row instead of trusting it)."""
    row = row or {}
    raw = {"min.t": (row.get("min") or {}).get("t"), "lastTrade.t": (row.get("lastTrade") or {}).get("t"),
           "lastQuote.t": (row.get("lastQuote") or {}).get("t"), "updated": row.get("updated")}
    out = {"units": {}, "surprises": []}
    names = {"min.t": "min_t_ms", "lastTrade.t": "last_trade_ms", "lastQuote.t": "last_quote_ms",
             "updated": "updated_ms"}
    for k, v in raw.items():
        if not v:
            out[names[k]] = None
            continue
        u = _unit_of(v)
        out["units"][k] = u
        if u != SNAPSHOT_UNITS[k]:
            out["surprises"].append("%s is %s, documented %s" % (k, u, SNAPSHOT_UNITS[k]))
        out[names[k]] = _TO_MS[u](v)
    return out


def et_day(ms):
    try:
        return datetime.fromtimestamp(int(ms) / 1000.0, tz=ET).date().isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


# ---------------------------------------------------------------- refusals (ported from Odyssey universe.py)

def check_grouped(day, payload):
    """{TICKER: row} for ONE grouped-daily answer, or `Refused`. P11: a status we know, no cursor,
    adjusted, the rows it says it has, every row dated `day` (ET), one row a ticker, and SPY's print
    (the evidence that `day` traded). Rows keep the vendor's ticker case verbatim."""
    if not isinstance(payload, dict):
        raise Refused("grouped %s: the answer is not a JSON object" % day)
    st = payload.get("status")
    if st not in OK_STATUSES:
        raise Refused("grouped %s: status %r" % (day, st))
    if payload.get("next_url"):
        raise Refused("grouped %s: the answer carries a next_url; one request is the whole market, so a "
                      "cursor means it was cut" % day)
    if payload.get("adjusted") is False:
        raise Refused("grouped %s: the vendor answered UNADJUSTED bars" % day)
    rows = payload.get("results") or []
    said = payload.get("resultsCount")
    if said is None:
        raise Refused("grouped %s: no resultsCount to verify the rows against" % day)
    if int(said) != len(rows):
        raise Refused("grouped %s: resultsCount %s but %d rows delivered" % (day, said, len(rows)))
    if not rows:
        raise Refused("grouped %s: no rows (a holiday, or not published yet)" % day)
    out = {}
    other_day = untickered = dupes = 0
    for r in rows:
        t = str(r.get("T") or "").strip()
        if not t:
            untickered += 1
            continue
        if et_day(r.get("t")) != day:
            other_day += 1
            continue
        if t in out:
            dupes += 1
            continue
        out[t] = {"t": int(r["t"]), "o": _num(r.get("o")), "h": _num(r.get("h")), "l": _num(r.get("l")),
                  "c": _num(r.get("c")), "v": _num(r.get("v")), "vw": _num(r.get("vw")), "n": r.get("n")}
    if other_day:
        raise Refused("grouped %s: %d row(s) dated another day; the vendor answered a different session"
                      % (day, other_day))
    if untickered:
        raise Refused("grouped %s: %d row(s) carry no ticker" % (day, untickered))
    if dupes:
        raise Refused("grouped %s: %d ticker(s) appear twice" % (day, dupes))
    if CALENDAR_SYMBOL not in out:
        raise Refused("grouped %s: no %s print; not a session the vendor knows" % (day, CALENDAR_SYMBOL))
    return out


def check_reference(pages, want_type=None, min_rows=1, page_limit=REFERENCE_PAGE_LIMIT):
    """({TICKER: row}, meta) from the reference list's PAGES, or `Refused` (P11): a page whose status
    is not OK, whose `count` disagrees with its rows, a cursor with no rows; a walk that ended on a
    page still carrying a cursor or exactly full; a row with no ticker, outside market=stocks, not
    active, or (with `want_type`) of another type (the filter was ignored); a ticker twice; fewer
    rows than `min_rows`."""
    out, n_pages, last, newest = {}, 0, None, None
    for p in pages:
        n_pages += 1
        if not isinstance(p, dict):
            raise Refused("reference page %d: not a JSON object" % n_pages)
        if p.get("status") != "OK":
            raise Refused("reference page %d: status %r" % (n_pages, p.get("status")))
        rows = p.get("results") or []
        cnt = p.get("count")
        if cnt is not None and int(cnt) != len(rows):
            raise Refused("reference page %d: count %s but %d rows" % (n_pages, cnt, len(rows)))
        if p.get("next_url") and not rows:
            raise Refused("reference page %d: a cursor and no rows" % n_pages)
        for r in rows:
            t = str(r.get("ticker") or "").strip()
            if not t:
                raise Refused("reference page %d: a row without a ticker" % n_pages)
            if r.get("market") != "stocks" or r.get("active") is not True:
                raise Refused("reference page %d: %s answers market=%r active=%r; the vendor ignored the filter"
                              % (n_pages, t, r.get("market"), r.get("active")))
            ty = str(r.get("type") or "").strip().upper() or None
            if want_type and ty != want_type:
                raise Refused("reference page %d: %s has type %r, asked for %s; the vendor ignored the filter"
                              % (n_pages, t, ty, want_type))
            if t in out:
                raise Refused("reference page %d: %s listed twice; the cursor overlapped" % (n_pages, t))
            out[t] = {"ticker": t, "name": " ".join(str(r.get("name") or "").split()), "type": ty,
                      "primary_exchange": r.get("primary_exchange"), "locale": r.get("locale")}
            lu = r.get("last_updated_utc")
            if lu and (newest is None or str(lu) > newest):
                newest = str(lu)
        last = p
    if last is None:
        raise Refused("reference: no page answered")
    if last.get("next_url"):
        raise Refused("reference: the walk stopped on page %d with a cursor still open; the list paginated short"
                      % n_pages)
    if len(last.get("results") or []) >= page_limit:
        raise Refused("reference: the last page (%d) is exactly full with no cursor; the list may have been "
                      "cut there" % n_pages)
    if len(out) < min_rows:
        raise Refused("reference: %d rows, under the %d sanity floor; a truncated list, not the market"
                      % (len(out), min_rows))
    return out, {"rows": len(out), "pages": n_pages, "updated_max": newest, "type": want_type}


# ---------------------------------------------------------------- the client

class Client(object):
    def __init__(self, key=None, base_url=None, timeout=30.0, max_retries=3, opener=None, sleep=None,
                 pace=None, rate_per_min=None):
        self._key = key or C.api_key()
        if not self._key:
            raise MassiveError("no market-data key found: set MASSIVE_API_KEY in ~/Infinit/.env (never in "
                               "<repo>/.env, see CLAUDE.md)")
        self.base_url = (base_url or C.api_base_url()).rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self._open = opener or _urlopen
        self._sleep = sleep or time.sleep
        if pace is not None:
            self.pace = pace
        elif rate_per_min:
            self.pace = Pace(rate_per_min, sleep=self._sleep)
        else:
            self.pace = shared_pace()
        self.requests = 0

    def __repr__(self):
        return "<mjonir.massive.Client %s>" % self.base_url

    # ------------------------------------------------------------ transport
    def _safe(self, text):
        return C.redact(text, self._key)

    def _headers(self):
        return {"Authorization": "Bearer " + self._key, "Accept": "application/json",
                "User-Agent": "mjonir-daytrader/0.1 (stdlib)"}

    def _guard(self, url):
        low = url.lower()
        path = urllib.parse.urlsplit(url).path
        if any(p in low for p in NOT_ENTITLED):
            raise NotEntitled("%s: %s" % (self._safe(path), NOT_ENTITLED_WORDS))
        qs = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        tickers = [path] + qs.get("tickers", []) + qs.get("ticker", [])
        if any(re.search(r"(^|[/,])(O|I):", urllib.parse.unquote(x)) for x in tickers):
            raise NotEntitled("%s: %s" % (self._safe(path), NOT_ENTITLED_WORDS))

    def _fetch(self, url):
        self._guard(url)
        endpoint = self._safe(url.split("?")[0])
        for attempt in range(self.max_retries):
            self.pace.take()
            self.requests += 1
            retry_after = None
            try:
                body = self._open(url, self._headers(), self.timeout)
            except urllib.error.HTTPError as e:
                code = e.code
                try:
                    retry_after = e.headers.get("Retry-After") if e.headers else None
                except Exception:
                    retry_after = None
                try:
                    e.close()
                except Exception:
                    pass
                if code not in RETRY_STATUS or attempt == self.max_retries - 1:
                    raise MassiveError("HTTP %d from %s" % (code, endpoint), status=code)
            except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as e:
                if attempt == self.max_retries - 1:
                    raise MassiveError("network error on %s: %s" % (endpoint, self._safe(e)))
            except Exception as e:
                # http.client.InvalidURL (a symbol with a space) is neither an HTTPError nor a URLError
                # and quotes the whole URL: scrubbed, and not retried (it will not get better).
                raise MassiveError("%s on %s: %s" % (type(e).__name__, endpoint, self._safe(e)))
            else:
                try:
                    return json.loads(body.decode("utf-8") if isinstance(body, bytes) else body)
                except ValueError:
                    raise MassiveError("not JSON from %s" % endpoint)
            try:
                wait = float(retry_after) if retry_after else 0.5 * (2 ** attempt)
            except ValueError:
                wait = 0.5 * (2 ** attempt)
            self._sleep(min(wait, 30.0))
        raise MassiveError("no answer from %s" % endpoint)

    def get(self, path, params=None):
        q = urllib.parse.urlencode(params or {})
        return self._fetch("%s%s%s" % (self.base_url, path, ("?" + q) if q else ""))

    def pages(self, path, params=None):
        """Every PAGE across ``next_url`` hops, refusing past ``MAX_PAGES`` (P11)."""
        payload = self.get(path, params)
        for page in range(1, MAX_PAGES + 1):
            yield payload
            nxt = payload.get("next_url") if isinstance(payload, dict) else None
            if not nxt:
                return
            if page >= MAX_PAGES:
                raise Refused("the vendor is still paging after %d pages on %s; refusing to follow further: a "
                              "truncated answer served as a whole one is what this guard exists for"
                              % (MAX_PAGES, path))
            if urllib.parse.urlsplit(nxt).netloc != urllib.parse.urlsplit(self.base_url).netloc:
                raise Refused("next_url on %s points at another host; not followed" % path)
            payload = self._fetch(nxt)

    # ------------------------------------------------------------ bars
    def aggregates(self, symbol, mult, timespan, start, end, adjusted=True):
        """Raw ascending rows {t (ms, bar START), o, h, l, c, v, vw, n}, extended hours included.
        ``limit=50000`` and ``sort=asc`` always; each page's status and count are checked."""
        sym = urllib.parse.quote(str(symbol).upper(), safe=".")
        path = "/v2/aggs/ticker/%s/range/%d/%s/%s/%s" % (sym, int(mult), timespan, start, end)
        params = {"adjusted": "true" if adjusted else "false", "sort": "asc", "limit": MAX_LIMIT}
        out, seen = [], set()
        for p in self.pages(path, params):
            st = p.get("status")
            if st not in OK_STATUSES:
                raise Refused("aggregates %s %s-%s %s..%s: status %r" % (symbol, mult, timespan, start, end, st))
            rows = p.get("results") or []
            said = p.get("resultsCount")
            if said is not None and int(said) != len(rows):
                raise Refused("aggregates %s: resultsCount %s but %d rows delivered" % (symbol, said, len(rows)))
            if p.get("adjusted") is not None and bool(p.get("adjusted")) != bool(adjusted):
                raise Refused("aggregates %s: asked adjusted=%s, answered %s" % (symbol, adjusted, p.get("adjusted")))
            for r in rows:
                if r.get("c") is None or r.get("t") is None:
                    continue
                t = int(r["t"])
                if t in seen:
                    raise Refused("aggregates %s: bar %d delivered twice; the cursor overlapped" % (symbol, t))
                seen.add(t)
                out.append({"t": t, "o": float(r["o"]), "h": float(r["h"]), "l": float(r["l"]),
                            "c": float(r["c"]), "v": float(r.get("v") or 0.0), "vw": _num(r.get("vw")),
                            "n": r.get("n")})
        if any(out[i]["t"] <= out[i - 1]["t"] for i in range(1, len(out))):
            raise Refused("aggregates %s: rows are not ascending" % symbol)
        return out

    def grouped_daily(self, day, adjusted=True):
        """{TICKER: row} for the whole US stock market on one session (OTC excluded), checked."""
        payload = self.get(GROUPED_PATH % day, {"adjusted": "true" if adjusted else "false",
                                                "include_otc": "false"})
        return check_grouped(str(day), payload)

    # ------------------------------------------------------------ the tape
    def snapshot(self, symbols):
        """{SYMBOL: row} for many tickers, chunks of 200. A ticker the API does not carry is absent;
        a failure raises (no print and could not ask are different answers)."""
        syms = [str(s).upper() for s in dict.fromkeys(symbols) if s]
        out = {}
        for i in range(0, len(syms), SNAPSHOT_CHUNK):
            payload = self.get(SNAPSHOT_PATH, {"tickers": ",".join(syms[i:i + SNAPSHOT_CHUNK])})
            if payload.get("status") not in OK_STATUSES:
                raise Refused("snapshot: status %r" % payload.get("status"))
            for row in payload.get("tickers") or []:
                t = row.get("ticker")
                if t:
                    out[str(t).upper()] = row
        return out

    def snapshot_all(self):
        """{SYMBOL: row} for every US stock in one request; count checked."""
        payload = self.get(SNAPSHOT_PATH, {"include_otc": "false"})
        if payload.get("status") not in OK_STATUSES:
            raise Refused("snapshot (all): status %r" % payload.get("status"))
        rows = payload.get("tickers") or []
        if payload.get("count") is not None and int(payload["count"]) != len(rows):
            raise Refused("snapshot (all): count %s but %d rows" % (payload["count"], len(rows)))
        return {str(r["ticker"]).upper(): r for r in rows if r.get("ticker")}

    def last_trade(self, symbol):
        return (self.get("/v2/last/trade/%s" % urllib.parse.quote(str(symbol).upper(), safe=".")) or {}).get("results")

    def last_nbbo(self, symbol):
        return (self.get("/v2/last/nbbo/%s" % urllib.parse.quote(str(symbol).upper(), safe=".")) or {}).get("results")

    def quote(self, symbol):
        """{bid, ask, t_ms} from the last NBBO, or None when it could not be asked (never 0)."""
        try:
            r = self.last_nbbo(symbol) or {}
        except MassiveError:
            return None
        bid, ask, t = _num(r.get("p")), _num(r.get("P")), r.get("t")
        if not bid or not ask or not t:
            return None
        return {"bid": bid, "ask": ask, "t_ms": _TO_MS[_unit_of(t)](t)}

    # ------------------------------------------------------------ calendar
    def market_status_now(self):
        return self.get("/v1/marketstatus/now")

    def market_status_upcoming(self):
        payload = self.get("/v1/marketstatus/upcoming")
        if not isinstance(payload, list):
            raise Refused("marketstatus/upcoming: not a list")
        return payload

    # ------------------------------------------------------------ reference
    def reference_pages(self, params):
        p = {"market": "stocks", "active": "true", "limit": REFERENCE_PAGE_LIMIT}
        p.update(params or {})
        return list(self.pages(REFERENCE_PATH, p))

    def ticker_overview(self, symbol):
        payload = self.get("%s/%s" % (REFERENCE_PATH, urllib.parse.quote(str(symbol).upper(), safe=".")))
        return payload.get("results") or {}

    def splits(self, symbol=None, since=None, limit=1000):
        """Split rows (``execution_date``, ``split_from``, ``split_to``) for one ticker, or for the whole
        market since a date. Every page followed (P11)."""
        params = {"limit": limit, "order": "asc", "sort": "execution_date"}
        if symbol:
            params["ticker"] = str(symbol).upper()
        if since:
            params["execution_date.gte"] = str(since)
        out = []
        for p in self.pages("/v3/reference/splits", params):
            if p.get("status") not in OK_STATUSES:
                raise Refused("splits: status %r" % p.get("status"))
            out.extend(p.get("results") or [])
        return out

    def news(self, symbol, since_utc=None, limit=50):
        """/v2/reference/news for one ticker, newest first."""
        params = {"ticker": str(symbol).upper(), "limit": min(int(limit), 1000), "order": "desc",
                  "sort": "published_utc"}
        if since_utc is not None:
            if isinstance(since_utc, datetime):
                since_utc = since_utc.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            params["published_utc.gte"] = str(since_utc)
        payload = self.get("/v2/reference/news", params)
        if payload.get("status") not in OK_STATUSES:
            raise Refused("news %s: status %r" % (symbol, payload.get("status")))
        return payload.get("results") or []

    # ------------------------------------------------------------ probe
    def probe(self):
        """Prove the key WORKS with one cheap request. Three outcomes, never two: authenticated,
        rejected (401/403: present and refused), unverified (the host could not be reached)."""
        try:
            self.get(REFERENCE_PATH, {"limit": 1, "market": "stocks"})
            return {"outcome": "authenticated", "detail": "one reference row answered", "base_url": self.base_url}
        except MassiveError as e:
            if e.status in (401, 403):
                return {"outcome": "rejected", "detail": str(e), "base_url": self.base_url}
            return {"outcome": "unverified", "detail": str(e), "base_url": self.base_url}
