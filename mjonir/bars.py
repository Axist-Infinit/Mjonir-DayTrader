"""Bars for the measurement layer (chunk 2 consumes these). Stdlib only.

    bars_5m(symbol, start, end, rth_only=True, info=None) -> [(t_ms, o, h, l, c, v)]   ascending
    daily(symbol, start, end, info=None)                  -> [(t_ms, o, h, l, c, v)]   one row a session
    adv_usd(symbol, asof, n=20)                -> mean(close x volume) over the n sessions STRICTLY before asof
    quote(symbol)                              -> {bid, ask, t_ms} | None   (None: could not ask; never 0)

Every list function raises ``DataError`` on an empty answer (P10): an empty bar list is never scored.
``t_ms`` is the bar START in milliseconds. A forming bar is never returned: "complete" is judged by the
REAL clock, so a replay pinned to an earlier --now must cut the bars by its own now.

``info`` (a dict, optional) receives where the rows came from, for chunk 2's ``data.source`` stamp:
``{"source": "api" | "cache" | "kalex" | "flatfile", "adjusted": bool, "as_of": "YYYY-MM-DD" | None}``
(``as_of`` is the date the prices are adjusted as of: the oldest fetch for cached rows, the store's
coverage end for Kalex, None for the unadjusted flat files).

Splits: Kalex rows are refused when the symbol split after the store's coverage end (unverified when no
client could ask); cached API rows fetched before a later split are dropped and fetched again.
"""

import statistics

from . import calendar as K
from . import localstores as LS
from . import massive as M
from .yahoo_shape import (_AUTO, DataError, _cache, _cal, _client, kalex_rows_checked, massive_symbol,
                          range_rows)


class InsufficientData(DataError):
    """Fewer sessions than asked (a recent listing, a long halt): excluded and counted, never padded."""


def _tuples(rows):
    return [(int(r["t"]), r["o"], r["h"], r["l"], r["c"], r["v"]) for r in rows]


def _fill(info, **kw):
    if info is not None:
        info.clear()
        info.update(kw)


def _api_rows(client, cal, symbol, sessions, res, cache, info):
    """Range rows through the cache, after dropping cached rows a later split made stale."""
    client = _client(client)
    cache = _cache(cache)
    stats = {}
    try:
        if cache is not None:
            cache.invalidate_split(massive_symbol(symbol), client.splits(symbol=massive_symbol(symbol)))
        rows = range_rows(client, cal, symbol, sessions, res, cache, stats)
    finally:
        if cache is not None:
            cache.close()
    oldest = stats.get("oldest_fetch")   # a UTC stamp: the New York date is what as_of speaks
    as_of = (K.parse_now(oldest).date() if oldest else K.today_et()).isoformat()   # fresh rows are today's
    _fill(info, source="api" if stats.get("requests") else "cache", adjusted=True, as_of=as_of)
    return rows


def bars_5m(symbol, start, end, rth_only=True, client=None, cal=None, source="auto", cache=_AUTO, info=None):
    cal = _cal(cal)
    sessions = cal.sessions_between(start, end)
    if not sessions:
        raise DataError("no session between %s and %s" % (start, end))
    sym = massive_symbol(symbol)
    if source == "auto":
        try:
            cov = LS.kalex_coverage(sym)
        except Exception:   # unreadable store: not this source
            cov = None
        source = "kalex" if cov and cov["first_day"] <= sessions[0].isoformat() and \
            sessions[-1].isoformat() <= cov["last_day"] else "api"
    if source == "kalex":
        rows, cov = kalex_rows_checked(client, symbol, sessions)
        _fill(info, source="kalex", adjusted=True, as_of=cov["last_day"])
    elif source == "flatfile":
        rows = LS.flatfile_bulk([sym], sessions)[sym]
        _fill(info, source="flatfile", adjusted=False, as_of=None)
    elif source == "api":
        rows = _api_rows(client, cal, symbol, sessions, "5m", cache, info)
    else:
        raise DataError("source is auto, api, kalex or flatfile, not %r" % source)
    now_ms = K.ms_of(K.now_et())
    rows = [r for r in rows if r["t"] + 300000 <= now_ms]          # complete bars only
    if rth_only:
        rows = cal.rth_filter(rows)
    if not rows:
        raise DataError("no 5-minute bars for %s between %s and %s" % (symbol, start, end))
    return _tuples(rows)


def daily(symbol, start, end, client=None, cal=None, cache=_AUTO, info=None):
    """Adjusted daily bars of COMPLETE sessions (by the real clock) from start to end."""
    cal = _cal(cal)
    today = K.today_et()
    sessions = [d for d in cal.sessions_between(start, end) if d < today or
                K.now_et() >= cal.session_bounds(d)[1]]
    if not sessions:
        raise DataError("no complete session between %s and %s" % (start, end))
    rows = _api_rows(client, cal, symbol, sessions, "1d", cache, info)
    if not rows:
        raise DataError("no daily bars for %s between %s and %s" % (symbol, start, end))
    return _tuples(rows)


def adv_usd(symbol, asof, n=20, client=None, cal=None, cache=_AUTO):
    """Mean dollar volume over the n sessions STRICTLY before `asof` (no look-ahead)."""
    cal = _cal(cal)
    days = cal.sessions_back(cal.prev_session(asof), int(n))
    rows = [r for r in daily(symbol, days[0], days[-1], client, cal, cache)
            if days[0] <= K.et_of_ms(r[0]).date() < K.as_date(asof)]
    if len(rows) < n:
        raise InsufficientData("%s has %d of the %d sessions before %s" % (symbol, len(rows), n, asof))
    return statistics.mean(r[4] * r[5] for r in rows[-n:])


def quote(symbol, client=None):
    """{bid, ask, t_ms} from the last NBBO, or None when it could not be asked (P2: never 0)."""
    try:
        return _client(client).quote(massive_symbol(symbol))
    except M.MassiveError:
        return None
