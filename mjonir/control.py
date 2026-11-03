"""The random-entry control and the baseline (chunk 2). Stdlib only, Python 3.8 syntax.

The control asks: does the rule's entry bar beat a random bar of the SAME session, traded the same way?
For every session where the rule fired, K control trades are drawn:

  * eligible bars: after the opening range (index >= n_or), inside the entry window (index <= the last
    bar the rule could enter on) and before `last` (at least one bar left to walk);
  * one bar j per draw from a per-session generator seeded "%s:%s:%s" % (seed, symbol, date): identifiers
    only, so the draws do not depend on the order sessions are visited, and deleting a session leaves
    every other session's draws unchanged;
  * entry at bar j's close; the rule's own risk distance as a percent of the entry on that session
    (stop = rule stop x close_j / rule entry, so on the rule's own bar it IS the rule's stop); the same
    target multiple (target = entry + R x risk); the same last bar (the flat-by);
  * scored by outcomes.score_trade with the same costs and gap fill as the rule;
  * skipped and counted: the rule's risk under the 0.05% floor (exit.py refuses such a stop), or no
    eligible bar.

The baseline ("buy any morning strength"): the close of the last opening-range bar on EVERY session, the
same stop rule and target multiple. A diagnostic, never a verdict.
"""

import random

from . import outcomes as O

RISK_FLOOR_PCT = 0.05


def session_rng(seed, symbol, date):
    """The per-session generator: seeded by identifiers only."""
    return random.Random("%s:%s:%s" % (seed, symbol, date))


def eligible_bars(n_or, last, entry_until=None):
    """Bar indexes a control may enter on: n_or .. min(entry_until, last - 1)."""
    end = last - 1 if entry_until is None else min(int(entry_until), last - 1)
    return list(range(int(n_or), end + 1))


def control_trade(bars, j, rule_entry, rule_stop, target_r, last, cost_fn=None, gap_fill="open", long=True):
    """The control trade on bar j (see the module docstring). cost_fn(entry, risk) -> cost_r."""
    c = O.ohlc(bars[j])[3]
    stop = rule_stop * (c / rule_entry)
    risk = (c - stop) if long else (stop - c)
    target = None if target_r is None else (c + target_r * risk if long else c - target_r * risk)
    cr = cost_fn(c, risk) if cost_fn else 0.0
    res = O.score_trade(bars, j, c, stop, target, last, cr, gap_fill=gap_fill, long=long)
    res.update(bar=j, entry=c, stop=stop, target=target)
    return res


def draw_controls(bars, symbol, date, seed, draws, n_or, last, rule_entry, rule_stop, target_r, cost_fn=None,
                  gap_fill="open", long=True, entry_until=None, force_bar=None):
    """(trades, skipped) for one session: `draws` control trades, or none with the skip reason counted
    {"risk_floor": n} / {"no_eligible_bar": n}. force_bar pins every draw to one bar (the delta-0 pin)."""
    risk_pct = 100.0 * abs(rule_entry - rule_stop) / rule_entry
    if risk_pct < RISK_FLOOR_PCT:
        return [], {"risk_floor": draws}
    elig = eligible_bars(n_or, last, entry_until)
    if force_bar is None and not elig:
        return [], {"no_eligible_bar": draws}
    rng = session_rng(seed, symbol, date)
    out = []
    for _ in range(int(draws)):
        j = force_bar if force_bar is not None else rng.choice(elig)
        out.append(control_trade(bars, j, rule_entry, rule_stop, target_r, last, cost_fn, gap_fill, long))
    return out, {}


def baseline_entry_bar(n_or):
    """The last opening-range bar: the baseline buys its close."""
    return int(n_or) - 1
