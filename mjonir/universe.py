"""The tradable universe from Massive: common stocks and ADRs over a price and a liquidity floor.

    build(client, cal, as_of, min_price, min_adv_usd, sessions=20, types=("CS", "ADRC"))

1. Two VERIFIED reference walks, one per type (``/v3/reference/tickers?market=stocks&active=true&type=``),
   each refused when it paginated short, overlapped, ignored the filter or came back under a sanity
   floor (``massive.check_reference``, ported from Odyssey, P11).
2. `sessions` VERIFIED grouped-daily answers ending ``as_of`` (``massive.check_grouped``: no cursor,
   count matches, SPY printed, every row that day), cached once complete. A day holding fewer than
   90% of the window's median rows is a partial answer and refused.
3. The funnel, in order: upstream's ``TICKER`` rule (1 to 5 letters, or 1 to 4 plus one class letter
   after a dot), a print on ``as_of``, last close >= ``min_price``, ADV$ = mean(close x volume) over
   the window (a missing day counts as 0) >= ``min_adv_usd``. OTC is out (market=stocks, and
   grouped with include_otc=false).

Floors live in trader/config.json (``universe.min_price`` 5, ``universe.min_adv_usd`` 20,000,000),
the same defaults here; never typed into a SKILL.md. Output: ``SYM|Name`` lines sorted (what
``scan.read_symbols`` reads) and a funnel record ``trader/data/universe/<as_of>.json``.
"""

import json
import os
import re
import statistics

from . import calendar as K
from . import config as C
from . import massive as M

TICKER = re.compile(r"^[A-Z]{1,5}$|^[A-Z]{1,4}\.[A-Z]$")   # scan.py's own rule
DEFAULT_MIN_PRICE = 5.0
DEFAULT_MIN_ADV_USD = 20000000.0
DEFAULT_SESSIONS = 20
DEFAULT_TYPES = ("CS", "ADRC")
#: Sanity floors under each walk (2026-11-02: about 5,400 CS and 390 ADRC active rows).
MIN_REFERENCE_ROWS = {"CS": 3000, "ADRC": 100}
GROUPED_MIN_SHARE = 0.9


def floors(cfg=None):
    cfg = C.trader_config() if cfg is None else cfg
    return (float(C.config_value(cfg, "universe.min_price", DEFAULT_MIN_PRICE)),
            float(C.config_value(cfg, "universe.min_adv_usd", DEFAULT_MIN_ADV_USD)))


def _grouped(client, day, cache):
    from .yahoo_shape import grouped_day
    return grouped_day(client, day, cache)


def build(client, cal, as_of=None, min_price=DEFAULT_MIN_PRICE, min_adv_usd=DEFAULT_MIN_ADV_USD,
          sessions=DEFAULT_SESSIONS, types=DEFAULT_TYPES, cache=None, clock=None, min_rows=None):
    """{"kept": [(SYM, name)], "counts": {...}, "as_of", "record"} or `massive.Refused`."""
    as_of = K.as_date(as_of) if as_of else cal.last_complete_session(clock)
    if not cal.is_session(as_of):
        raise M.Refused("universe as of %s: not a session (%s)" % (as_of, cal.why_closed(as_of)))
    min_rows = MIN_REFERENCE_ROWS if min_rows is None else min_rows
    refs, walks = {}, []
    for ty in types:
        rows, meta = M.check_reference(client.reference_pages({"type": ty}), want_type=ty,
                                       min_rows=min_rows.get(ty, 1))
        walks.append(meta)
        for t, r in rows.items():
            refs.setdefault(t, r)
    days = cal.sessions_back(as_of, int(sessions))
    grouped = {d: _grouped(client, d, cache) for d in days}
    med = statistics.median(len(g) for g in grouped.values())
    for d, g in grouped.items():
        if len(g) < GROUPED_MIN_SHARE * med:
            raise M.Refused("grouped %s: %d rows, under %d%% of the window's median %d; a partial answer, not "
                            "the market" % (d, len(g), int(GROUPED_MIN_SHARE * 100), med))
    label_price = "price under $%s" % _fmt(min_price)
    label_adv = "ADV$ under $%s" % _fmt(min_adv_usd)
    counts = {"rows": len(refs), "not a plain ticker": 0, "no print on %s" % as_of: 0, label_price: 0,
              label_adv: 0, "keep": 0}
    kept, detail = [], {}
    last = grouped[as_of]
    for t in sorted(refs):
        if not TICKER.match(t):
            counts["not a plain ticker"] += 1
            continue
        row = last.get(t)
        if not row or row.get("c") is None:
            counts["no print on %s" % as_of] += 1
            continue
        if row["c"] < min_price:
            counts[label_price] += 1
            continue
        adv = sum((g[t]["c"] or 0) * (g[t]["v"] or 0) for g in grouped.values() if t in g) / float(len(days))
        if adv < min_adv_usd:
            counts[label_adv] += 1
            continue
        counts["keep"] += 1
        kept.append((t, refs[t]["name"] or t))
        detail[t] = {"type": refs[t]["type"], "close": row["c"], "adv_usd": round(adv),
                     "sessions_present": sum(1 for g in grouped.values() if t in g)}
    if not kept:
        raise M.Refused("universe as of %s: nothing cleared the floors" % as_of)
    record = {"created_by": "mjonir.universe", "as_of": as_of.isoformat(), "generated_at": K.now_et(clock).astimezone(
        K.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "rule": {"types": list(types), "min_price": min_price,
                                                         "min_adv_usd": min_adv_usd, "sessions": len(days),
                                                         "ticker_rule": TICKER.pattern, "otc": "excluded"},
              "window": {"from": days[0].isoformat(), "to": days[-1].isoformat(),
                         "grouped_rows": {d.isoformat(): len(g) for d, g in grouped.items()}},
              "reference_walks": walks, "funnel": counts, "kept": len(kept), "names": detail}
    return {"kept": kept, "counts": counts, "as_of": as_of.isoformat(), "record": record}


def _fmt(x):
    x = float(x)
    if x >= 1e6 and x % 1e6 == 0:
        return "%dM" % int(x // 1e6)
    return ("%d" % x) if x == int(x) else "%.2f" % x


def universe_text(kept):
    return "".join("%s|%s\n" % (s, n) for s, n in sorted(kept))


def write(result, out="trader/universe.txt", record_dir=None):
    """Write SYM|Name lines and the funnel record. Returns (out, record_path)."""
    d = os.path.dirname(out)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(universe_text(result["kept"]))
    rd = record_dir or os.path.join(str(C.data_dir()), "universe")
    os.makedirs(rd, exist_ok=True)
    rp = os.path.join(rd, "%s.json" % result["as_of"])
    with open(rp, "w", encoding="utf-8") as fh:
        json.dump(result["record"], fh, indent=1)
        fh.write("\n")
    return out, rp


def build_default(now_text=None, client=None, cal=None, cache=None):
    """The rule with the config's floors, the default client, calendar and cache (scan.py universe)."""
    from . import cache as CA
    cal = cal or K.Calendar.load()
    client = client or M.Client()
    own = cache is None
    cache = cache or CA.Cache()
    try:
        mp, ma = floors()
        return build(client, cal, None, mp, ma, cache=cache, clock=now_text)
    finally:
        if own:
            cache.close()
