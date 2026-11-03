"""Yahoo-shaped documents from Massive bars and the local stores: the one code path (stdlib only).

Upstream's scripts read Yahoo's v8 chart JSON and spark JSON. Under ``--source massive`` they read
the SAME shapes, built here, so their own parsers, rules and tests stay untouched.

Alignment (verified): Yahoo ``timestamp[i]`` is the bar START in seconds; Massive ``t`` is the bar
start in milliseconds, so ``timestamp = t // 1000``. Daily rows are stamped 09:30 New York of their
session. Only regular-hours bars go into a chart (``rth_rows``); ``regularMarketDayHigh/Low/Volume``
are regular hours only. ``entry.py``'s completed-bar rule reads ``meta.regularMarketTime`` as the
last TRADE time: a historical session gets its close, a live one ``lastTrade.t`` (ns) when that is a
regular-hours print today, else ``min.t`` (ms) + 60 s, and the basis is recorded.

``meta.mjonir`` (ignored upstream) carries the source, adjustment, early-close label and, on live
documents, the quote: ``bid, ask, bid_size, ask_size, quote_time, spread_bps, age_s, session``.
That block is the cost layer's input (chunk 2).

The fetchers take a ``client`` (``massive.Client``) and a ``cal`` (``calendar.Calendar``); ``None``
builds the default one. ``Adapter`` is what the scripts' ``_mjonir()`` shim returns.
"""

import datetime as _dt
import json
import threading
from concurrent.futures import ThreadPoolExecutor

from . import cache as CA
from . import calendar as K
from . import localstores as LS
from . import massive as M

INTERVALS = {"1m": (1, "minute", 60), "5m": (5, "minute", 300), "1d": (1, "day", 86400)}
MAX_WORKERS = 8
_AUTO = object()


class DataError(RuntimeError):
    """A document could not be built. ``outcome`` is 'refused' (the data says no: a closed day, no
    bars, a split inside an unadjusted file) or 'unverified' (could not ask)."""

    def __init__(self, message, outcome="refused"):
        super().__init__(message)
        self.outcome = outcome


ERRORS = (DataError, M.MassiveError, K.CalendarError, CA.CacheError, LS.StoreError)


def outcome_of(exc):
    return getattr(exc, "outcome", "unverified")


# ---------------------------------------------------------------- small pieces

def yahoo_symbol(sym):
    return str(sym).strip().upper().replace(".", "-")


def massive_symbol(sym):
    return str(sym).strip().upper().replace("-", ".")


def _iso_utc(dt):
    return dt.astimezone(K.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _vol(v):
    return int(round(float(v or 0)))


def _client(client):
    return client if client is not None else M.Client()


def _cal(cal):
    return cal if cal is not None else K.Calendar.load()


def _cache(cache):
    if cache is _AUTO:
        return CA.Cache()
    return cache or None


def rth_rows(rows, cal, day=None):
    """Rows inside the regular session of their own New York date (and of `day` only, if given)."""
    out = cal.rth_filter(rows)
    if day is not None:
        d = K.as_date(day)
        out = [r for r in out if K.et_of_ms(r["t"]).date() == d]
    return out


def by_session(rows):
    out = {}
    for r in rows:
        out.setdefault(K.et_of_ms(r["t"]).date(), []).append(r)
    return out


def session_state(cal, now):
    """'pre', 'regular', 'post' or 'closed' for an aware New York datetime."""
    b = cal.session_bounds(now.date())
    if b is None:
        return "closed"
    if now < b[0]:
        return "pre"
    return "regular" if now < b[1] else "post"


def quote_block(snap, now):
    """bid, ask, sizes, quote time, spread in bps and age from a snapshot row's lastQuote (P2: None
    when absent, never 0)."""
    q = (snap or {}).get("lastQuote") or {}
    times = M.snapshot_times(snap)
    bid, ask = q.get("p"), q.get("P")
    out = {"bid": bid, "ask": ask, "bid_size": q.get("s"), "ask_size": q.get("S"), "quote_time": None,
           "spread_bps": None, "age_s": None, "units_surprises": times["surprises"] or None}
    if times["last_quote_ms"]:
        qt = K.et_of_ms(times["last_quote_ms"])
        out["quote_time"] = _iso_utc(qt)
        out["age_s"] = max(0, int((now - qt).total_seconds()))
    if bid and ask and ask >= bid > 0:
        out["spread_bps"] = round((ask - bid) / ((ask + bid) / 2.0) * 1e4, 2)
    return out


def _meta(symbol, interval, day, rng, mj, price=None, market_time=None, prev_close=None, chart_prev_close=None,
          day_high=None, day_low=None, day_volume=None):
    tzname, off = K.tz_label(day)
    return {"currency": "USD", "symbol": yahoo_symbol(symbol), "exchangeName": "MASSIVE", "instrumentType": "EQUITY",
            "regularMarketTime": market_time, "hasPrePostMarketData": False, "gmtoffset": off, "timezone": tzname,
            "exchangeTimezoneName": "America/New_York", "regularMarketPrice": price,
            "regularMarketDayHigh": day_high, "regularMarketDayLow": day_low, "regularMarketVolume": day_volume,
            "chartPreviousClose": chart_prev_close if chart_prev_close is not None else prev_close,
            "previousClose": prev_close, "dataGranularity": interval, "range": rng, "mjonir": mj}


def _result(meta, rows, interval):
    ts = [int(r["t"]) // 1000 for r in rows]
    if interval == "1d":
        ts = [int(K.ms_of(_dt.datetime.combine(K.et_of_ms(r["t"]).date(), K.OPEN, tzinfo=K.ET))) // 1000
              for r in rows]
    return {"meta": meta, "timestamp": ts,
            "indicators": {"quote": [{"open": [r["o"] for r in rows], "high": [r["h"] for r in rows],
                                      "low": [r["l"] for r in rows], "close": [r["c"] for r in rows],
                                      "volume": [_vol(r.get("v")) for r in rows]}]}}


def _wrap(result):
    return {"chart": {"result": [result], "error": None}}


def to_text(doc):
    return json.dumps(doc, separators=(",", ":"))


# ---------------------------------------------------------------- the documents (pure)

def live_time_price(snap, rth_today, cal, now, step):
    """(regularMarketTime, basis, price, withheld) for today's chart while the session runs."""
    times = M.snapshot_times(snap)
    b = cal.session_bounds(now.date())
    lt = (snap or {}).get("lastTrade") or {}
    if b and now >= b[1]:
        day_c = ((snap or {}).get("day") or {}).get("c")
        price = day_c if day_c else (rth_today[-1]["c"] if rth_today else None)
        return int(b[1].timestamp()), "session_close", price, None
    lt_ms = times["last_trade_ms"]
    if lt_ms and b and b[0] <= K.et_of_ms(lt_ms) < b[1] and lt.get("p"):
        return lt_ms // 1000, "last_trade", float(lt["p"]), None
    mn = (snap or {}).get("min") or {}
    m_ms = times["min_t_ms"]
    if m_ms and b and b[0] <= K.et_of_ms(m_ms) < b[1] and mn.get("c"):
        return m_ms // 1000 + 60, "minute_bar", float(mn["c"]), None
    withheld = None
    if lt_ms and K.et_of_ms(lt_ms).date() == now.date():
        withheld = "an extended-hours print at %s ET, never a regular-hours mark" % K.et_of_ms(lt_ms).strftime("%H:%M")
    if rth_today:
        return int(rth_today[-1]["t"]) // 1000, "last_bar_start", rth_today[-1]["c"], withheld
    prev = ((snap or {}).get("prevDay") or {}).get("c")
    pb = cal.session_bounds(cal.prev_session(now.date()))
    return int(pb[1].timestamp()), "previous_close", prev, withheld


def chart_doc(symbol, rows, interval, cal, day=None, rng="1d", prev_close=None, chart_prev_close=None,
              daily_close=None, live=None, now=None, source="massive", adjusted=True, generated_at=None,
              only_day=True):
    """A v8 chart document: regular-hours bars of one session (or, with ``only_day=False``, of every
    session in `rows`: a history), ascending, on grid, no nulls. ``day`` is the (last) session;
    ``live`` is today's snapshot row (None for a past session)."""
    mult, _, step = INTERVALS[interval]
    now = now or K.now_et()
    rth = rth_rows(rows, cal, day if only_day else None)
    sessions = sorted(by_session(rth))
    if day is not None:
        last_day = K.as_date(day)
    elif sessions:
        last_day = sessions[-1]
    else:
        raise DataError("no regular-hours %s bars for %s" % (interval, symbol))
    today_rows = [r for r in rth if K.et_of_ms(r["t"]).date() == last_day]
    if not today_rows and not (live is not None and session_state(cal, now) == "pre"):
        raise DataError("no regular-hours %s bars for %s on %s" % (interval, symbol, last_day))
    mj = {"source": source, "adjusted": adjusted, "rth_only": True, "generated_at": generated_at or _iso_utc(now),
          "early_close": cal.early_close_label(last_day) if cal.is_early_close(last_day) else None,
          "early_close_basis": cal.early_close_basis(last_day, len(today_rows) if today_rows else None),
          "sessions": len(sessions), "bars": len(rth), "expected_bars": cal.expected_bars(last_day, mult)
          if interval != "1d" else None}
    if live is not None:
        mt, basis, price, withheld = live_time_price(live, today_rows, cal, now, step)
        mj.update(quote_block(live, now), session=session_state(cal, now), regular_market_time_basis=basis,
                  withheld=withheld)
        if prev_close is None:
            prev_close = ((live.get("prevDay") or {}).get("c")) or None
        forming = [r for r in today_rows if r["t"] // 1000 + step > now.timestamp()]
        mj["forming"] = ({"start": K.et_of_ms(forming[-1]["t"]).strftime("%H:%M"), "t": forming[-1]["t"] // 1000}
                         if forming else None)
    else:
        b = cal.session_bounds(last_day)
        mt, price = int(b[1].timestamp()), (daily_close if daily_close is not None else today_rows[-1]["c"])
        mj.update(session="closed", regular_market_time_basis="session_close",
                  close_basis="daily_bar" if daily_close is not None else "last_rth_bar")
    meta = _meta(symbol, interval, last_day, rng, mj, price=price, market_time=mt, prev_close=prev_close,
                 chart_prev_close=chart_prev_close,
                 day_high=max((r["h"] for r in today_rows), default=None),
                 day_low=min((r["l"] for r in today_rows), default=None),
                 day_volume=sum(_vol(r.get("v")) for r in today_rows) if today_rows else None)
    return _wrap(_result(meta, rth, interval))


def history_doc(symbol, rows, cal, start, end, live=None, now=None, source="massive", adjusted=True,
                interval="5m", generated_at=None):
    """Many sessions in one v8 document (the time machine's `<SYM>-60d5m.json.gz`). meta.range tells
    the truth: the number of sessions asked, with from / to and the incomplete sessions in mjonir."""
    sessions = cal.sessions_between(start, end)
    if not sessions:
        raise DataError("no session between %s and %s" % (start, end))
    rth = rth_rows(rows, cal)
    rth = [r for r in rth if sessions[0] <= K.et_of_ms(r["t"]).date() <= sessions[-1]]
    per = by_session(rth)
    mult = INTERVALS[interval][0]
    short = [{"date": d.isoformat(), "bars": len(per.get(d, [])), "expected": cal.expected_bars(d, mult)}
             for d in sessions if len(per.get(d, [])) != cal.expected_bars(d, mult)]
    doc = chart_doc(symbol, rth, interval, cal, day=sessions[-1], rng="%dd" % len(sessions), live=live, now=now,
                    source=source, adjusted=adjusted, generated_at=generated_at, only_day=False,
                    prev_close=(per[sessions[-2]][-1]["c"] if len(sessions) > 1 and per.get(sessions[-2]) else None),
                    chart_prev_close=None)
    mj = doc["chart"]["result"][0]["meta"]["mjonir"]
    mj.update(sessions=len(sessions), first_session=sessions[0].isoformat(), last_session=sessions[-1].isoformat(),
              incomplete_sessions=short,
              early_closes={d.isoformat(): cal.early_close_basis(d, len(per.get(d, [])) or None)
                            for d in sessions if cal.is_early_close(d)},
              prev_close_basis="last_rth_bar")
    return doc


def daily_doc(symbol, rows, cal, rng=None, source="massive", adjusted=True, closes_only=False, generated_at=None,
              now=None):
    """A daily v8 result for one symbol (rows = daily bars, ``t`` any time on the session date).
    regularMarketPrice and regularMarketVolume are the last COMPLETE session's."""
    if not rows:
        raise DataError("no daily bars for %s" % symbol)
    rows = sorted(rows, key=lambda r: r["t"])
    last = rows[-1]
    d_last = K.et_of_ms(last["t"]).date()
    b = cal.session_bounds(d_last)
    mj = {"source": source, "adjusted": adjusted, "sessions": len(rows), "generated_at": generated_at
          or _iso_utc(now or K.now_et()), "first_session": K.et_of_ms(rows[0]["t"]).date().isoformat(),
          "last_session": d_last.isoformat()}
    meta = _meta(symbol, "1d", d_last, rng or "%dd" % len(rows), mj, price=last["c"],
                 market_time=int(b[1].timestamp()) if b else int(last["t"]) // 1000,
                 prev_close=rows[-2]["c"] if len(rows) > 1 else None,
                 day_high=last["h"], day_low=last["l"], day_volume=_vol(last.get("v")))
    res = _result(meta, rows, "1d")
    if closes_only:
        res["indicators"]["quote"][0] = {"close": res["indicators"]["quote"][0]["close"]}
    return res


def spark_doc(results):
    """{"spark": {"result": [{"symbol", "response": [result]}], "error": None}} from v8 results (or
    whole v8 documents), symbols in Yahoo form."""
    out = []
    for res in results:
        if "chart" in res:
            res = res["chart"]["result"][0]
        out.append({"symbol": res["meta"]["symbol"], "response": [res]})
    return {"spark": {"result": out, "error": None}}


def last_regular_session(cal, now):
    """The session a quote describes: today once it has opened, else the one before."""
    return now.date() if session_state(cal, now) in ("regular", "post") else cal.prev_session(now.date())


def snapshot_day_is(snap, day):
    """True when the snapshot's ``day`` bar is session `day` (its newest minute is dated `day`). After
    the 03:30 ET clear ``day`` is empty and ``prevDay`` holds the last session instead."""
    t = M.snapshot_times(snap)["min_t_ms"]
    return bool(t and K.et_of_ms(t).date() == day and ((snap or {}).get("day") or {}).get("c"))


def quote_doc(symbol, snap, cal, now, prev_close=None, source="massive"):
    """A range=1d interval=1d v8 document from one snapshot row: what ``alerts.parse_yahoo`` and
    ``news.parse_chart`` read. In the session: the last regular-hours trade. Otherwise the last
    regular close (a pre- or post-market print is withheld and named). ``prev_close`` fills the
    previous close when the snapshot was cleared (before the open)."""
    snap = snap or {}
    state = session_state(cal, now)
    day, prev = snap.get("day") or {}, snap.get("prevDay") or {}
    times = M.snapshot_times(snap)
    sess = last_regular_session(cal, now)
    withheld, bar = None, None
    if state == "regular":
        mt, basis, price, withheld = live_time_price(snap, [], cal, now, 60)
        pc = prev.get("c")
        if snapshot_day_is(snap, sess):
            bar = day
    elif snapshot_day_is(snap, sess):
        mt, basis, price, pc, bar = int(cal.session_bounds(sess)[1].timestamp()), "session_close", day["c"], \
            prev.get("c"), day
    else:
        if state == "post":   # no print today at all: the last close is the session before
            sess = cal.prev_session(now.date())
        mt, basis, price, pc = int(cal.session_bounds(sess)[1].timestamp()), "previous_close", prev.get("c"), prev_close
    close_at = cal.session_bounds(sess)[1]
    lt_ms = times["last_trade_ms"]
    if withheld is None and basis != "last_trade" and lt_ms and K.et_of_ms(lt_ms) >= close_at:
        withheld = "an extended-hours print at %s ET, never a regular-hours mark" % K.et_of_ms(lt_ms).strftime(
            "%Y-%m-%d %H:%M")
    if not price:
        raise DataError("no regular-hours price for %s in the snapshot" % symbol)
    mj = dict(quote_block(snap, now), source=source, adjusted=True, rth_only=True, session=state,
              regular_market_time_basis=basis, withheld=withheld, generated_at=_iso_utc(now),
              session_date=sess.isoformat())
    rows = []
    if bar is not None and bar.get("o"):
        rows = [{"t": K.ms_of(_dt.datetime.combine(sess, K.OPEN, tzinfo=K.ET)), "o": bar.get("o"), "h": bar.get("h"),
                 "l": bar.get("l"), "c": bar.get("c"), "v": bar.get("v")}]
    meta = _meta(symbol, "1d", sess, "1d", mj, price=price, market_time=mt, prev_close=pc,
                 day_high=bar.get("h") if rows else None, day_low=bar.get("l") if rows else None,
                 day_volume=_vol(bar.get("v")) if rows else None)
    return _wrap(_result(meta, rows, "1d"))


def news_items(ticker, rows):
    """Massive /v2/reference/news rows -> trader-news items (time as an ISO string, UTC)."""
    out = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        link = r.get("article_url") or ""
        out.append({"id": "massive:" + str(r.get("id") or link), "source": "Massive news", "kind": "headline",
                    "ticker": ticker.upper(), "title": " ".join(str(r.get("title") or "").split()),
                    "summary": " ".join(str(r.get("description") or "").split()), "link": link,
                    "publisher": (r.get("publisher") or {}).get("name"), "time": r.get("published_utc")})
    return out


# ---------------------------------------------------------------- fetching (client + calendar + cache)

def session_rows(client, cal, symbol, day, interval="5m", cache=None):
    """Raw rows of one session (extended hours included): the cache for a complete session, else the
    API (and the cache is filled). "Complete" is judged by the REAL clock (a date before today in New
    York): a replay pinned with --now must cut the bars by its own now. Today's session and an empty
    answer are never cached. The cache key is the Massive ticker (BRK.B and BRK-B share a session)."""
    day = K.as_date(day)
    mult, span, _ = INTERVALS[interval]
    key = massive_symbol(symbol)
    cacheable = cache is not None and day < K.today_et()
    if cacheable:
        got = cache.get_session(key, interval, day, src="massive")
        if got is not None:
            return got
    rows = client.aggregates(key, mult, span, day.isoformat(), day.isoformat())
    if cacheable and rows:
        cache.put_session(key, interval, day, rows, "massive", adjusted=True)
    return rows


def range_rows(client, cal, symbol, sessions, interval="5m", cache=None, stats=None):
    """Raw rows for many sessions: cached ones from the cache, the rest in ranged API requests
    (contiguous runs), each complete session with rows then cached. A session the answer lacks is
    NOT cached (the next call asks again). `stats` (a dict) receives cached / fetched session counts,
    the API requests made and the oldest fetch date of the cached rows used."""
    mult, span, _ = INTERVALS[interval]
    key = massive_symbol(symbol)
    today = K.today_et()
    out, missing, oldest = [], [], None
    for d in sessions:
        got = cache.get_session(key, interval, d, src="massive") if (cache is not None and d < today) else None
        if got is None:
            missing.append(d)
        else:
            out.extend(got)
            f = (cache.coverage(key, interval, d) or {}).get("fetched_at")
            oldest = f if oldest is None or (f and f < oldest) else oldest
    runs, cur = [], []
    for d in missing:
        if cur and cal.next_session(cur[-1]) != d:
            runs.append(cur)
            cur = []
        cur.append(d)
    if cur:
        runs.append(cur)
    for run in runs:
        rows = client.aggregates(key, mult, span, run[0].isoformat(), run[-1].isoformat())
        per = by_session(rows)
        for d in run:
            got = per.get(d, [])
            if cache is not None and d < today and got:
                cache.put_session(key, interval, d, got, "massive", adjusted=True)
            out.extend(got)
    if stats is not None:
        stats.update(cached=len(sessions) - len(missing), fetched=len(missing), requests=len(runs),
                     oldest_fetch=oldest)
    return sorted(out, key=lambda r: r["t"])


def kalex_rows_checked(client, symbol, sessions):
    """(rows, coverage) from the Kalex store, after a split check. The store is adjusted as of its
    coverage end; a split executed after that end (and so on or after the span) leaves its rows on the
    old share count against every other source: REFUSED, naming the split. When no client can ask,
    UNVERIFIED, never served silently."""
    sym = massive_symbol(symbol)
    cov = LS.kalex_coverage(sym)
    if not cov:
        raise DataError("the Kalex store has no %s rows" % symbol)
    try:
        splits = _client(client).splits(symbol=sym)
    except M.MassiveError as e:
        raise DataError("the Kalex rows of %s are adjusted as of %s and no client could check for a later "
                        "split: %s" % (symbol, cov["last_day"], e), outcome="unverified")
    late = [x for x in splits if str(x.get("execution_date"))[:10] > cov["last_day"]
            and str(x.get("execution_date"))[:10] >= K.as_date(sessions[0]).isoformat()]
    if late:
        x = late[0]
        raise DataError("%s split %s-for-%s on %s, after the Kalex store's coverage end %s: its rows are on the "
                        "old share count, refused (use --source api)" % (symbol, x.get("split_to"),
                                                                         x.get("split_from"),
                                                                         x.get("execution_date"), cov["last_day"]))
    return LS.kalex_5m(sym, sessions[0], sessions[-1]), cov


def daily_rows(client, cal, symbol, start, end, cache=None):
    sessions = cal.sessions_between(start, end)
    return range_rows(client, cal, symbol, sessions, "1d", cache)


def fetch_chart_doc(client, cal, symbol, day, interval="5m", live=None, clock=None, cache=_AUTO):
    """One session's v8 chart. ``live`` defaults to day == today (the REAL clock): a live chart
    carries the forming bar (labelled, never cached) and the snapshot's quote."""
    cal = _cal(cal)
    day = K.as_date(day)
    if interval not in ("1m", "5m"):
        raise DataError("intraday charts are 5m or 1m, not %s" % interval)
    why = cal.why_closed(day)
    if why:
        raise DataError("no session on %s (%s)" % (day, why))
    real = K.now_et()
    if day > real.date():
        raise DataError("%s is in the future" % day)
    is_live = (day == real.date()) if live is None else bool(live)
    client = _client(client)
    cache = None if is_live else _cache(cache)
    try:
        rows = session_rows(client, cal, symbol, day, interval, cache)
        prev = cal.prev_session(day)
        if is_live:
            snap = client.snapshot([massive_symbol(symbol)]).get(massive_symbol(symbol))
            if snap is None:
                raise DataError("the snapshot has no row for %s" % symbol)
            return chart_doc(symbol, rows, interval, cal, day=day, live=snap, now=real)
        daily = {K.et_of_ms(r["t"]).date(): r for r in daily_rows(client, cal, symbol, prev, day, cache)}
        return chart_doc(symbol, rows, interval, cal, day=day, now=real,
                         prev_close=(daily.get(prev) or {}).get("c"),
                         daily_close=(daily.get(day) or {}).get("c"))
    finally:
        if cache is not None:
            cache.close()


def fetch_charts_bulk(client, cal, symbols, day, interval="5m", workers=MAX_WORKERS, clock=None, cache=_AUTO):
    """({SYM: v8 doc}, {SYM: error}) for one session, at most 8 threads, paced by the client's bucket.
    A past session takes its previous and own closes from two grouped-daily answers (cached)."""
    cal = _cal(cal)
    day = K.as_date(day)
    why = cal.why_closed(day)
    if why:
        raise DataError("no session on %s (%s)" % (day, why))
    real = K.now_et()
    is_live = day == real.date()
    client = _client(client)
    cache = None if is_live else _cache(cache)
    syms = [s.upper() for s in dict.fromkeys(symbols) if s]
    docs, errors = {}, {}
    lock = threading.Lock()
    try:
        prev = cal.prev_session(day)
        if is_live:
            snaps = client.snapshot([massive_symbol(s) for s in syms])
            closes = None
        else:
            snaps = None
            g_prev = grouped_day(client, prev, cache)
            g_day = grouped_day(client, day, cache)
            closes = (g_prev, g_day)

        def one(sym):
            try:
                rows = session_rows(client, cal, sym, day, interval, cache)
                if is_live:
                    snap = snaps.get(massive_symbol(sym))
                    if snap is None:
                        raise DataError("the snapshot has no row for %s" % sym)
                    doc = chart_doc(sym, rows, interval, cal, day=day, live=snap, now=real)
                else:
                    ms = massive_symbol(sym)
                    doc = chart_doc(sym, rows, interval, cal, day=day, now=real,
                                    prev_close=(closes[0].get(ms) or {}).get("c"),
                                    daily_close=(closes[1].get(ms) or {}).get("c"))
                with lock:
                    docs[sym] = doc
            except ERRORS as e:
                with lock:
                    errors[sym] = str(e)
        with ThreadPoolExecutor(max_workers=max(1, min(MAX_WORKERS, int(workers)))) as ex:
            list(ex.map(one, syms))
    finally:
        if cache is not None:
            cache.close()
    return docs, errors


def grouped_day(client, day, cache=None):
    """{TICKER: row} for one session: the cache when complete and stored, else the API (checked)."""
    day = K.as_date(day)
    cacheable = cache is not None and day < K.today_et()
    if cacheable:
        got = cache.get_grouped(day)
        if got is not None:
            return got
    rows = client.grouped_daily(day.isoformat())
    if cacheable:
        cache.put_grouped(day, rows)
    return rows


def fetch_daily_bundle(client, cal, symbols=None, sessions=65, end=None, clock=None, cache=_AUTO):
    """(spark document, info): the last `sessions` COMPLETE sessions of daily bars for every symbol
    (or every ticker in the grouped answers), from grouped-daily (one request a session, cached), with
    real highs and lows. A ticker that split inside the window (or since) is fetched on its own,
    adjusted, instead of being spliced from grouped days adjusted at different times."""
    cal = _cal(cal)
    client = _client(client)
    cache = _cache(cache)
    try:
        end = K.as_date(end) if end else cal.last_complete_session(clock)
        days = cal.sessions_back(end, int(sessions))
        per_day = {}
        for d in days:
            per_day[d] = grouped_day(client, d, cache)
        split_rows = client.splits(since=days[0].isoformat())
        split_syms = sorted(set(str(s.get("ticker") or "").upper() for s in split_rows) - {""})
        want = [s.upper() for s in symbols] if symbols else sorted(set().union(*[set(g) for g in per_day.values()]))
        results, failed = [], {}
        for sym in want:
            ms = massive_symbol(sym)
            if ms in split_syms:
                try:
                    rows = client.aggregates(ms, 1, "day", days[0].isoformat(), days[-1].isoformat())
                except M.MassiveError as e:
                    failed[sym] = str(e)
                    continue
                basis = "aggregates (split since %s)" % days[0]
            else:
                rows = [per_day[d][ms] for d in days if ms in per_day[d]]
                basis = "grouped"
            if not rows:
                failed[sym] = "no daily bars in the %d sessions" % len(days)
                continue
            res = daily_doc(sym, rows, cal, rng="%dd" % len(days), closes_only=False)
            res["meta"]["mjonir"]["basis"] = basis
            results.append(res)
        info = {"sessions": len(days), "from": days[0].isoformat(), "to": days[-1].isoformat(),
                "symbols": len(want), "built": len(results), "failed": len(failed),
                "split_refetched": [s for s in want if massive_symbol(s) in split_syms], "requests": client.requests}
        doc = spark_doc(results)
        doc["mjonir"] = dict(info, failed_symbols=failed)
        return doc, info
    finally:
        if cache is not None:
            cache.close()


def fetch_history_doc(client, cal, symbol, start, end, source="auto", clock=None, cache=_AUTO, interval="5m"):
    """Many sessions of 5-minute bars in one v8 document, from ONE source:
    ``api`` (Massive, adjusted now, cached), ``kalex`` (local, adjusted as of its coverage end, read-only,
    refused after a later split, unverified when no client can check: ``kalex_rows_checked``),
    ``flatfile`` (local, UNADJUSTED: refused across a split), or ``auto`` (kalex when the store holds
    the whole range, else api). The last session may be today (live, never cached)."""
    cal = _cal(cal)
    start, end = K.as_date(start), K.as_date(end)
    sessions = cal.sessions_between(start, end)
    if not sessions:
        raise DataError("no session between %s and %s" % (start, end))
    real = K.now_et()
    if sessions[-1] > real.date():
        raise DataError("%s is in the future" % sessions[-1])
    live_day = sessions[-1] == real.date()
    if source == "auto":
        cov = None
        try:
            cov = LS.kalex_coverage(massive_symbol(symbol))
        except Exception:   # an unreadable store means "not kalex", never a crash
            cov = None
        source = "kalex" if (cov and cov["first_day"] <= sessions[0].isoformat()
                             and sessions[-1].isoformat() <= cov["last_day"] and not live_day) else "api"
    if source in ("kalex", "flatfile") and live_day:
        raise DataError("today's session is not in the local stores: use --source api")
    if source == "kalex":
        rows, _ = kalex_rows_checked(client, symbol, sessions)
        if not rows:
            raise DataError("the Kalex store has no %s rows for %s..%s" % (symbol, sessions[0], sessions[-1]))
        return history_doc(symbol, rows, cal, start, end, now=real, source="kalex", adjusted=True)
    client = _client(client)
    if source == "flatfile":
        splits = [s for s in client.splits(symbol=massive_symbol(symbol))
                  if sessions[0].isoformat() < str(s.get("execution_date"))[:10] <= sessions[-1].isoformat()]
        if splits:
            raise DataError("%s split on %s inside %s..%s: the flat files are unadjusted, refused"
                            % (symbol, splits[0]["execution_date"], sessions[0], sessions[-1]))
        rows = LS.flatfile_bulk([massive_symbol(symbol)], sessions)[massive_symbol(symbol)]
        return history_doc(symbol, rows, cal, start, end, now=real, source="flatfile", adjusted=False)
    if source != "api":
        raise DataError("--source is auto, api, kalex or flatfile, not %r" % source)
    cache = _cache(cache)
    try:
        if cache is not None:
            cache.invalidate_split(massive_symbol(symbol), client.splits(symbol=massive_symbol(symbol)))
        done = [d for d in sessions if d != real.date()]
        rows = range_rows(client, cal, symbol, done, interval, cache) if done else []
        snap = None
        if live_day:
            rows = rows + client.aggregates(massive_symbol(symbol), INTERVALS[interval][0], INTERVALS[interval][1],
                                            real.date().isoformat(), real.date().isoformat())
            snap = client.snapshot([massive_symbol(symbol)]).get(massive_symbol(symbol))
        return history_doc(symbol, rows, cal, start, end, live=snap, now=real, source="massive", adjusted=True,
                           interval=interval)
    finally:
        if cache is not None:
            cache.close()


def fetch_history_bars(client, cal, symbol, start, end, source="auto", cache=_AUTO):
    """The time machine's history (chunk 2): ``bars.bars_5m`` (ONE store: Kalex, the API or its cache, or
    the flat files; complete bars by the real clock, regular hours) as a v8 history document whose
    ``meta.mjonir`` carries that call's own ``info``: ``store`` (api, cache, kalex, flatfile), ``adjusted``
    and ``as_of``. ``source`` stays massive, kalex or flatfile (the chunk 1 label)."""
    from . import bars as B
    cal = _cal(cal)
    info = {}
    rows = B.bars_5m(symbol, start, end, rth_only=True, client=client, cal=cal, source=source, cache=cache,
                     info=info)
    dicts = [{"t": t, "o": o, "h": h, "l": l, "c": c, "v": v} for (t, o, h, l, c, v) in rows]
    store = info.get("source")
    doc = history_doc(symbol, dicts, cal, start, end, now=K.now_et(),
                      source="massive" if store in ("api", "cache") else store, adjusted=info.get("adjusted"))
    doc["chart"]["result"][0]["meta"]["mjonir"].update(store=store, as_of=info.get("as_of"))
    return doc


def fetch_adv_usd(client, cal, symbol, asof, n=20):
    """The cost layer's ADV$ (bars.adv_usd): the n sessions strictly before asof."""
    from . import bars as B
    return B.adv_usd(symbol, asof, n, client=client, cal=cal)


def fetch_quote(client, symbol):
    """The NBBO {bid, ask, t_ms} (bars.quote), or None when it could not be asked."""
    from . import bars as B
    return B.quote(symbol, client=client)


def fetch_daily_rows(client, cal, symbol, start, end):
    """Adjusted daily bars of complete sessions (bars.daily) as (t_ms, o, h, l, c, v)."""
    from . import bars as B
    return B.daily(symbol, start, end, client=client, cal=cal)


def fetch_quote_docs(client, cal, symbols, clock=None):
    """({SYM: range=1d v8 doc}, {SYM: error}) from ONE snapshot request per 200 tickers. Before the
    open the previous close needs the session before it: one daily request per ticker then."""
    cal = _cal(cal)
    client = _client(client)
    now = K.now_et(clock)
    syms = [s.upper() for s in dict.fromkeys(symbols) if s]
    snaps = client.snapshot([massive_symbol(s) for s in syms])
    docs, errors = {}, {}
    sess = last_regular_session(cal, now)
    for sym in syms:
        snap = snaps.get(massive_symbol(sym))
        if snap is None:
            errors[sym] = "Massive has no snapshot row for %s" % sym
            continue
        pc = None
        try:
            if session_state(cal, now) != "regular" and not snapshot_day_is(snap, sess):
                last = cal.prev_session(now.date())
                rows = client.aggregates(massive_symbol(sym), 1, "day", cal.prev_session(last).isoformat(),
                                         last.isoformat())
                if len(rows) >= 2:
                    pc = rows[-2]["c"]
            docs[sym] = quote_doc(sym, snap, cal, now, prev_close=pc)
        except ERRORS as e:
            errors[sym] = str(e)
    return docs, errors


# ---------------------------------------------------------------- the scripts' adapter

class Adapter(object):
    """What ``_mjonir()`` returns inside an upstream script. Every mjonir failure comes back as the
    script's own error class, so its ``main()`` prints one line and exits 1. The fetchers are looked
    up at call time (tests replace them with ones that serve fixture documents)."""

    def __init__(self, err):
        self.err = err

    def _run(self, fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except ERRORS as e:
            raise self.err("Massive (%s): %s" % (outcome_of(e), e))
        except ValueError as e:
            raise self.err("Massive: %s" % e)

    @staticmethod
    def _now_text(a):
        return getattr(a, "now", None) if a is not None else None

    def chart_text(self, symbol, interval, day, live=None):
        """entry.py / exit.py: one session's v8 chart as text (no 60-day cap)."""
        g = globals()
        return to_text(self._run(g["fetch_chart_doc"], None, None, symbol, day, interval, live))

    def spark_series(self, symbols, rng, interval, parse_spark, a=None):
        """scan.py fetch_spark(): ({SYM: series}, {SYM: error}). Daily: the grouped-daily bundle.
        5-minute: one v8 chart per symbol (real highs and lows, so no stage 2)."""
        g = globals()
        now = self._run(K.parse_now, self._now_text(a))
        if interval == "1d":
            doc, _ = self._run(g["fetch_daily_bundle"], None, None, symbols, 65, None, self._now_text(a))
            errs = (doc.get("mjonir") or {}).get("failed_symbols") or {}
        else:
            docs, errs = self._run(g["fetch_charts_bulk"], None, None, symbols, now.date(), interval)
            doc = spark_doc([docs[s] for s in sorted(docs)])
        wanted = {yahoo_symbol(s): s for s in symbols}
        got = parse_spark(doc, wanted)
        data = {s: got[s] for s in symbols if s in got}
        failed = {s: errs.get(s) or "no data from Massive" for s in symbols if s not in data}
        return data, failed

    def history_text(self, symbol, date, sessions=60, years=None, now=None):
        """timemachine.py: `sessions` sessions ending on the plan's date (60 = Yahoo's 60d), or every
        session of the `years` years before it, through bars.bars_5m (fetch_history_bars)."""
        g = globals()
        cal = self._run(K.Calendar.load)
        end = self._run(K.as_date, date)
        if years:
            start = end - _dt.timedelta(days=int(round(365.25 * float(years))))
        else:
            start = self._run(cal.sessions_back, end, int(sessions))[0]
        return to_text(self._run(g["fetch_history_bars"], None, cal, symbol, start, end, "auto"))

    def adv_usd(self, symbol, asof, n=20):
        """The cost layer's ADV$: mean close x volume over the n sessions strictly before asof."""
        g = globals()
        return self._run(g["fetch_adv_usd"], None, None, symbol, asof, n)

    def quote(self, symbol):
        """The NBBO {bid, ask, t_ms}, or None when it could not be asked (never 0)."""
        g = globals()
        try:
            return g["fetch_quote"](None, symbol)
        except ERRORS:
            return None

    def daily_rows(self, symbol, start, end):
        """Adjusted daily bars [(t_ms, o, h, l, c, v)] of complete sessions (trader-exit's datr stop)."""
        g = globals()
        return self._run(g["fetch_daily_rows"], None, None, symbol, start, end)

    def quote_texts(self, symbols):
        """alerts.py / news.py: {SYM: v8 text} from one snapshot request; a missing ticker is absent."""
        g = globals()
        docs, _ = self._run(g["fetch_quote_docs"], None, None, symbols)
        return {s: to_text(d) for s, d in docs.items()}

    def news_texts(self, symbols, since_utc, limit=50):
        """news.py: {SYM: JSON text of Massive's raw news rows} since a UTC time."""
        g = globals()
        return self._run(g["fetch_news"], None, symbols, since_utc, limit)

    def news_items(self, ticker, text):
        """news.py: Massive news rows (JSON text or a list) as trader-news items."""
        return self._run(lambda: news_items(ticker, json.loads(text) if isinstance(text, (str, bytes)) else text))

    def rvol_scan(self, day, symbols, floors, top, lookback, shortlist, live, say=None):
        """scan.py rvol: the two-stage list of docs/PREREG_RVOL_ORB.md (mjonir/rvol.py) on Massive's data, with the
        requests it made. mjonir.rvol.make_fetch is looked up at call time (the tests serve a synthetic store).
        say(text) hears the stage-2 request count before stage 2 starts."""
        from . import rvol as R
        cal = self._run(K.Calendar.load)
        fetch = self._run(R.make_fetch, cal)
        doc = self._run(R.scan, fetch, cal, day, symbols, floors, top, lookback, R.ADV_N, shortlist, live, say=say)
        doc["requests"] = fetch.requests()
        return doc

    def universe_rows(self, a=None):
        """scan.py universe: (kept [(SYM, name)], counts, as_of) from the Massive universe rule."""
        from . import universe as U
        res = self._run(U.build_default, getattr(a, "now", None) if a is not None else None)
        return res["kept"], res["counts"], res["as_of"]


def fetch_news(client, symbols, since_utc, limit=50):
    client = _client(client)
    return {s.upper(): json.dumps(client.news(massive_symbol(s), since_utc, limit)) for s in symbols}


def adapter(err):
    return Adapter(err)
