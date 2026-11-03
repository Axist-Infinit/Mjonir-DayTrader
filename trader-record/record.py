#!/usr/bin/env python3
"""Forward Record for trader-record: the paper account that decides whether this pack ever trades money.
Standard library only; Python 3.8 syntax. It never places an order.

    python3 record.py add --from trader/entry.json --plan trader/plan.json --skipped "too extended"
    python3 record.py add --from trader/entry.json --plan trader/plan.json --taken --fingerprint FP --qty 156
    python3 record.py score --date 2026-10-19 --source massive      # after the close
    python3 record.py score --date 2026-10-19 --offline TSLA.json --now "2026-10-19 16:30"
    python3 record.py report                                       # counts, intervals, control, the gate
    python3 record.py report --setup orb --since 2026-11-01 --json
    python3 record.py journal                                      # taken beside skipped, by setup and month

Two append-only files under ${TRADER_RECORD_DIR:-record} (cwd-relative, like trader/), both tracked in git
and opened with mode "a" only (mjonir/ledger.py, P7):

  triggers.jsonl  one line per trigger the entry timer sees, taken or not (entry.py check and watch append it
                  with --record, on by default), one per random-entry control drawn on its session, and one
                  per later decision (ticket.py approve and decline append those)
  scores.jsonl    one line per scored id (a trigger or a control), written once; `score` skips ids already
                  there, so a second run appends nothing

A trigger row's plan: the plan file you pass (--plan, matching symbol and date), else trader-exit's own
defaults for the setup (an orb: or-mid stop, 2R target, the config's flat-by), built by trader-exit itself.
Its id is sha256(symbol|date|setup|trigger time|rule hash)[:16]; the same id is never appended twice.

How `score` scores a trigger: exactly the way the time machine's history scores the same plan
(mjonir/outcomes.py score_trade): from the trigger bar's close, through the bars STRICTLY after it, to the
plan's flat-by bar (moved up three hours on a 1:00 p.m. early close, as trader-exit and the time machine move
it), out at that bar's close if neither the stop nor the target was touched; the stop checked first in each
bar; a bar opening through the stop fills at its open; one round trip charged once from the plan's cost card
(mjonir/costs.py; the time machine's default card, ADV unverified, when the plan has none). Prices are the
plan's as written: the cent order prices. The time machine's history enters at the unrounded bar close and
its targets can sit a fraction of a cent away; that difference is by design (chunk 2 review note 11). The
time machine itself ends its replays at --until (default the 16:00 close); run it with --until <flat_by> for
the same last bar.

Each scored trigger gets one random-entry control row (--control-draws, default 1): mjonir/control.py, a bar
after the opening range and inside the plan's entry window (no_entries_after, 15:30, or its early-close
equivalent), the plan's risk as a percent of the entry, the same target multiple and flat-by, seeded by
identifiers only (19:symbol:date). A taken trade is also scored from the hand-entered fills in
trader/state/broker.json (ticket.py fill) when both legs are there: fill_basis "broker".

The gate (`report`) reads the statistics the time machine's verdict reads: the net expectancy interval
(mjonir.stats.expectancy_ci) over ALL scored paper triggers, taken or not, and the paired delta against the
control (paired_delta_ci). PASSES when n >= 40 AND days >= 180 AND the expectancy interval is wholly above 0
AND the delta interval is wholly above 0 over at least 40 paired sessions; FAILS when n >= 40 AND days >= 180
AND (the expectancy interval is wholly below 0, OR the delta interval is wholly below 0 over at least 40 paired
sessions); NOT YET otherwise, with the reasons. days = calendar days from the first trigger's date to today
(New York). Every report ends with "Money only past the gate; the gate is not a forecast."

Exit codes: add 0 = written or already there, 1 = an error; score 0 = every trigger of the day is scored,
2 = some could not be scored yet (bars missing: unverified), 1 = an error; report and journal 0.
"""

import argparse
import datetime
import importlib
import importlib.util
import json
import os
import re
import sys

SEED = 19
GATE_DAYS = 180
FOOTER = "Money only past the gate; the gate is not a forecast."
NOTE_PRICES = ("Prices are the plan's as written (the cent order prices); the time machine's history enters at the "
               "unrounded bar close, so its targets can differ by a fraction of a cent. That is by design.")
OPEN_MIN = 9 * 60 + 30
CLOSE_MIN = 16 * 60
EARLY_MIN = 13 * 60
STEP = 300


class RecordFail(Exception):
    pass


# ---------------------------------------------------------------- the layers it stands on

def _root():
    return os.environ.get("MJONIR_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _measure(name):
    """mjonir.<name> (ledger, stats, costs, outcomes, control): Python 3.8 syntax, stdlib only."""
    root = _root()
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        return importlib.import_module("mjonir." + name)
    except ImportError as e:
        raise RecordFail("the measurement layer (mjonir/%s.py) is missing at %s: %s" % (name, root, e))


_SCRIPTS = {}


def _script(folder, name):
    """A sibling skill's script as a module (trader-entry/entry.py for bars and the clock, trader-exit/exit.py
    for the rule's own plan): one definition of each, loaded once."""
    key = (folder, name)
    if key not in _SCRIPTS:
        path = os.path.join(_root(), folder, name + ".py")
        if not os.path.exists(path):
            raise RecordFail("%s is missing at %s" % (folder, path))
        spec = importlib.util.spec_from_file_location("trader_record_%s" % name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _SCRIPTS[key] = mod
    return _SCRIPTS[key]


def _entry():
    return _script("trader-entry", "entry")


def parse_now(text=None):
    """--now (New York unless it says otherwise) -> naive UTC, through trader-entry's clock."""
    en = _entry()
    try:
        return en.parse_now(text) if text else en.utc_now()
    except en.EntryError as e:
        raise RecordFail(str(e))


def today_et(now_utc):
    """The New York date of now (the trader scripts' one DST rule; never the box's Mountain date)."""
    return _entry().to_eastern(now_utc).date()


def iso(now_utc):
    return now_utc.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clock_min(text, what="a time"):
    """'10:15 AM', '3:55 PM' or '15:55' -> minutes after midnight."""
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*(?:([AaPp])\.?\s*[Mm]\.?)?\s*$", str(text or ""))
    if not m:
        raise RecordFail("%s wants a New York time like 10:15 AM or 15:55, not %r" % (what, text))
    h, mi, ap = int(m.group(1)), int(m.group(2)), (m.group(3) or "").lower()
    if ap == "p" and h != 12:
        h += 12
    elif ap == "a" and h == 12:
        h = 0
    return h * 60 + mi


def hhmm(minutes):
    return "%02d:%02d" % divmod(int(minutes), 60)


def read_json(path, what, required=True):
    if not path or not os.path.exists(path):
        if required:
            raise RecordFail("no %s at %s" % (what, path))
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except ValueError as e:
        raise RecordFail("%s is not valid JSON: %s" % (path, e))


def _r6(x):
    return None if x is None else round(float(x), 6)


# ---------------------------------------------------------------- the plan and the cost card

def rule_plan(doc, config=None, source="yahoo", now_utc=None, now_text=None):
    """(plan, basis) for a trigger with no plan file: trader-exit's own build_plan with its defaults (an orb:
    or-mid stop, 2R target, the config's flat-by and min reward:risk, the cost card). (None, why) when
    trader-exit refuses (a level setup has no default stop; a plan under the net minimum reward:risk)."""
    ex = _script("trader-exit", "exit")
    ex.SOURCE = "massive" if source == "massive" else "yahoo"
    orr = doc.get("opening_range") or {}
    ns = argparse.Namespace(
        from_path=None, symbol=doc.get("symbol"), entry=doc.get("price"), or_high=orr.get("high"),
        or_low=orr.get("low"), or_minutes=orr.get("minutes") or 15, setup=doc.get("setup"), date=doc.get("date"),
        time=doc.get("time"), entry_bar=doc.get("bar_index"), interval=doc.get("interval") or "5m", side="buy",
        stop=None, target=None, exit=None, shares=None, no_costs=False, flat_by=None,
        config=config or "trader/config.json", offline=None, now=now_text, write=None, json=False)
    try:
        plan, _ = ex.build_plan(ns, now_utc or parse_now(now_text))
    except ex.PlanError as e:
        return None, "trader-exit refused the default plan: %s" % e
    except Exception as e:   # a data layer that could not answer: the trigger is still recorded
        return None, "the default plan could not be built: %s" % e
    return plan, "trader-exit defaults for the setup (%s stop, %s target)" % (
        plan.get("stop_rule"), ("%gR" % plan["target_r"]) if plan.get("target_r") is not None else "no")


def card_for(plan, cfg):
    """The plan's cost card, as the time machine's cost_card_for reads it: the card trader-exit wrote, None
    when the plan says costs are off ("costs": null), else a default card from the config's costs block with
    the ADV unverified (the most expensive tier) over floor(max loss / risk) shares."""
    if "costs" in plan:
        return (plan["costs"] if isinstance(plan["costs"], dict) else None), (
            "the plan's cost card" if isinstance(plan["costs"], dict) else "off in the plan")
    costs = _measure("costs")
    entry, stop = float(plan["entry"]), float(plan["stop"])
    ml = (cfg or {}).get("max_loss_per_trade_usd") or costs.DEFAULT_MAX_LOSS_USD
    try:
        shares, how = costs.shares_basis(entry - stop, ml)
        card = costs.cost_card(entry, stop, plan.get("target"), shares, cfg=cfg,
                               adv_note="unverified: the plan carries no cost card", max_loss_usd=float(ml))
    except costs.CostError as e:
        raise RecordFail("costs: %s" % e)
    card["shares_basis"] = how
    return card, "the time machine's default card (ADV unverified: the most expensive tier)"


# ---------------------------------------------------------------- trigger rows

def rule_of(doc, plan, window, min_volume_x=None):
    """What the record measures: the entry rule and the exit rule. RULE_KEYS (mjonir/ledger.py) are hashed;
    the flat-by and the entry window are kept beside them."""
    p = plan or {}
    stop_rule = p.get("stop_rule")
    param = None
    if stop_rule in ("pct", "atr", "datr"):
        m = re.match(r"^\s*([0-9.]+)", str(p.get("stop_label") or ""))
        param = float(m.group(1)) if m else None
    tr = p.get("target_r")
    if str(p.get("target_label") or "").startswith("your price"):
        tr = "price"
    elif tr is not None:
        tr = float(tr)
    orr = doc.get("opening_range") or {}
    return {"setup": doc.get("setup") or "orb", "interval": doc.get("interval") or "5m",
            "or_minutes": orr.get("minutes"), "min_volume_x": min_volume_x, "stop_rule": stop_rule,
            "stop_param": param, "target_r": tr, "exit": (p.get("exit") or "target") if plan else None,
            "flat_by": p.get("flat_by"), "no_entries_before": window[0], "no_entries_after": window[1]}


def _window(config):
    """(no_entries_before, no_entries_after) from the config, through trader-entry's reader (09:45, 15:30)."""
    en = _entry()
    try:
        cfg = en.read_config(config or "trader/config.json")
    except en.EntryError as e:
        raise RecordFail(str(e))
    return cfg["no_entries_before"], cfg["no_entries_after"]


def plan_part(plan, basis):
    entry, stop = float(plan["entry"]), float(plan["stop"])
    risk = float(plan.get("risk_per_share") or round(entry - stop, 4))
    return {"entry": entry, "stop": stop, "target": plan.get("target"), "risk_per_share": risk,
            "risk_pct": round(100.0 * risk / entry, 4), "target_r": plan.get("target_r"),
            "exit": plan.get("exit") or "target", "flat_by": plan.get("flat_by"), "entry_bar": plan.get("entry_bar"),
            "entry_time": plan.get("entry_time"), "basis": basis}


def trigger_time(doc):
    return hhmm(_clock_min(doc.get("time"), "the trigger time"))


def build_trigger(doc, plan, plan_basis, decision, now_utc, window, bars_label, extra=None, notes=(), cfg=None):
    ledger = _measure("ledger")
    extra = extra or {}
    sym = str(doc.get("symbol") or "").upper()
    rule = rule_of(doc, plan, window, extra.get("min_volume_x"))
    rh = ledger.rule_hash(rule)
    t = trigger_time(doc)
    card, card_basis = (None, None)
    if plan is not None:
        card, card_basis = card_for(plan, cfg)
    orr = doc.get("opening_range") or {}
    return {
        "schema": ledger.SCHEMA, "kind": "trigger",
        "id": ledger.trigger_id(sym, doc.get("date"), rule["setup"], t, rh), "paired_id": None,
        "recorded_at": iso(now_utc), "date": doc.get("date"), "symbol": sym, "setup": rule["setup"],
        "rule": rule, "rule_hash": rh,
        "trigger": {"time": t, "bar_index": doc.get("bar_index"), "price": doc.get("price"),
                    "or_high": orr.get("high"), "or_low": orr.get("low"), "level": doc.get("level"),
                    "volume_x": extra.get("volume_x"), "rvol": extra.get("rvol")},
        "plan": None if plan is None else plan_part(plan, plan_basis),
        "plan_note": None if plan is not None else plan_basis,
        "costs": card, "costs_basis": card_basis,
        "decision": decision or {"taken": None, "reason": "pending: no decision recorded yet"},
        "source": {"bars": bars_label or doc.get("source") or "yahoo", "as_of": doc.get("checked_at")},
        "notes": list(notes),
    }


def _matches(doc, plan):
    return (isinstance(plan, dict) and str(plan.get("symbol") or "").upper() == str(doc.get("symbol") or "").upper()
            and str(plan.get("date")) == str(doc.get("date")))


def record_trigger(doc, plan=None, decision=None, config=None, source="yahoo", now_utc=None, now_text=None,
                   bars_label=None, extra=None, record_dir=None):
    """Append one trigger row, once. A plan for another symbol or day is not used (noted); without one the
    rule's default plan is built by trader-exit. Returns {state appended|exists|decided|skipped, id, message}."""
    ledger = _measure("ledger")
    if doc.get("status") != "triggered":
        return {"state": "skipped", "id": None, "message": "not recorded: %s is %s, not triggered"
                % (doc.get("symbol"), doc.get("status"))}
    now_utc = now_utc or parse_now(now_text)
    notes = []
    basis = None
    if plan is not None and not _matches(doc, plan):
        notes.append("the plan given was for %s %s, not this trigger: not used" % (plan.get("symbol"), plan.get("date")))
        plan = None
    if plan is not None:
        basis = "the plan file"
    else:
        plan, basis = rule_plan(doc, config, source, now_utc, now_text)
    cfg = read_json(config or "trader/config.json", "config", required=False) or {}
    row = build_trigger(doc, plan, basis, decision, now_utc, _window(config), bars_label, extra, notes, cfg)
    book = ledger.load(record_dir)
    tp, _ = ledger.paths(record_dir)
    if row["id"] in book["ids"]:
        if decision and decision.get("taken") is not None:
            got = append_decision(book, [t for t in book["triggers"] if t["id"] == row["id"]][0], decision,
                                  now_utc, record_dir)
            return dict(got, id=row["id"])
        return {"state": "exists", "id": row["id"],
                "message": "already in %s (id %s): a trigger is recorded once" % (tp, row["id"])}
    ledger.append_rows(tp, [row])
    what = "the plan from %s" % basis if plan is not None else "no plan (%s)" % basis
    return {"state": "appended", "id": row["id"], "row": row,
            "message": "recorded %s %s %s in %s (id %s), %s" % (row["symbol"], row["date"], row["trigger"]["time"],
                                                               tp, row["id"], what)}


def append_decision(book, t, decision, now_utc, record_dir=None):
    ledger = _measure("ledger")
    did = ledger.decision_id(t["id"], decision.get("taken"), decision.get("reason"),
                             decision.get("broker_fingerprint"))
    tp, _ = ledger.paths(record_dir)
    now_d = ledger.decision_of(book, t)
    same = all(now_d.get(k) == decision.get(k) for k in ("taken", "reason", "broker_fingerprint"))
    if did in book["ids"] or same:
        return {"state": "exists", "message": "that decision is already in %s for %s (trigger id %s)" % (
            tp, t.get("symbol"), t["id"])}
    row = {"schema": ledger.SCHEMA, "kind": "decision", "id": did, "paired_id": t["id"], "recorded_at": iso(now_utc),
           "date": t.get("date"), "symbol": t.get("symbol"), "setup": t.get("setup"), "decision": decision}
    ledger.append_rows(tp, [row])
    return {"state": "decided", "message": "recorded the decision (%s) for %s %s %s in %s (id %s)" % (
        "taken" if decision.get("taken") else "skipped: %s" % decision.get("reason"), t.get("symbol"), t.get("date"),
        (t.get("trigger") or {}).get("time"), tp, did)}


def _same_plan(t, oplan):
    p = t.get("plan") or {}
    try:
        same_stop = abs(float(p["stop"]) - float(oplan.get("stop"))) < 0.005
    except (TypeError, ValueError, KeyError):
        return False
    a, b = p.get("target"), oplan.get("target")
    if a is None or b is None:
        return same_stop and a is None and b is None
    return same_stop and abs(float(a) - float(b)) < 0.005


def decide(order, decision, today, now_utc, entry_path="trader/entry.json", plan_path="trader/plan.json",
           config=None, source=None, record_dir=None):
    """ticket.py approve / decline: the decision for the trigger behind this order. The trigger is found by
    (symbol, day, setup, trigger time) from trader/entry.json, else from the order's plan; a decision row is
    appended to it (to the row whose plan matches the order's stop and target, else the first). No trigger row
    yet: the trigger row is written from entry.json (and plan.json when it matches) with the decision in it.
    Returns {state, message}; nothing is written when no trigger can be found (said so)."""
    ledger = _measure("ledger")
    sym = str(order.get("symbol") or "").upper()
    oplan = order.get("plan") if isinstance(order.get("plan"), dict) else {}
    doc = read_json(entry_path, "entry", required=False)
    if not (isinstance(doc, dict) and str(doc.get("symbol") or "").upper() == sym and str(doc.get("date")) == today
            and doc.get("status") == "triggered"):
        doc = None
    plan = read_json(plan_path, "plan", required=False)
    if not (isinstance(plan, dict) and str(plan.get("symbol") or "").upper() == sym and str(plan.get("date")) == today):
        plan = None
    when = (doc or {}).get("time") or oplan.get("entry_time")
    setup = (doc or {}).get("setup") or oplan.get("setup") or "orb"
    if not when:
        return {"state": "skipped", "message": "not recorded: no trigger time for %s (no matching %s and no entry "
                                               "time in the order's plan)" % (sym, entry_path)}
    key = (sym, today, setup, hhmm(_clock_min(when, "the trigger time")))
    book = ledger.load(record_dir)
    cands = [t for t in book["triggers"] if ledger.trigger_key(t) == key]
    full = dict(decision, order_plan={k: oplan.get(k) for k in ("entry", "stop", "target", "max_loss")})
    if cands:
        pick = next((t for t in cands if _same_plan(t, oplan)), cands[0])
        full["plan_matches_record"] = _same_plan(pick, oplan)
        return append_decision(book, pick, full, now_utc, record_dir)
    if doc is None:
        return {"state": "skipped", "message": "not recorded: no trigger row for %s %s %s in the record and no "
                                               "matching %s to write one from" % (sym, today, key[3], entry_path)}
    got = record_trigger(doc, plan, full, config, source or os.environ.get("TRADER_SOURCE") or "yahoo", now_utc,
                         bars_label=doc.get("source"), record_dir=record_dir)
    return got


# ---------------------------------------------------------------- scoring

def last_bar(flat_by, early):
    """The flat-by bar of a session, as the time machine reads its last bar: the plan's flat-by (default the
    16:00 close); on a 1:00 p.m. early close a flat-by at or after 13:00 moves up three hours (15:55 -> 12:55,
    bar 40), as trader-exit's resolve_flat_by and the time machine's early_last move it."""
    fb = _clock_min(flat_by or "16:00", "flat_by")
    end = EARLY_MIN if early else CLOSE_MIN
    if early and fb >= EARLY_MIN:
        fb -= CLOSE_MIN - EARLY_MIN
    return (min(fb, end) - OPEN_MIN) // 5 - 1


def entry_until(no_entries_after, early):
    """The last bar an entry may close on: no_entries_after (default 15:30), moved up with an early close the way
    trader-entry's early_cutoff moves it (15:30 -> 12:30). 15:30 is bar 71 (the 15:25 bar closes at 15:30)."""
    cut = _clock_min(no_entries_after or "15:30", "no_entries_after")
    close = EARLY_MIN if early else CLOSE_MIN
    if cut >= close:
        cut -= CLOSE_MIN - close
        if cut <= OPEN_MIN:
            cut = close
    return (cut - OPEN_MIN) // 5 - 1


def session_bars(symbol, day, source="massive", offline=None, now_utc=None):
    """({slot: {o,h,l,c}}, info) of one session's COMPLETE 5-minute bars (by now), through trader-entry's own
    reader (an --offline file or folder, Yahoo, or Massive). info: early (a 1:00 p.m. close, from the
    calendar overlay or the data's own label), n (78 or 42), source."""
    en = _entry()
    en.SOURCE = "massive" if source == "massive" else "yahoo"
    try:
        chart = en.get_chart(symbol, "5m", day, offline, en.to_eastern(en.utc_now()).date())
    except en.EntryError as e:
        raise RecordFail("no bars for %s on %s: %s" % (symbol, day, e))
    s = en.session(day)
    if not s:
        raise RecordFail("%s is not a session (%s)" % (day, en.trading_day(day)[1]))
    mj = (chart.get("meta") or {}).get("mjonir") or {}
    labels = mj.get("early_closes") if isinstance(mj.get("early_closes"), dict) else {}
    early = s[1] != en.CLOSE or labels.get(day.isoformat()) not in (None, "contradicted")
    open_dt = datetime.datetime.combine(day, en.OPEN)
    n = 42 if early else 78
    now_ts = en.ts_of(now_utc or en.utc_now())
    slots = {}
    for b in chart["bars"]:
        if b["t"] % STEP or b["t"] + STEP > now_ts:
            continue
        et = en.to_eastern(en.utc_of(b["t"]))
        sec = (et - open_dt).total_seconds()
        if et.date() != day or sec < 0:
            continue
        i = int(sec) // STEP
        if i < n:
            slots[i] = {"o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"]}
    label = "offline" if offline else ("massive" if source == "massive" else "yahoo")
    return slots, {"early": early, "n": n, "source": label, "data_source": mj.get("source") or label}


def broker_fills(state, t, dec, card, others):
    """({entry_price, exit_price, qty, commission_usd, gross_usd, net_usd, gross_r, net_r}, None) from the
    hand-entered fills in trader/state/broker.json (ticket.py fill) for this taken trade, else (None, why)."""
    fp = dec.get("broker_fingerprint")
    if not fp:
        return None, "no broker fingerprint in the decision"
    if not isinstance(state, dict):
        return None, "no trader/state/broker.json"
    orders = state.get("orders") or []
    day = str(t.get("date"))
    sym = str(t.get("symbol")).upper()

    def rec_day(r):
        return str(r.get("date") or str(r.get("at", ""))[:10])
    if not any(r.get("fingerprint") == fp and r.get("status") in ("approved", "placed") for r in orders):
        return None, "no approval for this order (fingerprint %s) in the broker log" % fp
    if others:
        return None, "%d other taken trade(s) on %s %s: the day's fills cannot be told apart" % (others, sym, day)
    fills = [r for r in orders if r.get("status") == "filled" and str(r.get("symbol", "")).upper() == sym
             and rec_day(r) == day]
    buys = [(float(r["qty"]), float(r["price"])) for r in fills if str(r.get("side")).lower() == "buy"]
    sells = [(float(r["qty"]), float(r["price"])) for r in fills if str(r.get("side")).lower() == "sell"]
    if not buys or not sells:
        return None, "the broker log has %s fill(s) on %s for %s: both legs are needed" % (
            "buy" if buys else "sell" if sells else "no", day, sym)
    bq, sq = sum(q for q, _ in buys), sum(q for q, _ in sells)
    if abs(bq - sq) > 1e-9:
        return None, "bought %g and sold %g %s on %s: not flat" % (bq, sq, sym, day)
    ep = sum(q * p for q, p in buys) / bq
    xp = sum(q * p for q, p in sells) / sq
    comm = float((card or {}).get("commission_usd") or 0.0)
    risk = float((t.get("plan") or {}).get("risk_per_share") or 0.0)
    gross = (xp - ep) * bq
    net = gross - 2.0 * comm
    return {"entry_price": round(ep, 4), "exit_price": round(xp, 4), "qty": bq, "commission_usd": comm,
            "gross_usd": round(gross, 2), "net_usd": round(net, 2),
            "gross_r": _r6(gross / (bq * risk)) if risk else None, "net_r": _r6(net / (bq * risk)) if risk else None}, None


def _score_row(kind, rid, t, res, k, last, info, now_utc):
    return {"schema": 1, "id": rid, "kind": kind, "paired_id": None if kind == "trigger" else t["id"],
            "scored_at": iso(now_utc), "date": t.get("date"), "symbol": t.get("symbol"), "outcome": res["outcome"],
            "entry_bar": k, "exit_bar": res["exit_bar"], "exit_time": hhmm(OPEN_MIN + 5 * (res["exit_bar"] + 1)),
            "exit_price": _r6(res["exit_price"]), "gross_r": _r6(res["gross_r"]), "net_r": _r6(res["net_r"]),
            "cost_r": _r6(res["cost_r"]), "mfe_r": _r6(res["mfe_r"]), "mae_r": _r6(res["mae_r"]),
            "fragile": res["fragile"], "gap": res["gap"], "bars_used": res["exit_bar"] - k, "last_bar": last,
            "fill_basis": "paper", "broker": None,
            "source": {"bars": info["source"], "data": info.get("data_source"), "early_close": info["early"]}}


def score_day(day, source="massive", offline=None, draws=1, now_utc=None, state_path="trader/state/broker.json",
              record_dir=None, symbols=None):
    """Score every trigger recorded on `day` that has no score yet, and its control rows. Returns
    {lines, appended, pending}. Ids already scored are skipped; nothing is rewritten."""
    ledger, costs, outcomes, control = (_measure("ledger"), _measure("costs"), _measure("outcomes"),
                                        _measure("control"))
    now_utc = now_utc or parse_now(None)
    day = datetime.date.fromisoformat(str(day))
    book = ledger.load(record_dir)
    tp, sp = ledger.paths(record_dir)
    todo = [t for t in book["triggers"] if t.get("date") == day.isoformat()
            and (not symbols or t.get("symbol") in symbols)]
    todo.sort(key=lambda t: (str((t.get("trigger") or {}).get("time")), t["id"]))
    out = {"lines": [], "appended": {"triggers": 0, "scores": 0}, "pending": 0, "day": day.isoformat()}
    if not todo:
        out["lines"].append("No trigger recorded on %s in %s." % (day.isoformat(), tp))
        return out
    state = read_json(state_path, "broker state", required=False) if state_path else None
    taken_by_sym = {}
    for t in todo:
        if ledger.is_taken(book, t):
            taken_by_sym[t["symbol"]] = taken_by_sym.get(t["symbol"], 0) + 1
    bars_cache = {}
    for t in todo:
        label = "%s %s %s" % (t["symbol"], (t.get("trigger") or {}).get("time"), t.get("setup"))
        plan = t.get("plan")
        cids = [ledger.control_id(t["id"], i, SEED) for i in range(int(draws))]
        have_score = t["id"] in book["scores"]
        if plan is None:
            if not have_score:
                ledger.append_rows(sp, [{"schema": 1, "id": t["id"], "kind": "trigger", "paired_id": None,
                                         "scored_at": iso(now_utc), "date": t.get("date"), "symbol": t.get("symbol"),
                                         "outcome": "no_data", "reason": "no plan: %s" % t.get("plan_note"),
                                         "fill_basis": "paper", "broker": None}])
                out["appended"]["scores"] += 1
                out["lines"].append("%s: no plan to score (%s): written as no_data." % (label, t.get("plan_note")))
            continue
        if have_score and all(c in book["ids"] and c in book["scores"] for c in cids):
            out["lines"].append("%s: already scored (%s, net %+.3f R); nothing appended." % (
                label, book["scores"][t["id"]].get("outcome"), float(book["scores"][t["id"]].get("net_r") or 0)))
            continue
        key = t["symbol"]
        if key not in bars_cache:
            try:
                bars_cache[key] = session_bars(t["symbol"], day, source, offline, now_utc)
            except RecordFail as e:
                bars_cache[key] = e
        got = bars_cache[key]
        if isinstance(got, RecordFail):
            out["pending"] += 1
            out["lines"].append("%s: unverified, not scored: %s" % (label, got))
            continue
        slots, info = got
        k = plan.get("entry_bar")
        k = int((t.get("trigger") or {}).get("bar_index") if k is None else k)
        last = last_bar(plan.get("flat_by"), info["early"])
        missing = [i for i in range(0, last + 1) if i not in slots]
        if missing:
            out["pending"] += 1
            out["lines"].append("%s: unverified, not scored: %d of the %d bars through the flat-by bar %d are not in "
                                "the data yet (first missing: bar %d)" % (label, len(missing), last + 1, last,
                                                                          missing[0]))
            continue
        if not 0 <= k < last:
            if not have_score:
                ledger.append_rows(sp, [{"schema": 1, "id": t["id"], "kind": "trigger", "paired_id": None,
                                         "scored_at": iso(now_utc), "date": t.get("date"), "symbol": t.get("symbol"),
                                         "outcome": "no_data", "reason": "the entry bar %d is not before the flat-by "
                                                                         "bar %d" % (k, last),
                                         "fill_basis": "paper", "broker": None}])
                out["appended"]["scores"] += 1
            continue
        seq = [slots[i] for i in range(last + 1)]
        entry, stop, target = float(plan["entry"]), float(plan["stop"]), plan.get("target")
        target = None if target is None else float(target)
        model = costs.model_of(t.get("costs"))

        def cost_fn(e, r, model=model):
            return costs.trade_cost_r(e, r, model)
        if not have_score:
            res = outcomes.score_trade(seq, k, entry, stop, target, last, cost_fn(entry, entry - stop),
                                       fill="close", gap_fill="open", long=True)
            row = _score_row("trigger", t["id"], t, res, k, last, info, now_utc)
            trig_c = seq[k]["c"]
            if abs(trig_c - float((t.get("trigger") or {}).get("price") or trig_c)) > 0.02:
                row["note"] = ("the trigger bar's close here is %.4f, the trigger said %.2f (another source or "
                               "vendor)" % (trig_c, float(t["trigger"]["price"])))
            dec = ledger.decision_of(book, t)
            if dec.get("taken") is True:
                b, why = broker_fills(state, t, dec, t.get("costs"), taken_by_sym.get(t["symbol"], 1) - 1)
                if b:
                    row.update(fill_basis="broker", broker=b)
                else:
                    row["broker_note"] = why
            ledger.append_rows(sp, [row])
            out["appended"]["scores"] += 1
            words = "%s at %s (exit %.2f), net %+.3f R (gross %+.3f R, costs %.3f R)" % (
                res["outcome"], row["exit_time"], res["exit_price"], res["net_r"], res["gross_r"], res["cost_r"])
            if row["fill_basis"] == "broker":
                words += "; from the fills: net %+.3f R, $%.2f" % (row["broker"]["net_r"], row["broker"]["net_usd"])
            out["lines"].append("%s: %s." % (label, words))
        if not cids:
            continue
        rule = t.get("rule") or {}
        n_or = int(rule.get("or_minutes") or 15) // 5
        eu = entry_until(rule.get("no_entries_after"), info["early"])
        tr = plan.get("target_r")
        tr = None if target is None or tr is None else float(tr)
        got_c, why = control.draw_controls(seq, t["symbol"], t["date"], SEED, len(cids), n_or, last, entry, stop, tr,
                                           cost_fn, "open", True, entry_until=eu)
        if not got_c:
            out["lines"].append("  control: none drawn (%s)." % ", ".join("%s %d" % kv for kv in sorted(why.items())))
            continue
        new_rows, new_scores = [], []
        for i, (cid, c) in enumerate(zip(cids, got_c)):
            if cid not in book["ids"]:
                new_rows.append({
                    "schema": 1, "kind": "control", "id": cid, "paired_id": t["id"], "recorded_at": iso(now_utc),
                    "date": t.get("date"), "symbol": t.get("symbol"), "setup": t.get("setup"),
                    "rule_hash": t.get("rule_hash"),
                    "control": {"draw": i, "seed": "%s:%s:%s" % (SEED, t["symbol"], t["date"]), "bar_index": c["bar"],
                                "time": hhmm(OPEN_MIN + 5 * (c["bar"] + 1)), "entry": _r6(c["entry"]),
                                "stop": _r6(c["stop"]), "target": _r6(c["target"]), "n_or": n_or, "entry_until": eu,
                                "last": last, "risk_pct": round(100.0 * (entry - stop) / entry, 4)}})
            if cid not in book["scores"]:
                new_scores.append(_score_row("control", cid, t, c, c["bar"], last, info, now_utc))
                out["lines"].append("  control %d: bar %d (%s) at %.2f, %s, net %+.3f R." % (
                    i, c["bar"], hhmm(OPEN_MIN + 5 * (c["bar"] + 1)), c["entry"], c["outcome"], c["net_r"]))
        ledger.append_rows(tp, new_rows)
        ledger.append_rows(sp, new_scores)
        out["appended"]["triggers"] += len(new_rows)
        out["appended"]["scores"] += len(new_scores)
    return out


# ---------------------------------------------------------------- the report and the gate

def _filtered(book, setup=None, since=None):
    return [t for t in book["triggers"] if (not setup or t.get("setup") == setup)
            and (not since or str(t.get("date")) >= since)]


def _ci(stats, rs):
    return stats.expectancy_ci(rs) if rs else None


def gate_of(n, days, first, exp, delta, floor):
    """The money gate, three outcomes: pass, fail, not_yet (with the reasons)."""
    reasons = []
    dn = delta["n_sessions"] if delta else 0
    met = n >= floor and days >= GATE_DAYS
    if met and exp and (exp["hi"] < 0 or (dn >= floor and delta["hi"] < 0)):
        why = []
        if exp["hi"] < 0:
            why.append("the net expectancy interval [%+.3f, %+.3f] is wholly under 0" % (exp["lo"], exp["hi"]))
        if dn >= floor and delta["hi"] < 0:
            why.append("the delta against the random-entry control [%+.3f, %+.3f] over %d paired sessions is wholly "
                       "under 0" % (delta["lo"], delta["hi"], dn))
        return {"state": "fail", "reasons": why,
                "text": "GATE FAILS: n %d and %d days are met, and %s." % (n, days, "; and ".join(why))}
    if met and exp and exp["lo"] > 0 and dn >= floor and delta["lo"] > 0:
        return {"state": "pass", "reasons": [],
                "text": ("GATE PASSES: n %d, %d days, the net expectancy interval [%+.3f, %+.3f] wholly over 0 and the "
                         "delta against the random-entry control [%+.3f, %+.3f] over %d paired sessions wholly over 0."
                         % (n, days, exp["lo"], exp["hi"], delta["lo"], delta["hi"], dn))}
    if n < floor:
        reasons.append("n %d of the %d scored triggers" % (n, floor))
    if days < GATE_DAYS:
        reasons.append("%d of the %d days since the first trigger%s" % (days, GATE_DAYS,
                                                                         (" (%s)" % first) if first else ""))
    if not exp:
        reasons.append("no scored trigger yet")
    elif not exp["lo"] > 0:
        reasons.append("the net expectancy interval [%+.3f, %+.3f] is not wholly over 0" % (exp["lo"], exp["hi"]))
    if not delta:
        reasons.append("no trigger paired with a control yet")
    else:
        if dn < floor:
            reasons.append("%d of the %d paired control sessions" % (dn, floor))
        if not delta["lo"] > 0:
            reasons.append("the control delta interval [%+.3f, %+.3f] is not wholly over 0" % (delta["lo"], delta["hi"]))
    return {"state": "not_yet", "reasons": reasons, "text": "GATE NOT YET: " + "; ".join(reasons) + "."}


def report_doc(book, today, setup=None, since=None):
    ledger, stats = _measure("ledger"), _measure("stats")
    trig = _filtered(book, setup, since)
    ids = set(t["id"] for t in trig)
    scores = book["scores"]
    paper = [(t, scores[t["id"]]) for t in trig if scores.get(t["id"], {}).get("outcome") in ledger.SCORED]
    nets = [float(s["net_r"]) for _, s in paper]
    exp = _ci(stats, nets)
    gross = _ci(stats, [float(s["gross_r"]) for _, s in paper])
    dec_rate = stats.decided_rate([s["outcome"] for _, s in paper])
    trs = set((t.get("plan") or {}).get("target_r") for t, _ in paper)
    cost_mean = (sum(float(s.get("cost_r") or 0) for _, s in paper) / len(paper)) if paper else None
    be = None
    if dec_rate["n"] and len(trs) == 1 and None not in trs and "price" not in trs:
        be = stats.net_break_even(float(list(trs)[0]), cost_mean)
    ctrl_by, rule_by = {}, {}
    for c in book["controls"]:
        s = scores.get(c["id"])
        if c.get("paired_id") in ids and s and s.get("outcome") in ledger.SCORED:
            ctrl_by.setdefault(c["paired_id"], []).append(float(s["net_r"]))
    for t, s in paper:
        rule_by[t["id"]] = [float(s["net_r"])]
    paired = [k for k in rule_by if k in ctrl_by]
    delta = stats.paired_delta_ci(rule_by, ctrl_by) if paired else None
    ctrl_all = [x for k in paired for x in ctrl_by[k]]
    dates = sorted(str(t.get("date")) for t in trig)
    first = dates[0] if dates else None
    days = (today - datetime.date.fromisoformat(first)).days if first else 0
    decisions = {"taken": 0, "skipped": 0, "undecided": 0}
    for t in trig:
        d = ledger.decision_of(book, t)
        decisions["taken" if d.get("taken") is True else "skipped" if d.get("taken") is False else "undecided"] += 1
    taken = [(t, s) for t, s in paper if ledger.is_taken(book, t)]
    taken_r = [ledger.realized_r(s) for _, s in taken]
    outcomes = {}
    for t in trig:
        o = scores.get(t["id"], {}).get("outcome") or "not scored"
        outcomes[o] = outcomes.get(o, 0) + 1
    gate = gate_of(len(paper), days, first, exp, delta, stats.N_FLOOR)
    rules = {}
    for t in trig:
        rules.setdefault(t.get("rule_hash"), {"rule": t.get("rule"), "n": 0})["n"] += 1
    return {
        "created_by": "trader-record", "today": today.isoformat(), "filters": {"setup": setup, "since": since},
        "record": {"dir": book["dir"], "triggers_path": book["triggers_path"], "lines": len(book["rows"]),
                   "scores": len(scores), "as_of": book["as_of"]},
        "counts": {"triggers": len(trig), "outcomes": outcomes, "decisions": decisions,
                   "controls": sum(1 for c in book["controls"] if c.get("paired_id") in ids), "rules": rules},
        "paper": {"n": len(paper), "expectancy": exp, "gross": gross, "decided": dec_rate, "cost_r_mean": cost_mean,
                  "net_break_even": be, "target_r": sorted(str(x) for x in trs)},
        "control": {"n": len(ctrl_all), "expectancy": _ci(stats, ctrl_all), "delta": delta},
        "taken": {"n": len(taken), "realized": _ci(stats, taken_r),
                  "broker_basis": sum(1 for _, s in taken if s.get("fill_basis") == "broker")},
        "days": days, "first_trigger": first, "gate": gate, "note": NOTE_PRICES, "footer": FOOTER,
    }


def _iv(ci):
    return "%+.3f R a trade (95%% bootstrap [%+.3f, %+.3f], n %d)" % (ci["mean"], ci["lo"], ci["hi"], ci["n"])


def _pc(x):
    return "%.1f%%" % (100.0 * x)


def report_lines(doc):
    c, p, k, tk = doc["counts"], doc["paper"], doc["control"], doc["taken"]
    out = ["Forward record %s: %d lines, %d scores, as of %s. Today %s (New York)." % (
        doc["record"]["triggers_path"], doc["record"]["lines"], doc["record"]["scores"], doc["record"]["as_of"] or "-",
        doc["today"])]
    if doc["filters"]["setup"] or doc["filters"]["since"]:
        out.append("Filtered: setup %s, since %s." % (doc["filters"]["setup"] or "any", doc["filters"]["since"] or "the start"))
    oc = c["outcomes"]
    out.append("Triggers: %d recorded; scored %d target, %d stop, %d close; %d no data; %d not scored yet." % (
        c["triggers"], oc.get("target", 0), oc.get("stop", 0), oc.get("close", 0), oc.get("no_data", 0),
        oc.get("not scored", 0)))
    d = c["decisions"]
    out.append("Decisions: %d taken, %d skipped, %d undecided. Controls: %d rows." % (
        d["taken"], d["skipped"], d["undecided"], c["controls"]))
    if p["n"]:
        out.append("Paper, every scored trigger (taken or not): net average %s." % _iv(p["expectancy"]))
        out.append("  Gross %s; costs %.3f R a trade on average." % (_iv(p["gross"]), p["cost_r_mean"]))
        dr = p["decided"]
        if dr["n"]:
            line = "  Decided: %d of %d hit the target (%s, 95%% Wilson [%s, %s])" % (
                dr["k"], dr["n"], _pc(dr["p"]), _pc(dr["lo"]), _pc(dr["hi"]))
            if p["net_break_even"] is not None:
                line += " against a net break-even of %s at %sR after costs" % (_pc(p["net_break_even"]),
                                                                                 p["target_r"][0])
            else:
                line += "; no single break-even (the targets differ, or there is none)"
            out.append(line + ".")
        else:
            out.append("  Decided: none yet (every scored trigger exited at the flat-by close).")
    else:
        out.append("Paper: no scored trigger yet.")
    if k["delta"]:
        dl = k["delta"]
        out.append("Random-entry control: %d trades, net average %s; delta %+.3f R a trade (95%% bootstrap [%+.3f, "
                   "%+.3f]) over %d paired sessions." % (k["n"], _iv(k["expectancy"]), dl["delta"], dl["lo"], dl["hi"],
                                                         dl["n_sessions"]))
    else:
        out.append("Random-entry control: no trigger paired with a scored control yet.")
    if tk["n"]:
        out.append("Taken subset (beside the paper rows, never instead of them): %d trades, realized net average %s; "
                   "%d from the broker's fills, %d on paper." % (tk["n"], _iv(tk["realized"]), tk["broker_basis"],
                                                                tk["n"] - tk["broker_basis"]))
    else:
        out.append("Taken subset (beside the paper rows, never instead of them): no taken trade scored yet.")
    out.append("Days: %d since the first trigger (%s); the gate needs %d." % (doc["days"], doc["first_trigger"] or "none",
                                                                            GATE_DAYS))
    if len(c["rules"]) > 1:
        out.append("Rules in this record: %d (%s); use --setup to read one." % (
            len(c["rules"]), ", ".join("%s n %d" % (h, v["n"]) for h, v in sorted(c["rules"].items()))))
    out.append(doc["note"])
    out.append("")
    out.append(doc["gate"]["text"])
    out.append(doc["footer"])
    return out


# ---------------------------------------------------------------- the journal

def _block(stats, rows):
    """Stats of [(trigger, score, R)]: realized R, expectancy, win rate (Wilson), profit factor, average winner
    and loser, largest loss, MAE and MFE means."""
    rs = [r for _, _, r in rows]
    if not rs:
        return {"n": 0}
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    lo, hi = stats.wilson(len(wins), len(rs))
    return {"n": len(rs), "total_r": sum(rs), "expectancy": stats.expectancy_ci(rs), "wins": len(wins),
            "losses": len(losses), "win_rate": len(wins) / float(len(rs)), "wilson": [lo, hi],
            "profit_factor": (sum(wins) / -sum(losses)) if losses else None,
            "avg_winner_r": (sum(wins) / len(wins)) if wins else None,
            "avg_loser_r": (sum(losses) / len(losses)) if losses else None,
            "largest_loss_r": min(losses) if losses else None,
            "mae_mean_r": sum(float(s.get("mae_r") or 0) for _, s, _ in rows) / len(rows),
            "mfe_mean_r": sum(float(s.get("mfe_r") or 0) for _, s, _ in rows) / len(rows)}


def journal_doc(book, today, setup=None, since=None):
    ledger, stats = _measure("ledger"), _measure("stats")
    trig = _filtered(book, setup, since)
    groups = {"taken": [], "skipped": [], "undecided": []}
    for t in trig:
        s = book["scores"].get(t["id"])
        if not s or s.get("outcome") not in ledger.SCORED:
            continue
        d = ledger.decision_of(book, t)
        if d.get("taken") is True:
            groups["taken"].append((t, s, ledger.realized_r(s)))
        elif d.get("taken") is False:
            groups["skipped"].append((t, s, float(s["net_r"])))
        else:
            groups["undecided"].append((t, s, float(s["net_r"])))
    out = {"created_by": "trader-record", "today": today.isoformat(), "filters": {"setup": setup, "since": since},
           "basis": {"taken": "realized: the broker's fills where entered, else the paper score",
                     "skipped": "paper: the rule's score", "undecided": "paper: the rule's score"},
           "blocks": {k: _block(stats, v) for k, v in groups.items()}, "by_setup": {}, "by_month": {},
           "footer": FOOTER}
    for name, key in (("by_setup", lambda t: str(t.get("setup"))), ("by_month", lambda t: str(t.get("date"))[:7])):
        keys = sorted(set(key(t) for v in groups.values() for t, _, _ in v))
        for kk in keys:
            out[name][kk] = {g: _block(stats, [x for x in v if key(x[0]) == kk]) for g, v in groups.items()}
    return out


def _bline(name, b):
    if not b.get("n"):
        return "%-9s n 0" % name
    pf = "n/a (no losing trade)" if b["profit_factor"] is None else "%.2f" % b["profit_factor"]
    return ("%-9s n %d, total %+.3f R, expectancy %s; won %d of %d (%s, 95%% Wilson [%s, %s]); profit factor %s; "
            "average winner %s, average loser %s, largest loss %s; MAE mean %+.3f R, MFE mean %+.3f R" % (
                name, b["n"], b["total_r"], _iv(b["expectancy"]), b["wins"], b["n"], _pc(b["win_rate"]),
                _pc(b["wilson"][0]), _pc(b["wilson"][1]), pf,
                "n/a" if b["avg_winner_r"] is None else "%+.3f R" % b["avg_winner_r"],
                "n/a" if b["avg_loser_r"] is None else "%+.3f R" % b["avg_loser_r"],
                "n/a" if b["largest_loss_r"] is None else "%+.3f R" % b["largest_loss_r"],
                b["mae_mean_r"], b["mfe_mean_r"]))


def journal_lines(doc):
    out = ["Journal, as of %s (New York). Taken trades are realized (the broker's fills where entered, else paper); "
           "skipped and undecided triggers are the rule's paper score." % doc["today"]]
    for g in ("taken", "skipped", "undecided"):
        out.append(_bline(g, doc["blocks"][g]))
    for name, title in (("by_setup", "By setup"), ("by_month", "By month")):
        out.append("")
        out.append(title + ":")
        if not doc[name]:
            out.append("  nothing scored yet")
        for k, v in sorted(doc[name].items()):
            out.append("  %s" % k)
            for g in ("taken", "skipped", "undecided"):
                if v[g].get("n"):
                    out.append("    " + _bline(g, v[g]))
    out.append("")
    out.append(doc["footer"])
    return out


# ---------------------------------------------------------------- commands

def cmd_add(a):
    now = parse_now(a.now)
    doc = read_json(a.from_path, "entry (run trader-entry first)")
    if not isinstance(doc, dict):
        raise RecordFail("%s is not an entry document" % a.from_path)
    plan = read_json(a.plan, "plan", required=bool(a.plan)) if a.plan else None
    decision = None
    if a.taken and a.skipped:
        raise RecordFail("--taken or --skipped, not both")
    if a.taken:
        if not a.fingerprint:
            raise RecordFail("--taken needs --fingerprint (the order trader-risk passed)")
        decision = {"taken": True, "reason": "taken", "risk_fingerprint": a.fingerprint,
                    "broker_fingerprint": a.fingerprint, "risk_verdict": None, "qty": a.qty,
                    "max_loss_usd": a.max_loss, "decided_at": iso(now)}
    elif a.skipped:
        decision = {"taken": False, "reason": a.skipped, "decided_at": iso(now)}
    got = record_trigger(doc, plan, decision, a.config, a.source or os.environ.get("TRADER_SOURCE") or "yahoo", now,
                         a.now, bars_label=doc.get("source"), record_dir=a.record_dir)
    print(got["message"][0].upper() + got["message"][1:] + ".")
    return 0 if got["state"] in ("appended", "exists", "decided") else 1


def cmd_score(a):
    now = parse_now(a.now)
    if a.control_draws < 0 or a.control_draws > 10:
        raise RecordFail("--control-draws is 0 to 10")
    day = a.date or today_et(now).isoformat()
    try:
        datetime.date.fromisoformat(day)
    except ValueError:
        raise RecordFail("--date wants YYYY-MM-DD, not %r" % day)
    syms = [s.strip().upper() for s in a.symbols.split(",")] if a.symbols else None
    src = a.source or os.environ.get("TRADER_SOURCE") or "massive"
    res = score_day(day, src, a.offline, a.control_draws, now, a.state, a.record_dir, syms)
    for line in res["lines"]:
        print(line)
    print("Appended %d score line(s) and %d control row(s)%s." % (
        res["appended"]["scores"], res["appended"]["triggers"],
        "; %d trigger(s) not scored yet (run score again when the bars are in)" % res["pending"] if res["pending"]
        else ""))
    return 2 if res["pending"] else 0


def cmd_report(a):
    now = parse_now(a.now)
    book = _measure("ledger").load(a.record_dir)
    doc = report_doc(book, today_et(now), a.setup, a.since)
    if a.json:
        print(json.dumps(doc, indent=2, default=str))
    else:
        print("\n".join(report_lines(doc)))
    return 0


def cmd_journal(a):
    now = parse_now(a.now)
    book = _measure("ledger").load(a.record_dir)
    doc = journal_doc(book, today_et(now), a.setup, a.since)
    if a.json:
        print(json.dumps(doc, indent=2, default=str))
    else:
        print("\n".join(journal_lines(doc)))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Forward Record (trader-record): every trigger, scored, and the gate.")
    sub = ap.add_subparsers(dest="cmd")

    def common(p):
        p.add_argument("--record-dir", help="default ${TRADER_RECORD_DIR:-record} (cwd-relative)")
        p.add_argument("--now", help='pretend it is this New York time, e.g. "2026-10-19 16:30"')

    p = sub.add_parser("add", help="append a trigger (and a decision) once")
    common(p)
    p.add_argument("--from", dest="from_path", default="trader/entry.json", help="the entry (trader/entry.json)")
    p.add_argument("--plan", help="the plan (trader/plan.json); default: trader-exit's defaults for the setup")
    p.add_argument("--taken", action="store_true", help="the owner took it (with --fingerprint)")
    p.add_argument("--fingerprint", help="the order's fingerprint (trader-risk and trader-broker)")
    p.add_argument("--qty", type=float, help="shares taken")
    p.add_argument("--max-loss", type=float, help="the order's planned max loss net of costs, $")
    p.add_argument("--skipped", metavar="REASON", help="the owner skipped it, and why")
    p.add_argument("--config", default="trader/config.json")
    p.add_argument("--source", choices=["yahoo", "massive"], help="for a default plan's cost card")
    p = sub.add_parser("score", help="score a day's triggers and their controls, once")
    common(p)
    p.add_argument("--date", help="YYYY-MM-DD (default today, New York)")
    p.add_argument("--offline", metavar="PATH", help="a saved chart JSON (.json/.json.gz) or a folder of <SYM>.json")
    p.add_argument("--source", choices=["yahoo", "massive"], help="default massive (or TRADER_SOURCE)")
    p.add_argument("--control-draws", type=int, default=1)
    p.add_argument("--symbols", help="only these, comma-separated")
    p.add_argument("--state", default="trader/state/broker.json", help="the hand-entered fills (ticket.py fill)")
    for name, help_ in (("report", "counts, intervals, the control and the gate"),
                        ("journal", "taken beside skipped, by setup and by month")):
        p = sub.add_parser(name, help=help_)
        common(p)
        p.add_argument("--setup")
        p.add_argument("--since", help="YYYY-MM-DD")
        p.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    ledger = _measure("ledger")
    try:
        return {"add": cmd_add, "score": cmd_score, "report": cmd_report, "journal": cmd_journal}[a.cmd](a)
    except (RecordFail, ledger.RecordError) as e:
        print("record.py: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
