"""Transaction costs (chunk 2). Stdlib only, Python 3.8 syntax: the trader scripts import this module on
every run, whatever --source is (one definition, P8).

The model, per share and per side, for a long (a short mirrors it):

    slippage   the bps of the highest ADV$ floor the name clears (Kalex's _slip_bps_for), from
               costs.slippage_tiers_bps, default [[100M, 4], [30M, 8], [0, 15]]; ADV unknown (no Massive,
               --source yahoo, too few sessions) -> the most expensive tier and the flag adv_unverified
    half spread  the live NBBO half spread in bps when costs.spread_source is "snapshot" and the quote is
               fresh (costs.quote_fresh_seconds), else costs.default_half_spread_bps (3.0) and the spread
               gate is UNVERIFIED; spread_source "default" always uses the default; "none" turns it off
    commission costs.commission_usd per order (default 1.0; E*TRADE charges 0 on stocks, the knob is kept),
               spread over the shares

    side cost a share       price x (slippage + half spread) / 10,000 + commission / shares
    round trip a share      the entry side + the exit side (both priced at the entry: R is per entry risk)
    cost_r                  round trip a share / risk a share         (applied ONCE per trade)
    net R                   gross R - cost_r
    net reward:risk         (target - entry - round trip) / (entry - stop + round trip)

The reel (TSLA 2026-10-19: entry 364.18, risk 5.86, 4 bp tier, 3 bp half spread, $1 commission, 8 shares):
side 364.18 x 7 / 10,000 + 1 / 8 = 0.3799, round trip 0.7599 a share, cost_r 0.130, net reward:risk at 1R
0.770 and at 2R 1.656.

The spread gate: the FULL spread (2 x half) in dollars against costs.spread_max_frac_of_risk (0.10) of the
risk a share: pass under it, block over it, unverified when the spread was not measured live (P2: three
outcomes; could-not-ask is never 0).
"""

import math

DEFAULTS = {
    "slippage_tiers_bps": [[100000000, 4], [30000000, 8], [0, 15]],
    "commission_usd": 1.0,
    "spread_source": "snapshot",
    "default_half_spread_bps": 3.0,
    "quote_fresh_seconds": 60,
    "spread_max_frac_of_risk": 0.10,
    "spread_unverified": "warn",
}
#: Costs switched off by configuration (upstream's mechanics): zero tiers, no commission, no spread.
OFF = {"slippage_tiers_bps": [[0, 0]], "commission_usd": 0.0, "spread_source": "none",
       "default_half_spread_bps": 0.0}
SPREAD_SOURCES = ("snapshot", "default", "none")
DEFAULT_MAX_LOSS_USD = 50.0     # upstream's max_loss_per_trade_usd default: the share basis for a plan


class CostError(ValueError):
    pass


def settings(cfg=None):
    """The costs block merged over DEFAULTS. ``cfg`` is a whole trader config (with a "costs" key) or the
    block itself. Bad values raise CostError with the key."""
    block = {}
    if isinstance(cfg, dict):
        block = cfg.get("costs") if isinstance(cfg.get("costs"), dict) else (
            cfg if any(k in DEFAULTS for k in cfg) else {})
    s = dict(DEFAULTS)
    s.update({k: v for k, v in block.items() if v is not None})
    try:
        tiers = [[float(f), float(b)] for f, b in s["slippage_tiers_bps"]]
    except (TypeError, ValueError):
        raise CostError("costs.slippage_tiers_bps wants [[min_adv_usd, bps], ...], got %r" % (s["slippage_tiers_bps"],))
    if not tiers or any(b < 0 or f < 0 for f, b in tiers):
        raise CostError("costs.slippage_tiers_bps needs at least one [floor, bps] pair, none negative")
    s["slippage_tiers_bps"] = tiers
    for k in ("commission_usd", "default_half_spread_bps", "quote_fresh_seconds", "spread_max_frac_of_risk"):
        try:
            s[k] = float(s[k])
        except (TypeError, ValueError):
            raise CostError("costs.%s must be a number, got %r" % (k, s[k]))
        if s[k] < 0:
            raise CostError("costs.%s must not be negative, got %r" % (k, s[k]))
    if s["spread_source"] not in SPREAD_SOURCES:
        raise CostError("costs.spread_source is snapshot, default or none, not %r" % (s["spread_source"],))
    if s["spread_unverified"] not in ("warn", "block"):
        raise CostError("costs.spread_unverified is warn or block, not %r" % (s["spread_unverified"],))
    return s


def is_off(s):
    """True when the settings cost nothing at all (zero tiers, no commission, no spread)."""
    return (max(b for _, b in s["slippage_tiers_bps"]) == 0 and s["commission_usd"] == 0
            and (s["spread_source"] == "none" or s["default_half_spread_bps"] == 0))


# ---------------------------------------------------------------- the pieces

def tier_bps(adv_usd, tiers):
    """(bps, flag): the bps of the highest floor the name's ADV$ clears. ADV None -> the most expensive
    tier and 'adv_unverified'; ADV under every floor -> the most expensive tier and 'adv_below_tiers'."""
    rows = sorted((float(f), float(b)) for f, b in tiers)
    worst = max(b for _, b in rows)
    if adv_usd is None:
        return worst, "adv_unverified"
    chosen = None
    for floor, bps in rows:
        if float(adv_usd) >= floor:
            chosen = bps
    if chosen is None:
        return worst, "adv_below_tiers"
    return chosen, None


def half_spread_bps(quote, now_ms, fresh_s):
    """(bps, state) from a quote {bid, ask, t_ms}: state 'measured', 'stale' (older than fresh_s at
    now_ms, or more than a minute in its future), 'missing' (no quote, a zero side) or 'crossed'. The bps
    is None unless measured."""
    if not quote:
        return None, "missing"
    bid, ask, t = quote.get("bid"), quote.get("ask"), quote.get("t_ms")
    if not bid or not ask or bid <= 0 or ask <= 0:
        return None, "missing"
    if ask < bid:
        return None, "crossed"
    if t is None or now_ms is None or now_ms - t > fresh_s * 1000.0 or t - now_ms > 60000:
        return None, "stale"
    mid = (bid + ask) / 2.0
    return (ask - bid) / 2.0 / mid * 1e4, "measured"


def per_side_bps(slip_bps, half_bps):
    return float(slip_bps) + float(half_bps)


def side_cost_per_share(price, bps, commission, shares):
    """price x bps / 10,000 + commission / shares (the commission spread over the order's shares)."""
    if commission and not shares > 0:
        raise CostError("a commission needs a share count to spread over")
    return float(price) * float(bps) / 1e4 + (float(commission) / shares if commission else 0.0)


def round_trip_cost_per_share(entry, bps, commission, shares, exit_price=None):
    """The entry side plus the exit side (priced at the entry unless exit_price is given)."""
    out = entry if exit_price is None else exit_price
    return side_cost_per_share(entry, bps, commission, shares) + side_cost_per_share(out, bps, commission, shares)


def cost_r(rt, risk):
    if not risk > 0:
        raise CostError("cost_r needs a positive risk a share")
    return float(rt) / float(risk)


def net_r(gross_r, c_r):
    return gross_r - c_r


def net_reward_risk(entry, stop, target, rt, long=True):
    """(reward - round trip) / (risk + round trip); None without a target."""
    if target is None:
        return None
    reward = (target - entry) if long else (entry - target)
    risk = (entry - stop) if long else (stop - entry)
    return (reward - rt) / (risk + rt)


def spread_gate(half_bps, state, entry, risk, max_frac):
    """{state pass|block|unverified, reason, spread_usd, limit_usd}: the full spread against max_frac of
    the risk a share. Unverified when the spread was not measured live."""
    limit = float(max_frac) * float(risk)
    if state != "measured" or half_bps is None:
        return {"state": "unverified", "spread_usd": None, "limit_usd": round(limit, 4),
                "reason": "spread not measured live (%s): the %.2f limit cannot be checked" % (state, limit)}
    spread = 2.0 * float(half_bps) / 1e4 * float(entry)
    st = "block" if spread > limit + 1e-12 else "pass"
    return {"state": st, "spread_usd": round(spread, 4), "limit_usd": round(limit, 4),
            "reason": "spread %.4f a share %s %.0f%% of the %.2f risk (%.4f)"
                      % (spread, "over" if st == "block" else "within", 100 * max_frac, risk, limit)}


def shares_basis(risk, max_loss_usd=None):
    """(shares, how): the share count a plan's commission is spread over before trader-budget sizes it,
    floor(max loss / risk a share), at least 1."""
    ml = DEFAULT_MAX_LOSS_USD if max_loss_usd in (None, "", 0) else float(max_loss_usd)
    n = int(math.floor(ml / risk + 1e-9)) if risk > 0 else 0
    if n < 1:
        return 1, "1 share (the %.2f max loss is under one share's %.2f risk)" % (ml, risk)
    return n, "floor(%.2f max loss / %.2f risk) = %d shares" % (ml, risk, n)


def model_of(card):
    """The per-trade cost model a cost card implies (what a history or control trade is charged):
    {per_side_bps, commission_usd, shares, max_loss_usd}; None when costs are off. With max_loss_usd each
    trade's commission is spread over its own floor(max loss / risk) shares, the way trader-budget sizes
    it; without, over the card's shares."""
    if not card or card.get("off"):
        return None
    return {"per_side_bps": card["per_side_bps"], "commission_usd": card["commission_usd"], "shares": card["shares"],
            "max_loss_usd": card.get("max_loss_usd")}


def trade_cost_r(entry, risk, model):
    """cost_r of one trade at this entry and risk under a model (0 when the model is None)."""
    if not model:
        return 0.0
    shares = shares_basis(risk, model["max_loss_usd"])[0] if model.get("max_loss_usd") else model["shares"]
    rt = round_trip_cost_per_share(entry, model["per_side_bps"], model["commission_usd"], shares)
    return cost_r(rt, risk)


def plan_terms(plan, cfg=None):
    """(per_side_bps, commission_usd, source) for sizing or checking an order: the plan's cost card from
    trader-exit when it carries one (its ADV tier and spread), else the config's costs block with the ADV
    unverified (the most expensive tier) and the default half spread (0 under spread_source none)."""
    s = settings(cfg)
    card = (plan or {}).get("costs") if isinstance((plan or {}).get("costs"), dict) else None
    if card and not card.get("off") and card.get("per_side_bps") is not None:
        return float(card["per_side_bps"]), float(card["commission_usd"]), "the plan's cost card"
    if is_off(s):
        return 0.0, 0.0, "zero in the config"
    slip, _ = tier_bps(None, s["slippage_tiers_bps"])
    half = 0.0 if s["spread_source"] == "none" else s["default_half_spread_bps"]
    return slip + half, s["commission_usd"], "the config (ADV unverified: the most expensive tier)"


# ---------------------------------------------------------------- the card

def cost_card(entry, stop, target, shares, adv_usd=None, quote=None, now_ms=None, cfg=None, long=True,
              adv_note=None, quote_note=None, max_loss_usd=None):
    """Everything about one trade's costs in one dict (P12: Python computes, the model narrates).
    max_loss_usd: the max loss the share count came from (shares_basis), recorded for model_of."""
    s = settings(cfg)
    risk = (entry - stop) if long else (stop - entry)
    if not risk > 0:
        raise CostError("the stop must be on the losing side of the entry")
    shares = int(shares)
    if shares < 1:
        raise CostError("the cost card needs at least one share")
    slip, adv_flag = tier_bps(adv_usd, s["slippage_tiers_bps"])
    flags = [adv_flag] if adv_flag else []
    measured, qstate = half_spread_bps(quote, now_ms, s["quote_fresh_seconds"])
    if s["spread_source"] == "none":
        half, used = 0.0, "none"
    elif s["spread_source"] == "snapshot" and qstate == "measured":
        half, used = measured, "measured"
    else:
        half, used = s["default_half_spread_bps"], "default"
        flags.append("spread_default" if s["spread_source"] == "default" else "spread_%s" % qstate)
    side_bps = per_side_bps(slip, half)
    rt = round_trip_cost_per_share(entry, side_bps, s["commission_usd"], shares)
    c_r = cost_r(rt, risk)
    gate = None if s["spread_source"] == "none" else spread_gate(
        measured if s["spread_source"] == "snapshot" else None,
        qstate if s["spread_source"] == "snapshot" else "default", entry, risk, s["spread_max_frac_of_risk"])
    rr_gross = None if target is None else ((target - entry) if long else (entry - target)) / risk
    return {
        "entry": entry, "stop": stop, "target": target, "risk_per_share": round(risk, 6), "shares": shares,
        "max_loss_usd": max_loss_usd,
        "adv_usd": None if adv_usd is None else round(float(adv_usd)), "adv_note": adv_note,
        "slippage_bps": slip, "half_spread_bps": round(half, 4), "spread_basis": used,
        "quote_state": qstate, "quote_note": quote_note, "quote": quote if quote else None,
        "per_side_bps": round(side_bps, 4), "commission_usd": s["commission_usd"],
        "side_cost_per_share": round(side_cost_per_share(entry, side_bps, s["commission_usd"], shares), 6),
        "round_trip_per_share": round(rt, 6), "round_trip_usd": round(rt * shares, 4), "cost_r": round(c_r, 6),
        "reward_risk_gross": None if rr_gross is None else round(rr_gross, 4),
        "reward_risk_net": None if target is None else round(net_reward_risk(entry, stop, target, rt, long), 4),
        "spread_gate": gate, "spread_unverified": s["spread_unverified"], "flags": flags,
        "off": is_off(s), "settings": {k: s[k] for k in ("slippage_tiers_bps", "commission_usd", "spread_source",
                                                          "default_half_spread_bps", "quote_fresh_seconds",
                                                          "spread_max_frac_of_risk")},
    }


def card_line(card):
    """One human line for a cost card (the scripts print it)."""
    if not card:
        return "Costs: off (--no-costs): gross numbers only."
    if card.get("off"):
        return "Costs: zero in the config (no slippage tier, no commission, no spread): gross numbers only."
    adv = ("ADV $%s" % "{:,.0f}".format(card["adv_usd"])) if card.get("adv_usd") is not None else "ADV unverified"
    spread = {"measured": "measured live", "none": "off", "default": "the default, unverified"}.get(
        card["spread_basis"], card["spread_basis"])
    return ("Costs: %.4f a share round trip = %.3f R (%g bp slippage tier, %s; %g bp half spread, %s; $%g "
            "commission a side over %d shares)." % (card["round_trip_per_share"], card["cost_r"],
                                                   card["slippage_bps"], adv, card["half_spread_bps"], spread,
                                                   card["commission_usd"], card["shares"]))
