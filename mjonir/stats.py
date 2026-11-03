"""The measurement statistics (chunk 2). Stdlib only, Python 3.8 syntax: the trader scripts import this
module on every run, whatever --source is (one definition, P8).

    wilson(k, n, z)                    Wilson score interval (Odyssey replay/stats.py, verbatim)
    decided_rate(outcomes)             k targets of n decided (target or stop) with the Wilson interval
    net_break_even(target_r, cost_r)   the decided target rate that nets zero after costs
    expectancy_ci(rs, seed, draws)     mean R with a seeded percentile-bootstrap 95% interval
    paired_delta_ci(rule, control)     rule minus control, SESSIONS resampled (seeded)
    verdict_history(...)               pass / fail / unverified from the net expectancy interval (all fires)
    verdict_control(...)               pass / fail / unverified from the paired delta, floored on its sessions

The break-even: a decided fire wins target_r - cost_r or loses 1 + cost_r (R = the risk a share), so the
target rate that nets zero is p = (1 + cost_r) / (target_r + 1): 50% at 1R with no costs, 56.5% at 1R
with a 0.13 R round trip.

N_FLOOR = 40 is the house's gate count: at p = 0.5 the Wilson half-width is 14.8 points at n = 40, so a
verdict below it says "cannot judge" whatever the point estimate is. Both verdicts read the statistic the
money gate reads (the history: the net expectancy interval over every fire; the control: the paired
delta, floored on its own paired sessions); the decided rate is a diagnostic beside it. No verdict string
here reads the Monte Carlo replays, and none may use the words in BANNED (unit-tested).
"""

import math
import random
import re

N_FLOOR = 40
FRAGILE_R = 0.05        # a decided fire whose deciding touch cleared its level by under 0.05 R
DRAWS = 2000
SEED = 19
LEVEL = 0.95
# Words no verdict may use. "edge" is banned bare: the only use allowed is the fixed negation
# "edge not distinguishable from ..." in the straddle templates below.
BANNED = (re.compile(r"coin flip", re.I), re.compile(r"\bleans?\b", re.I), re.compile(r"\bstrongly\b", re.I),
          re.compile(r"profit", re.I), re.compile(r"\bedge\b(?! not distinguishable from)", re.I))


def banned_words(text):
    """The banned patterns found in a verdict string (empty = clean)."""
    return [p.pattern for p in BANNED if p.search(text or "")]


# ---------------------------------------------------------------- intervals

def wilson(successes, n, z=1.96):
    """Binomial CI that stays inside [0,1] and stays honest at small n."""
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, centre - half), min(1.0, centre + half))


def decided_rate(outcomes):
    """Over target / stop outcomes only ("close" is not decided): {k, n, p, lo, hi}; p, lo, hi are None
    when nothing was decided."""
    outs = list(outcomes)
    k = sum(1 for o in outs if o == "target")
    n = k + sum(1 for o in outs if o == "stop")
    if n == 0:
        return {"k": 0, "n": 0, "p": None, "lo": None, "hi": None}
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "p": k / n, "lo": lo, "hi": hi}


def net_break_even(target_r, cost_r):
    """The decided target rate that nets zero: (1 + cost_r) / (target_r + 1)."""
    return (1.0 + cost_r) / (target_r + 1.0)


def _quantile(sorted_values, q):
    """Linear interpolation between order statistics at q x (m - 1)."""
    m = len(sorted_values)
    if m == 1:
        return sorted_values[0]
    pos = q * (m - 1)
    i = int(math.floor(pos))
    if i >= m - 1:
        return sorted_values[-1]
    frac = pos - i
    return sorted_values[i] + (sorted_values[i + 1] - sorted_values[i]) * frac


def _bootstrap_means(values, seed, draws):
    rng = random.Random(seed)
    n = len(values)
    out = [sum(rng.choices(values, k=n)) / n for _ in range(draws)]
    out.sort()
    return out


def expectancy_ci(rs, seed=SEED, draws=DRAWS):
    """Mean R and its percentile-bootstrap 95% interval: {n, mean, lo, hi, draws, seed}. The same rs, seed
    and draws give the same interval on any machine. An empty list raises (P10): nothing is averaged
    without trades."""
    vals = [float(r) for r in rs]
    if not vals:
        raise ValueError("expectancy_ci needs at least one trade")
    means = _bootstrap_means(vals, seed, int(draws))
    a = (1.0 - LEVEL) / 2.0
    return {"n": len(vals), "mean": sum(vals) / len(vals), "lo": _quantile(means, a),
            "hi": _quantile(means, 1.0 - a), "draws": int(draws), "seed": seed}


def _as_list(v):
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return [float(x) for x in v]
    return [float(v)]


def paired_delta_ci(rule_by_session, control_by_session, seed=SEED, draws=DRAWS):
    """Rule minus control over the sessions both hold, SESSIONS resampled together (so a session's rule
    trade and its control draws stay paired). Per session: mean(rule R) - mean(control R). Returns
    {n_sessions, delta, lo, hi, rule_mean, control_mean, draws, seed}; raises when no session pairs."""
    keys = sorted(k for k in rule_by_session
                  if _as_list(rule_by_session.get(k)) and _as_list(control_by_session.get(k)))
    if not keys:
        raise ValueError("paired_delta_ci needs at least one session with both a rule and a control trade")
    rule = [sum(_as_list(rule_by_session[k])) / len(_as_list(rule_by_session[k])) for k in keys]
    ctrl = [sum(_as_list(control_by_session[k])) / len(_as_list(control_by_session[k])) for k in keys]
    deltas = [r - c for r, c in zip(rule, ctrl)]
    means = _bootstrap_means(deltas, seed, int(draws))
    a = (1.0 - LEVEL) / 2.0
    n = len(keys)
    return {"n_sessions": n, "delta": sum(deltas) / n, "lo": _quantile(means, a), "hi": _quantile(means, 1.0 - a),
            "rule_mean": sum(rule) / n, "control_mean": sum(ctrl) / n, "draws": int(draws), "seed": seed}


# ---------------------------------------------------------------- verdicts (fixed wording)

def _pct(x):
    return "%.1f%%" % (100.0 * x)


def _r(x):
    return "%+.3f" % x


def _multiple(target_r):
    return "%gR" % round(float(target_r), 2)


# The history verdict reads ONE statistic, the gate's own: the net expectancy interval over every fire
# against 0. The decided rate is appended as a diagnostic for a plan with a target; it never sets the state.
T_NONE = "Cannot judge: the rule never fired in this history."
T_FLOOR = ("Cannot judge: {n} fires, net average {mean} R a trade (95% bootstrap [{lo}, {hi}]); n is below the "
           "{floor}-fire floor.{decided}")
T_BELOW = ("Below zero: {n} fires, net average {mean} R a trade (95% bootstrap [{lo}, {hi}]); the whole interval "
           "is under 0.{decided}")
T_ABOVE = ("Above zero: {n} fires, net average {mean} R a trade (95% bootstrap [{lo}, {hi}]); the whole interval "
           "is over 0.{decided} A past sample is not a forward result.")
T_STRADDLE = ("Edge not distinguishable from zero: {n} fires, net average {mean} R a trade (95% bootstrap "
              "[{lo}, {hi}]); the interval includes 0.{decided}")
D_LINE = (" Decided: {k} of {nd} hit the target ({p}, 95% Wilson [{wlo}, {whi}]) against a net break-even of {be} "
          "at {r} after costs (the history's own mean round trip, {cr} R).")
D_LINE_OFF = (" Decided: {k} of {nd} hit the target ({p}, 95% Wilson [{wlo}, {whi}]) against a break-even of {be} "
              "at {r} with costs off.")
D_NONE = " No fire was decided; every one exited at the close."


def _decided_line(k, nd, target_r, cost_r, costs_on):
    """The decided-rate diagnostic for a plan with a target: (text, numbers)."""
    if nd == 0:
        return D_NONE, {"k": 0, "n": 0}
    lo, hi = wilson(k, nd)
    be = net_break_even(target_r, cost_r)
    f = dict(k=k, nd=nd, p=_pct(k / nd), wlo=_pct(lo), whi=_pct(hi), be=_pct(be), r=_multiple(target_r),
             cr="%.3f" % cost_r)
    return (D_LINE if costs_on else D_LINE_OFF).format(**f), {
        "k": k, "n": nd, "p": k / nd, "wilson": [lo, hi], "break_even": be, "cost_r": cost_r}


def verdict_history(hist_net, target_r, cost_r, costs_on=True, floor=N_FLOOR):
    """The history verdict, one statistic: the net expectancy interval over ALL fires against 0.
    ``hist_net``: {"triggered": m, "target": k, "stop": s, "expectancy": expectancy_ci(net R) or None};
    ``cost_r``: the history's own mean round trip in R (the break-even in the decided diagnostic).
    States: no fires -> unverified/no_history; n < floor -> unverified/n_below_floor; hi < 0 -> fail/below;
    lo > 0 -> pass/above; else unverified/straddles. With a target the decided rate (Wilson against the net
    break-even (1 + cost_r) / (target_r + 1)) is appended and never sets the state.
    Returns {state, reason, text, n, mean, lo, hi, basis, decided}."""
    m = int(hist_net.get("triggered") or 0)
    ex = hist_net.get("expectancy")
    if not m or not ex:
        return {"state": "unverified", "reason": "no_history", "text": T_NONE, "n": 0, "decided": None,
                "basis": "net expectancy vs 0"}
    decided, numbers = "", None
    if target_r is not None:
        k = int(hist_net.get("target") or 0)
        decided, numbers = _decided_line(k, k + int(hist_net.get("stop") or 0), target_r, cost_r, costs_on)
    f = dict(n=ex["n"], mean=_r(ex["mean"]), lo=_r(ex["lo"]), hi=_r(ex["hi"]), floor=floor, decided=decided)
    out = {"n": ex["n"], "mean": ex["mean"], "lo": ex["lo"], "hi": ex["hi"], "basis": "net expectancy vs 0",
           "decided": numbers, "cost_r": cost_r}
    if ex["n"] < floor:
        return dict(out, state="unverified", reason="n_below_floor", text=T_FLOOR.format(**f))
    if ex["hi"] < 0:
        return dict(out, state="fail", reason="below", text=T_BELOW.format(**f))
    if ex["lo"] > 0:
        return dict(out, state="pass", reason="above", text=T_ABOVE.format(**f))
    return dict(out, state="unverified", reason="straddles", text=T_STRADDLE.format(**f))


C_NONE = "Cannot judge against the random-entry control: no session paired a rule trade with a control trade."
C_FLOOR = ("Cannot judge against the random-entry control: net delta {d} R a trade (95% bootstrap [{lo}, {hi}]) over "
           "{m} paired sessions; {m} is below the {floor}-session floor.")
C_BELOW = ("Behind the random-entry control: net delta {d} R a trade (95% bootstrap [{lo}, {hi}]) over {m} paired "
           "sessions; the whole interval is under 0.")
C_ABOVE = ("Ahead of the random-entry control: net delta {d} R a trade (95% bootstrap [{lo}, {hi}]) over {m} paired "
           "sessions; the whole interval is over 0. A past sample is not a forward result.")
C_STRADDLE = ("Not distinguishable from the random-entry control: net delta {d} R a trade (95% bootstrap "
              "[{lo}, {hi}]) over {m} paired sessions; the interval includes 0.")


def verdict_control(delta, floor=N_FLOOR):
    """The control verdict, floored on the bootstrap's own n (the paired sessions m): no delta ->
    unverified/no_control; m < floor -> unverified/n_below_floor (either sign); hi < 0 -> fail/below;
    lo > 0 -> pass/above; else unverified/straddles. ``delta`` is paired_delta_ci(...) or None."""
    if not delta:
        return {"state": "unverified", "reason": "no_control", "text": C_NONE}
    m = delta["n_sessions"]
    f = dict(d=_r(delta["delta"]), lo=_r(delta["lo"]), hi=_r(delta["hi"]), m=m, floor=floor)
    out = {"delta": delta["delta"], "lo": delta["lo"], "hi": delta["hi"], "n_sessions": m}
    if m < floor:
        return dict(out, state="unverified", reason="n_below_floor", text=C_FLOOR.format(**f))
    if delta["hi"] < 0:
        return dict(out, state="fail", reason="below", text=C_BELOW.format(**f))
    if delta["lo"] > 0:
        return dict(out, state="pass", reason="above", text=C_ABOVE.format(**f))
    return dict(out, state="unverified", reason="straddles", text=C_STRADDLE.format(**f))


# The by-year reading (docs/PREREG_RVOL_ORB.md criterion 3): every calendar year with at least `floor` fires has
# a net mean above 0. No year at the floor is unverified, never a pass. And the sign-flip note beside a by-year table.
Y_NONE = "Cannot judge the years: no calendar year holds {floor} fires."
Y_ABOVE = "Every calendar year with at least {floor} fires has a net mean above 0 ({years})."
Y_BELOW = "A calendar year with at least {floor} fires has a net mean at or under 0 ({years})."
Y_FLIP = "The sign of the net average flips between years: {years}."


def verdict_years(means, floor=N_FLOOR):
    """``means``: {year: (n, net mean)}. no year with n >= floor -> unverified/no_year_at_floor; any such year with a
    mean at or under 0 -> fail/below (those years); else pass/above (the years counted).
    Returns {state, reason, years, text}."""
    at = dict((y, m) for y, (n, m) in means.items() if n >= floor)
    if not at:
        return {"state": "unverified", "reason": "no_year_at_floor", "years": [], "text": Y_NONE.format(floor=floor)}
    bad = sorted(y for y, m in at.items() if not m > 0)
    if bad:
        return {"state": "fail", "reason": "below", "years": bad,
                "text": Y_BELOW.format(floor=floor, years=", ".join(bad))}
    return {"state": "pass", "reason": "above", "years": sorted(at),
            "text": Y_ABOVE.format(floor=floor, years=", ".join(sorted(at)))}


def sign_flip_note(means):
    """``means``: {year: (n, net mean)}. The Y_FLIP note when the net mean's sign differs between years (a zero mean
    has no sign), else None."""
    signs = dict((y, m > 0) for y, (n, m) in means.items() if m is not None and m != 0)
    if len(set(signs.values())) < 2:
        return None
    return Y_FLIP.format(years=", ".join("%s %s (n %d)" % (y, _r(means[y][1]), means[y][0]) for y in sorted(signs)))


def all_templates():
    """Every verdict template, for the banned-words test."""
    return [T_NONE, T_FLOOR, T_BELOW, T_ABOVE, T_STRADDLE, D_LINE, D_LINE_OFF, D_NONE, C_NONE, C_FLOOR, C_BELOW,
            C_ABOVE, C_STRADDLE, Y_NONE, Y_ABOVE, Y_BELOW, Y_FLIP]
