"""Bars for the measurement layer (chunk 2 consumes these). Stdlib only.

    bars_5m(symbol, start, end, rth_only=True) -> [(t_ms, o, h, l, c, v)]   ascending, complete bars only
    daily(symbol, start, end)                  -> [(t_ms, o, h, l, c, v)]   one row a session, adjusted
    adv_usd(symbol, asof, n=20)                -> mean(close x volume) over the n sessions STRICTLY before asof
    quote(symbol)                              -> {bid, ask, t_ms} | None   (None: could not ask; never 0)

Every list function raises ``DataError`` on an empty answer (P10): an empty bar list is never scored.
``t_ms`` is the bar START in milliseconds. A forming bar is never returned.
"""

import statistics

from . import calendar as K
from . import localstores as LS
from . import massive as M
from .yahoo_shape import _AUTO, DataError, _cache, _cal, _client, massive_symbol, range_rows


class InsufficientData(DataError):
    """Fewer sessions than asked (a recent listing, a long halt): excluded and counted, never padded."""


def _tuples(rows):
    return [(int(r["t"]), r["o"], r["h"], r["l"], r["c"], r["v"]) for r in rows]


def bars_5m(symbol, start, end, rth_only=True, client=None, cal=None, source="auto", cache=_AUTO):
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
        rows = LS.kalex_5m(sym, sessions[0], sessions[-1])
    elif source == "flatfile":
        rows = LS.flatfile_bulk([sym], sessions)[sym]
    elif source == "api":
        client = _client(client)
        cache = _cache(cache)
        try:
            rows = range_rows(client, cal, symbol, sessions, "5m", cache)
        finally:
            if cache is not None:
                cache.close()
    else:
        raise DataError("source is auto, api, kalex or flatfile, not %r" % source)
    now_ms = K.ms_of(K.now_et())
    rows = [r for r in rows if r["t"] + 300000 <= now_ms]          # complete bars only
    if rth_only:
        rows = cal.rth_filter(rows)
    if not rows:
        raise DataError("no 5-minute bars for %s between %s and %s" % (symbol, start, end))
    return _tuples(rows)


def daily(symbol, start, end, client=None, cal=None, cache=_AUTO):
    """Adjusted daily bars of COMPLETE sessions from start to end."""
    cal = _cal(cal)
    today = K.today_et()
    sessions = [d for d in cal.sessions_between(start, end) if d < today or
                K.now_et() >= cal.session_bounds(d)[1]]
    if not sessions:
        raise DataError("no complete session between %s and %s" % (start, end))
    client = _client(client)
    cache = _cache(cache)
    try:
        rows = range_rows(client, cal, symbol, sessions, "1d", cache)
    finally:
        if cache is not None:
            cache.close()
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
