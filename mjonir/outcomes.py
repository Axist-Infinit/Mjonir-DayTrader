"""The ONE place a trade's outcome is computed (chunk 2). Stdlib only, Python 3.8 syntax.

    touch(o, h, l, stop, target, long, gap_fill)   one bar: ('stop', fill) | ('target', fill) | None
    score_trade(bars, k, entry, stop, target, last, cost_r, fill, gap_fill, long)

The time machine's Monte Carlo loop, its history, the random-entry control, the baseline and (chunk 3)
the forward record all call these two; nothing else compares a price with a stop or a target.

Rules, for a long (a short mirrors them):
  * the trade is entered at the close of bar k; bars k+1 .. last are walked in order;
  * the stop is checked FIRST in every bar: a bar that touches both counts as the stop (we cannot see
    the order inside a bar, so the conservative call);
  * a bar that OPENS through the stop fills at that open (gap_fill "open", the default: gross below
    -1R); gap_fill "stop" fills at the stop (upstream's exact -1R);
  * the target fills at the target;
  * target None: only the stop or the close;
  * nothing hit by bar `last`: "close", out at that bar's close (fill="close") or at a price you pass
    (fill=<float>, e.g. the daily bar's official close).

The touch margins (amendment b): over the bars after the entry up to the exit bar, how far the price
went beyond the target (high - target for a long) and beyond the stop (stop - low for a long), in
dollars and in R. A DECIDED fire (target or stop) whose deciding margin is under FRAGILE_R (0.05 R) is
"fragile": a cent or two of entry, stop or vendor difference could flip it.
"""

FRAGILE_R = 0.05
GAP_FILLS = ("open", "stop")


def ohlc(bar):
    """(o, h, l, c) from a bar dict {o,h,l,c}, a bars_5m tuple (t, o, h, l, c, v) or an (o, h, l, c)."""
    if isinstance(bar, dict):
        return bar["o"], bar["h"], bar["l"], bar["c"]
    if len(bar) >= 6:
        return bar[1], bar[2], bar[3], bar[4]
    return bar[0], bar[1], bar[2], bar[3]


def touch(o, h, l, stop, target, long=True, gap_fill="open"):
    """The exit inside one bar, or None. The stop is checked first."""
    if long:
        if l <= stop:
            return "stop", (o if (gap_fill == "open" and o < stop) else stop)
        if target is not None and h >= target:
            return "target", target
    else:
        if h >= stop:
            return "stop", (o if (gap_fill == "open" and o > stop) else stop)
        if target is not None and l <= target:
            return "target", target
    return None


def score_trade(bars, k, entry, stop, target, last, cost_r=0.0, fill="close", gap_fill="open", long=True):
    """One trade entered at the close of bars[k], walked through bars[last]. Returns
    {outcome target|stop|close, exit_bar, exit_price, gross_r, net_r, cost_r, mfe_r, mae_r, gap,
     margin_target, margin_target_r, margin_stop, margin_stop_r, decision_margin_r, fragile}.
    R is per the entry's risk (entry - stop for a long); net_r = gross_r - cost_r (cost applied once)."""
    if not bars:
        raise ValueError("score_trade needs bars (P10): an empty bar list is never scored")
    if gap_fill not in GAP_FILLS:
        raise ValueError("gap_fill is open or stop, not %r" % (gap_fill,))
    if not 0 <= k <= last < len(bars):
        raise ValueError("score_trade needs 0 <= k (%s) <= last (%s) < %d bars" % (k, last, len(bars)))
    risk = (entry - stop) if long else (stop - entry)
    if not risk > 0:
        raise ValueError("the stop %r is not on the losing side of the entry %r" % (stop, entry))
    sign = 1.0 if long else -1.0
    outcome = exit_price = None
    exit_bar = last
    hi = lo = None
    gap = False
    for i in range(k + 1, last + 1):
        o, h, l, c = ohlc(bars[i])
        hi = h if hi is None else max(hi, h)
        lo = l if lo is None else min(lo, l)
        t = touch(o, h, l, stop, target, long, gap_fill)
        if t is not None:
            outcome, exit_price = t
            exit_bar = i
            gap = outcome == "stop" and exit_price != stop
            break
    if outcome is None:
        outcome = "close"
        exit_price = ohlc(bars[last])[3] if fill == "close" else float(fill)
    gross = sign * (exit_price - entry) / risk
    if hi is None:              # entered on the last bar: nothing walked
        hi = lo = entry
    best, worst = (hi, lo) if long else (lo, hi)
    m_target = None if target is None else sign * (best - target)
    m_stop = sign * (stop - worst)
    out = {
        "outcome": outcome, "exit_bar": exit_bar, "exit_price": exit_price, "gross_r": gross,
        "net_r": gross - cost_r, "cost_r": cost_r, "gap": gap,
        "mfe_r": sign * (best - entry) / risk, "mae_r": sign * (worst - entry) / risk,
        "margin_target": m_target, "margin_target_r": None if m_target is None else m_target / risk,
        "margin_stop": m_stop, "margin_stop_r": m_stop / risk,
    }
    dm = out["margin_target_r"] if outcome == "target" else out["margin_stop_r"] if outcome == "stop" else None
    out["decision_margin_r"] = dm
    out["fragile"] = dm is not None and dm < FRAGILE_R
    return out
