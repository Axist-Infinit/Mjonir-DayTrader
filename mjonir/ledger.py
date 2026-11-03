"""The forward record's two files (chunk 3.1). Stdlib only, Python 3.8 syntax: trader-record/record.py
writes and reads them, trader-risk/check.py reads them (one definition, P8).

    record_dir(d)            ${TRADER_RECORD_DIR:-record}, cwd-relative like trader/
    paths(d)                 (<dir>/triggers.jsonl, <dir>/scores.jsonl)
    read_rows(path)          every row in file order; [] when the file is absent; a line that is not a JSON
                             object with an id, or a last line without its newline, raises RecordError
                             naming the file and the line (P7: the record is fixed by hand, never rewritten)
    append_rows(path, rows)  one line a row, opened with mode "a" and nothing else (P7)
    load(d)                  the book: trigger, control and decision rows, the scores by id
    trigger_id, rule_hash, control_id, decision_id   identifiers only (sha256, hex, truncated)
    decision_of(book, t)     the last decision row for a trigger, else its inline decision
    realized(book, a, b)     taken trades dated a..b: realized net dollars of the scored ones plus the
                             planned net max loss of the ones not scored yet
    loss_streak(book, n)     the date of the last of n taken, scored trades in a row that all lost net

triggers.jsonl holds rows of three kinds: "trigger" (one line per trigger the entry timer saw, taken or
not), "control" (a random-entry control drawn on that trigger's session, paired_id = the trigger) and
"decision" (the owner's yes or no, paired_id = the trigger, appended after the trigger when it was
written first). scores.jsonl holds one line per scored id (a trigger or a control), written once.
"""

import hashlib
import json
import os

SCHEMA = 1
TRIGGERS = "triggers.jsonl"
SCORES = "scores.jsonl"
SCORED = ("target", "stop", "close")      # a paper score; "no_data" is not one
RULE_KEYS = ("setup", "interval", "or_minutes", "min_volume_x", "stop_rule", "stop_param", "target_r", "exit")


class RecordError(ValueError):
    pass


def record_dir(d=None):
    return d or os.environ.get("TRADER_RECORD_DIR") or "record"


def paths(d=None):
    d = record_dir(d)
    return os.path.join(d, TRIGGERS), os.path.join(d, SCORES)


# ---------------------------------------------------------------- the files (the only two opens)

def read_rows(path):
    """Every row of a record file, in order. The file absent: []. Raises RecordError on a line that is not a
    JSON object with an "id", and on a last line without its newline (a cut write)."""
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    if text and not text.endswith("\n"):
        n = text.count("\n") + 1
        raise RecordError("%s line %d has no newline at its end: the last write was cut. Fix that line by hand "
                          "(the record is append-only; no script rewrites it)" % (path, n))
    for n, line in enumerate(text.split("\n")[:-1] if text else [], 1):
        try:
            row = json.loads(line)
        except ValueError as e:
            raise RecordError("%s line %d is not valid JSON (%s). Fix it by hand (the record is append-only; no "
                              "script rewrites it)" % (path, n, e))
        if not isinstance(row, dict) or not row.get("id"):
            raise RecordError("%s line %d is not a record row (a JSON object with an id)" % (path, n))
        row["_line"] = n
        rows.append(row)
    return rows


def append_rows(path, rows):
    """Append rows, one JSON line each (P7: mode "a" only, never a rewrite)."""
    if not rows:
        return 0
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        for r in rows:
            clean = {k: v for k, v in r.items() if not k.startswith("_")}
            fh.write(json.dumps(clean, sort_keys=True) + "\n")
    return len(rows)


# ---------------------------------------------------------------- identifiers

def _h(text, n=16):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:n]


def rule_hash(rule):
    """The rule's identity: the keys that change which bar triggers and how it is scored (RULE_KEYS). The
    flat-by and the entry window are recorded beside it, not hashed: an early close moves them."""
    core = {k: (rule or {}).get(k) for k in RULE_KEYS}
    return _h(json.dumps(core, sort_keys=True, separators=(",", ":")), 12)


def trigger_id(symbol, date, setup, trigger_time, rhash):
    return _h("%s|%s|%s|%s|%s" % (symbol, date, setup, trigger_time, rhash))


def control_id(trigger, draw, seed):
    return _h("control|%s|%s|%s" % (trigger, draw, seed))


def decision_id(trigger, taken, reason, fingerprint):
    return _h("decision|%s|%s|%s|%s" % (trigger, taken, reason, fingerprint or ""))


# ---------------------------------------------------------------- the book

def load(d=None):
    """The record as one dict. Raises RecordError on a bad line or on a second score for one id."""
    tp, sp = paths(d)
    rows = read_rows(tp)
    scores = {}
    for s in read_rows(sp):
        if s["id"] in scores:
            raise RecordError("%s line %d scores %s a second time (line %d has it): one score line per id"
                              % (sp, s["_line"], s["id"], scores[s["id"]]["_line"]))
        scores[s["id"]] = s
    book = {"dir": record_dir(d), "triggers_path": tp, "scores_path": sp, "exists": os.path.exists(tp),
            "rows": rows, "triggers": [], "controls": [], "decisions": {}, "ids": set(), "scores": scores,
            "as_of": None}
    stamps = []
    for r in rows:
        book["ids"].add(r["id"])
        kind = r.get("kind")
        if kind == "trigger":
            book["triggers"].append(r)
        elif kind == "control":
            book["controls"].append(r)
        elif kind == "decision":
            book["decisions"].setdefault(r.get("paired_id"), []).append(r)
        if r.get("recorded_at"):
            stamps.append(r["recorded_at"])
    stamps += [s["scored_at"] for s in scores.values() if s.get("scored_at")]
    book["as_of"] = max(stamps) if stamps else None
    return book


def trigger_key(row):
    """(symbol, date, setup, trigger time): one trigger event, whatever rule scores it."""
    return (row.get("symbol"), row.get("date"), row.get("setup"), (row.get("trigger") or {}).get("time"))


def decision_of(book, t):
    """The trigger's decision: the last decision row appended for it, else the one written with it."""
    later = book["decisions"].get(t["id"])
    if later:
        return later[-1].get("decision") or {}
    return t.get("decision") or {}


def is_taken(book, t):
    return decision_of(book, t).get("taken") is True


def realized_r(score):
    """A taken trade's realized net R: the broker's fills when the score carries them, else the paper R."""
    b = score.get("broker") if score.get("fill_basis") == "broker" else None
    if b and b.get("net_r") is not None:
        return float(b["net_r"])
    return float(score["net_r"])


def net_usd(t, score, decision):
    """A taken, scored trade's net dollars: the broker's when the score carries fills, else the paper net R x
    the shares taken x the plan's risk a share. None when the share count is unknown."""
    b = score.get("broker") if score.get("fill_basis") == "broker" else None
    if b and b.get("net_usd") is not None:
        return float(b["net_usd"])
    qty = decision.get("qty")
    risk = (t.get("plan") or {}).get("risk_per_share")
    try:
        return float(score["net_r"]) * float(qty) * float(risk)
    except (TypeError, ValueError, KeyError):
        return None


def realized(book, start, end):
    """Taken trades dated start..end (ISO dates, both included): {realized_usd, open_usd, scored, open,
    unknown}. realized_usd sums the scored trades' net dollars; open_usd sums the planned net max loss of the
    taken trades not scored yet; unknown lists the trades neither number could be read for."""
    out = {"realized_usd": 0.0, "open_usd": 0.0, "scored": 0, "open": 0, "unknown": []}
    for t in book["triggers"]:
        if not (start <= str(t.get("date")) <= end) or not is_taken(book, t):
            continue
        dec = decision_of(book, t)
        s = book["scores"].get(t["id"])
        label = "%s %s %s" % (t.get("date"), t.get("symbol"), (t.get("trigger") or {}).get("time"))
        if s and s.get("outcome") in SCORED:
            usd = net_usd(t, s, dec)
            if usd is None:
                out["unknown"].append("%s: scored, but the shares taken are not in the record" % label)
            else:
                out["realized_usd"] += usd
                out["scored"] += 1
        elif s:
            out["unknown"].append("%s: taken, scored %s (no paper outcome)" % (label, s.get("outcome")))
        else:
            ml = dec.get("max_loss_usd")
            try:
                out["open_usd"] += float(ml)
                out["open"] += 1
            except (TypeError, ValueError):
                out["unknown"].append("%s: taken, not scored, and no planned max loss in the record" % label)
    out["realized_usd"] = round(out["realized_usd"], 2)
    out["open_usd"] = round(out["open_usd"], 2)
    return out


def taken_scored(book):
    """[(trigger, score)] of taken trades with a paper outcome, oldest first (date, trigger time)."""
    rows = [(t, book["scores"][t["id"]]) for t in book["triggers"]
            if is_taken(book, t) and book["scores"].get(t["id"], {}).get("outcome") in SCORED]
    rows.sort(key=lambda p: (str(p[0].get("date")), str((p[0].get("trigger") or {}).get("time"))))
    return rows


def loss_streak(book, n):
    """The date of the last trade when the last n taken, scored trades all lost net (realized R < 0), else
    None. n < 1: None."""
    if not n or int(n) < 1:
        return None
    rows = taken_scored(book)
    if len(rows) < int(n):
        return None
    last = rows[-int(n):]
    if all(realized_r(s) < 0 for _, s in last):
        return str(last[-1][0].get("date"))
    return None
