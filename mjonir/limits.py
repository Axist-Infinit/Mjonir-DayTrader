"""Risk limits in percent of the trade notional (chunk 3.2). Stdlib only, Python 3.8 syntax: trader-budget/size.py
and trader-risk/check.py both call derive_limits (one definition, P8).

The owner's decision: "Assume each trade is 100k. For now just keep everything in percentages." So the config
carries a trade notional (the sizing basis and the cap on one trade's size) and percents of it; no equity
figure. Percent limits are percents of that notional, not of an account.

    "sizing":     {"trade_notional_usd": 100000, "max_loss_pct_of_notional": 1.0}
    "limits_pct": {"daily_loss": 1.0, "weekly_loss": 2.0, "max_consecutive_losses": 3,
                   "pause_sessions_after_streak": 1, "max_trades_per_day": 3}
    "floors":     {"min_price": 5, "min_adv_usd": 20000000, "min_avg_volume": 1000000, "max_chase_pct": 0.5,
                   "no_averaging_down": true}

derive_limits(cfg) -> the dollar knobs:

    notional mode (a "sizing" block):  max_loss_usd = notional x max_loss_pct / 100; daily_loss_usd and
        weekly_loss_usd the same way from limits_pct (a limits_pct key that is absent takes LIMITS_PCT_DEFAULTS);
        max_order_usd = the notional. A legacy dollar key ALSO set in the config (max_loss_per_trade_usd,
        max_daily_loss_usd, max_order_usd, max_trades_per_day, or budget x max_position_pct for the position)
        is a second limit: the STRICTER of the two applies and a warning names both. A legacy key set to null
        is not set.
    legacy mode (no "sizing" block): upstream's dollar keys as they are, so a chunk 2 config behaves as chunk 2
        left it (the scripts' own DEFAULTS fill what is absent).

floors(cfg) are read in either mode; a floor that is absent is off.
"""

import sys

MODES = ("notional", "legacy")
SIZING_KEYS = ("trade_notional_usd", "max_loss_pct_of_notional")
#: the dollar keys a percent config may still carry (null = not set): never filled from a script's DEFAULTS
LEGACY_KEYS = ("max_loss_per_trade_usd", "max_daily_loss_usd", "max_order_usd", "max_trades_per_day", "budget")
LIMITS_PCT_DEFAULTS = {"daily_loss": 1.0, "weekly_loss": 2.0, "max_consecutive_losses": 3,
                       "pause_sessions_after_streak": 1, "max_trades_per_day": 3}
FLOOR_KEYS = ("min_price", "min_adv_usd", "min_avg_volume", "max_chase_pct", "no_averaging_down")


class LimitsError(ValueError):
    pass


def money(x):
    x = float(x)
    return "$" + ("{:,.0f}".format(x) if abs(x - round(x)) < 0.005 else "{:,.2f}".format(x))


def _num(block, key, where, lo=0.0, hi=None, positive=False, integer=False):
    v = block.get(key)
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise LimitsError("%s.%s must be a number, got %r" % (where, key, v))
    if (positive and not x > 0) or x < lo or (hi is not None and x > hi):
        raise LimitsError("%s.%s is out of range: %r" % (where, key, v))
    if integer:
        if x != int(x):
            raise LimitsError("%s.%s must be a whole number, got %r" % (where, key, v))
        return int(x)
    return x


def is_notional(cfg):
    return isinstance(cfg, dict) and isinstance(cfg.get("sizing"), dict)


def floors(cfg):
    """The floors block, checked: {min_price, min_adv_usd, min_avg_volume, max_chase_pct, no_averaging_down}; absent
    keys None. min_avg_volume (mean shares a day over 20 sessions) is read by scan.py rvol, not by trader-risk."""
    f = (cfg or {}).get("floors")
    if f is None:
        return {k: None for k in FLOOR_KEYS}
    if not isinstance(f, dict):
        raise LimitsError("floors must be an object, got %r" % (f,))
    out = {}
    for k in ("min_price", "min_adv_usd", "min_avg_volume", "max_chase_pct"):
        out[k] = None if f.get(k) is None else _num(f, k, "floors")
    nad = f.get("no_averaging_down")
    if nad not in (None, True, False):
        raise LimitsError("floors.no_averaging_down is true or false, got %r" % (nad,))
    out["no_averaging_down"] = nad
    return out


def _legacy(cfg, key):
    v = (cfg or {}).get(key)
    if v is None or v is False:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        raise LimitsError("%s must be a number, got %r" % (key, v))


def unknown_keys(cfg):
    """Warnings for keys the sizing, limits_pct and floors blocks do not know (a typo is otherwise silent)."""
    out = []
    for block, known in (("sizing", SIZING_KEYS), ("limits_pct", tuple(LIMITS_PCT_DEFAULTS)), ("floors", FLOOR_KEYS)):
        b = (cfg or {}).get(block)
        if isinstance(b, dict):
            for k in sorted(set(b) - set(known)):
                out.append("%s.%s is not a key this pack reads (it knows %s): ignored" % (block, k, ", ".join(known)))
    return out


def derive_limits(cfg):
    """The dollar knobs from the percent blocks (see the module docstring). Returns {mode, trade_notional_usd,
    max_loss_pct_of_notional, max_loss_usd, daily_loss_pct, daily_loss_usd, weekly_loss_pct, weekly_loss_usd,
    max_trades_per_day, max_consecutive_losses, pause_sessions_after_streak, max_order_usd, position_cap_usd,
    floors, from, warnings}. Bad values raise LimitsError naming the key."""
    cfg = cfg or {}
    fl = floors(cfg)
    unknown = unknown_keys(cfg)
    for w in unknown:
        sys.stderr.write("mjonir.limits: %s\n" % w)
    if not is_notional(cfg):
        if isinstance(cfg.get("limits_pct"), dict):
            raise LimitsError("limits_pct are percents of sizing.trade_notional_usd: add the sizing block")
        return {"mode": "legacy", "trade_notional_usd": None, "max_loss_usd": _legacy(cfg, "max_loss_per_trade_usd"),
                "daily_loss_usd": _legacy(cfg, "max_daily_loss_usd"), "weekly_loss_usd": None,
                "max_trades_per_day": cfg.get("max_trades_per_day"), "max_consecutive_losses": None,
                "pause_sessions_after_streak": None, "max_order_usd": _legacy(cfg, "max_order_usd"),
                "position_cap_usd": None, "floors": fl, "from": {}, "warnings": list(unknown)}
    s = cfg["sizing"]
    notional = _num(s, "trade_notional_usd", "sizing", positive=True)
    pct = _num(s, "max_loss_pct_of_notional", "sizing", hi=100.0, positive=True)
    lp = cfg.get("limits_pct")
    if lp is not None and not isinstance(lp, dict):
        raise LimitsError("limits_pct must be an object, got %r" % (lp,))
    lp = dict(LIMITS_PCT_DEFAULTS, **{k: v for k, v in (lp or {}).items() if v is not None})
    daily_pct = _num(lp, "daily_loss", "limits_pct", hi=100.0)
    weekly_pct = _num(lp, "weekly_loss", "limits_pct", hi=100.0)
    streak = _num(lp, "max_consecutive_losses", "limits_pct", integer=True)
    pause = _num(lp, "pause_sessions_after_streak", "limits_pct", integer=True)
    trades = _num(lp, "max_trades_per_day", "limits_pct", integer=True)
    nm = money(notional)
    out = {"mode": "notional", "trade_notional_usd": notional, "max_loss_pct_of_notional": pct,
           "max_loss_usd": round(notional * pct / 100.0, 2), "daily_loss_pct": daily_pct,
           "daily_loss_usd": round(notional * daily_pct / 100.0, 2), "weekly_loss_pct": weekly_pct,
           "weekly_loss_usd": round(notional * weekly_pct / 100.0, 2), "max_trades_per_day": trades,
           "max_consecutive_losses": streak, "pause_sessions_after_streak": pause, "max_order_usd": notional,
           "position_cap_usd": notional, "floors": fl, "warnings": list(unknown),
           "from": {"max_loss_usd": "sizing.max_loss_pct_of_notional %g%% of the %s trade notional" % (pct, nm),
                    "daily_loss_usd": "limits_pct.daily_loss %g%% of %s" % (daily_pct, nm),
                    "weekly_loss_usd": "limits_pct.weekly_loss %g%% of %s" % (weekly_pct, nm),
                    "max_trades_per_day": "limits_pct.max_trades_per_day",
                    "max_order_usd": "sizing.trade_notional_usd", "position_cap_usd": "sizing.trade_notional_usd"}}
    pairs = (("max_loss_per_trade_usd", "max_loss_usd"), ("max_daily_loss_usd", "daily_loss_usd"),
             ("max_order_usd", "max_order_usd"))
    for legacy, key in pairs:
        v = _legacy(cfg, legacy)
        if v is not None and v > 0:
            stricter = min(v, out[key])
            out["warnings"].append("%s %s and %s = %s are both set: the stricter, %s, applies"
                                   % (legacy, money(v), out["from"][key], money(out[key]), money(stricter)))
            if v < out[key]:
                out[key] = v
                out["from"][key] = legacy
    v = _legacy(cfg, "max_trades_per_day")
    if v is not None and v > 0:
        n = int(v)
        out["warnings"].append("max_trades_per_day %d and limits_pct.max_trades_per_day %d are both set: the stricter, "
                               "%d, applies" % (n, trades, min(n, trades)))
        if n < trades:
            out["max_trades_per_day"] = n
            out["from"]["max_trades_per_day"] = "max_trades_per_day"
    b = _legacy(cfg, "budget")
    if b is not None and b > 0:
        cap = round(b * float(cfg.get("max_position_pct") or 100) / 100.0, 2)
        out["warnings"].append("budget %s (x max_position_pct %s%% = %s) and the %s trade notional are both set: the "
                               "stricter, %s, caps the position" % (money(b), cfg.get("max_position_pct") or 100,
                                                                    money(cap), nm, money(min(cap, notional))))
        if cap < notional:
            out["position_cap_usd"] = cap
            out["from"]["position_cap_usd"] = "budget x max_position_pct"
    return out
