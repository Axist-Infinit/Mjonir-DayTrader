"""The measurement statistics (chunk 2). Stdlib only, Python 3.8 syntax: the trader scripts import this
module on every run, whatever --source is (one definition, P8).

    wilson(k, n, z)                    Wilson score interval (Odyssey replay/stats.py, verbatim)
    decided_rate(outcomes)             k targets of n decided (target or stop) with the Wilson interval
    net_break_even(target_r, cost_r)   the decided target rate that nets zero after costs
    expectancy_ci(rs, seed, draws)     mean R with a seeded percentile-bootstrap 95% interval
    paired_delta_ci(rule, control)     rule minus control, SESSIONS resampled (seeded)
    verdict_history(...)               pass / fail / unverified from the history, fixed wording
    verdict_control(...)               pass / fail / unverified from the paired delta, fixed wording

The break-even: a decided fire wins target_r - cost_r or loses 1 + cost_r (R = the risk a share), so the
target rate that nets zero is p = (1 + cost_r) / (target_r + 1): 50% at 1R with no costs, 56.5% at 1R
with a 0.13 R round trip.

N_FLOOR = 40 is the house's gate count: at p = 0.5 the Wilson half-width is 14.8 points at n = 40, so a
verdict below it says "cannot judge" whatever the point estimate is. No verdict string here reads the
Monte Carlo replays, and none may use the words in BANNED (unit-tested).
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


T_NO_HISTORY = "Cannot judge: no decided fires in this history ({m} fired; none hit the target or the stop)."
T_FLOOR = ("Cannot judge: {k} of {n} decided fires hit the target ({p}, 95% Wilson [{lo}, {hi}]); "
           "n is below the {floor}-fire floor. Net break-even at {r} {basis} is {be}.")
T_STRADDLE = ("Edge not distinguishable from break-even: {k} of {n} decided fires hit the target ({p}, 95% Wilson "
              "[{lo}, {hi}]); net break-even at {r} {basis} is {be}, inside that interval.")
T_BELOW = ("Below break-even: {k} of {n} decided fires hit the target ({p}, 95% Wilson [{lo}, {hi}]); net "
           "break-even at {r} {basis} is {be}, above the whole interval.")
T_ABOVE = ("Above break-even: {k} of {n} decided fires hit the target ({p}, 95% Wilson [{lo}, {hi}]); net "
           "break-even at {r} {basis} is {be}, below the whole interval. A past sample is not a forward result.")
# no target (the plan exits at the stop or at its flat-by close): the net R a trade itself
T_NT_NONE = "Cannot judge: the rule never fired in this history."
T_NT_FLOOR = ("Cannot judge: {n} fires, net average {mean} R a trade (95% bootstrap [{lo}, {hi}]); n is below the "
              "{floor}-fire floor.")
T_NT_STRADDLE = ("Edge not distinguishable from zero: {n} fires, net average {mean} R a trade (95% bootstrap "
                 "[{lo}, {hi}]); the interval includes 0.")
T_NT_BELOW = ("Below zero: {n} fires, net average {mean} R a trade (95% bootstrap [{lo}, {hi}]); the whole interval "
              "is under 0.")
T_NT_ABOVE = ("Above zero: {n} fires, net average {mean} R a trade (95% bootstrap [{lo}, {hi}]); the whole interval "
              "is over 0. A past sample is not a forward result.")


def verdict_history(hist_net, target_r, cost_r, costs_on=True, floor=N_FLOOR):
    """The history verdict. ``hist_net``: {"target": k, "stop": s, "triggered": m, "expectancy":
    expectancy_ci(net R) or None}. With a target: the decided target rate's Wilson interval against the
    net break-even (1 + cost_r) / (target_r + 1). Without one: the net expectancy interval against 0.
    Returns {state pass|fail|unverified, reason, text, ...the numbers}."""
    m = int(hist_net.get("triggered") or 0)
    basis = "after costs" if costs_on else "with costs off"
    if target_r is None:
        ex = hist_net.get("expectancy")
        if not m or not ex:
            return {"state": "unverified", "reason": "no_history", "text": T_NT_NONE, "n": m}
        f = dict(n=ex["n"], mean=_r(ex["mean"]), lo=_r(ex["lo"]), hi=_r(ex["hi"]), floor=floor)
        out = {"n": ex["n"], "mean": ex["mean"], "lo": ex["lo"], "hi": ex["hi"], "basis": "net expectancy vs 0"}
        if ex["n"] < floor:
            return dict(out, state="unverified", reason="n_below_floor", text=T_NT_FLOOR.format(**f))
        if ex["hi"] < 0:
            return dict(out, state="fail", reason="below", text=T_NT_BELOW.format(**f))
        if ex["lo"] > 0:
            return dict(out, state="pass", reason="above", text=T_NT_ABOVE.format(**f))
        return dict(out, state="unverified", reason="straddles", text=T_NT_STRADDLE.format(**f))
    k = int(hist_net.get("target") or 0)
    n = k + int(hist_net.get("stop") or 0)
    if n == 0:
        return {"state": "unverified", "reason": "no_history", "text": T_NO_HISTORY.format(m=m), "k": 0, "n": 0}
    lo, hi = wilson(k, n)
    p = k / n
    be = net_break_even(target_r, cost_r)
    f = dict(k=k, n=n, p=_pct(p), lo=_pct(lo), hi=_pct(hi), floor=floor, r=_multiple(target_r), basis=basis,
             be=_pct(be))
    out = {"k": k, "n": n, "p": p, "wilson": [lo, hi], "break_even": be, "cost_r": cost_r,
           "basis": "decided target rate vs net break-even"}
    if n < floor:
        return dict(out, state="unverified", reason="n_below_floor", text=T_FLOOR.format(**f))
    if hi < be:
        return dict(out, state="fail", reason="below", text=T_BELOW.format(**f))
    if lo > be:
        return dict(out, state="pass", reason="above", text=T_ABOVE.format(**f))
    return dict(out, state="unverified", reason="straddles", text=T_STRADDLE.format(**f))


C_NONE = "Cannot judge against the random-entry control: no session paired a rule trade with a control trade."
C_ABOVE = ("Ahead of the random-entry control: net delta {d} R a trade (95% bootstrap [{lo}, {hi}]) over {m} paired "
           "sessions, {n} decided fires. A past sample is not a forward result.")
C_BELOW = ("Behind the random-entry control: net delta {d} R a trade (95% bootstrap [{lo}, {hi}]) over {m} paired "
           "sessions.")
C_FLOOR = ("Cannot judge against the random-entry control: net delta {d} R a trade (95% bootstrap [{lo}, {hi}]) over "
           "{m} paired sessions; {n} decided fires is below the {floor}-fire floor.")
C_STRADDLE = ("Not distinguishable from the random-entry control: net delta {d} R a trade (95% bootstrap "
              "[{lo}, {hi}]) over {m} paired sessions; the interval includes 0.")


def verdict_control(delta, n_decided, floor=N_FLOOR):
    """pass when delta.lo > 0 and the decided n >= floor; fail when delta.hi < 0; else unverified.
    ``delta`` is paired_delta_ci(...) or None (no paired session)."""
    if not delta:
        return {"state": "unverified", "reason": "no_control", "text": C_NONE}
    f = dict(d=_r(delta["delta"]), lo=_r(delta["lo"]), hi=_r(delta["hi"]), m=delta["n_sessions"], n=n_decided,
             floor=floor)
    out = {"delta": delta["delta"], "lo": delta["lo"], "hi": delta["hi"], "n_sessions": delta["n_sessions"],
           "n_decided": n_decided}
    if delta["lo"] > 0 and n_decided >= floor:
        return dict(out, state="pass", reason="above", text=C_ABOVE.format(**f))
    if delta["hi"] < 0:
        return dict(out, state="fail", reason="below", text=C_BELOW.format(**f))
    if delta["lo"] > 0:
        return dict(out, state="unverified", reason="n_below_floor", text=C_FLOOR.format(**f))
    return dict(out, state="unverified", reason="straddles", text=C_STRADDLE.format(**f))


def all_templates():
    """Every verdict template, for the banned-words test."""
    return [T_NO_HISTORY, T_FLOOR, T_STRADDLE, T_BELOW, T_ABOVE, T_NT_NONE, T_NT_FLOOR, T_NT_STRADDLE, T_NT_BELOW,
            T_NT_ABOVE, C_NONE, C_ABOVE, C_BELOW, C_FLOOR, C_STRADDLE]
