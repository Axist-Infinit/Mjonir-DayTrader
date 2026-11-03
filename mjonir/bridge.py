"""The bridge: Massive data written as the Yahoo-shaped files upstream's ``--offline`` readers take.
Run from the repo root (``trader/`` is cwd-relative):

    python3 -m mjonir.bridge probe                              # authenticated / rejected / unverified
    python3 -m mjonir.bridge status                             # key, probe, calendar, cache, local stores
    python3 -m mjonir.bridge calendar                           # trader/calendar.json from marketstatus
    python3 -m mjonir.bridge universe                           # trader/universe.txt + funnel record
    python3 -m mjonir.bridge daily [--sessions 65]              # one spark bundle for scan.py daily --offline
    python3 -m mjonir.bridge intraday TSLA,NVDA --day 2026-10-19 [--interval 5m|1m] [--bundle]
    python3 -m mjonir.bridge history TSLA --from 2026-07-27 --to 2026-10-19 [--source auto|api|kalex|flatfile]
    python3 -m mjonir.bridge quotes TSLA,AAPL                    # massive-<SYM>.json for alerts.py --offline
    python3 -m mjonir.bridge news TSLA [--hours 48]              # massive-news-<SYM>.json for news.py --offline

Files, by verb (``--out`` moves them):
  intraday   <out>/<SYM>.json (entry.py / exit.py --offline DIR), or with --bundle
             <out>/wall5m-<D>.json.gz (scan.py orb --offline FILE); default trader/data/intraday/<D>/
  history    <out>/<SYM>-60d5m.json.gz (timemachine.py --offline DIR; the name is upstream's, meta.range
             says how many sessions it really holds); default trader/data/history/
  daily      <out>/daily-spark-<D>.json (scan.py daily --offline FILE); default trader/data/daily/
  quotes     <out>/massive-<SYM>.json; news <out>/massive-news-<SYM>.json; default trader/data/quotes|news/

Every verb takes ``--now`` (New York, like the scripts), ``--json`` and ``--out``. Exit codes: 0 ok,
1 refused (the API or the data said no: P11, a closed day, 401/403), 2 unverified (could not ask).
Options, indices (I:) and Benzinga are not entitled on this key: never tried, and ``status`` says so.
The key is never printed: ``status`` names the variable that holds it, never its value.
"""

import argparse
import datetime as _dt
import gzip
import json
import os
import re
import sys
import time

from . import cache as CA
from . import calendar as K
from . import config as C
from . import localstores as LS
from . import massive as M
from . import universe as U
from . import yahoo_shape as Y

OK, REFUSED, UNVERIFIED = 0, 1, 2


def code_of(exc):
    return REFUSED if Y.outcome_of(exc) == "refused" else UNVERIFIED


def symbols_of(items):
    out = []
    for it in items or []:
        for s in re.split(r"[,\s]+", str(it).upper()):
            if s and s not in out:
                out.append(s)
    return out


def write_json(path, doc, gz=False, indent=None):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    if gz:
        with gzip.open(tmp, "wt", encoding="utf-8") as fh:
            json.dump(doc, fh, separators=(",", ":"))
    else:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=indent, separators=None if indent else (",", ":"))
            fh.write("\n")
    os.replace(tmp, path)
    return path


def emit(a, doc, lines):
    if a.json:
        print(json.dumps(doc, indent=2, default=str))
    else:
        for ln in lines:
            print(ln)


def _data(*parts):
    return os.path.join(str(C.data_dir()), *parts)


# ---------------------------------------------------------------- verbs

def cmd_probe(a, client):
    res = client.probe()
    code = {"authenticated": OK, "rejected": REFUSED}.get(res["outcome"], UNVERIFIED)
    emit(a, dict(res, not_entitled=M.NOT_ENTITLED_WORDS),
         ["Massive key: %s (%s)." % (res["outcome"].upper(), res["detail"]),
          "Not entitled: %s." % M.NOT_ENTITLED_WORDS])
    return code


def key_status():
    layers = C.env_layers()
    name = next((n for n in C.KEY_NAMES if layers.get(n)), None)
    repo_env = C.repo_env_path()
    bad = C.key_like_values(repo_env) if repo_env.exists() else []
    out = {"present": name is not None, "variable": name, "repo_env": str(repo_env),
           "repo_env_key_like": bad}
    if bad:
        out["warning"] = ("%s holds %s: a local plugin install copies gitignored files into the plugin cache. "
                          "Keep the key in ~/Infinit/.env and delete it from %s." % (repo_env, ", ".join(bad),
                                                                                       repo_env))
    return out


def cmd_status(a, client_factory):
    t0 = time.time()
    doc = {"key": key_status(), "not_entitled": M.NOT_ENTITLED_WORDS}
    try:
        doc["probe"] = client_factory().probe()
    except M.MassiveError as e:
        doc["probe"] = {"outcome": "unverified", "detail": str(e)}
    cp = K.calendar_path()
    cal_doc = None
    try:
        with open(cp, encoding="utf-8") as fh:
            cal_doc = json.load(fh)
    except (OSError, ValueError):
        pass
    doc["calendar"] = {"path": cp, "exists": cal_doc is not None,
                       "covered_years": (cal_doc or {}).get("covered_years") or list(K.SEED_YEARS),
                       "known_through": (cal_doc or {}).get("known_through"),
                       "generated_at": (cal_doc or {}).get("generated_at")}
    cpath = CA.default_path()
    if os.path.exists(cpath):
        c = CA.Cache(cpath)
        doc["cache"] = c.stats()
        c.close()
    else:
        doc["cache"] = {"path": cpath, "exists": False}
    uni = os.path.join("trader", "universe.txt")
    n_uni = None
    if os.path.exists(uni):
        with open(uni, encoding="utf-8") as fh:
            n_uni = sum(1 for ln in fh if ln.strip() and not ln.startswith("#"))
    doc["universe"] = {"path": uni, "symbols": n_uni}
    doc["stores"] = LS.stores_status()
    doc["now_et"] = K.now_et(a.now).strftime("%Y-%m-%d %H:%M %Z")
    doc["seconds"] = round(time.time() - t0, 1)
    k = doc["key"]
    lines = ["Massive key: %s; probe %s." % ("present in " + k["variable"] if k["present"] else "MISSING",
                                             doc["probe"]["outcome"].upper()),
             "Not entitled: %s." % M.NOT_ENTITLED_WORDS]
    if k.get("warning"):
        lines.append("WARNING: " + k["warning"])
    cd = doc["calendar"]
    lines.append("Calendar: %s, covers %s%s." % (cd["path"] if cd["exists"] else "seeds only (run bridge calendar)",
                                                 ", ".join(map(str, cd["covered_years"])),
                                                 (", vendor list through %s" % cd["known_through"])
                                                 if cd["known_through"] else ""))
    ch = doc["cache"]
    lines.append("Cache: %s." % ("%s bars, %s symbols, %s grouped days" % (ch["bars"], ch["symbols"],
                                                                         ch["grouped_days"])
                                 if "bars" in ch else "none yet"))
    lines.append("Universe: %s." % ("%d symbols in %s" % (n_uni, uni) if n_uni else "none yet (run bridge universe)"))
    st = doc["stores"]
    kx = st["kalex_5m"]
    lines.append("Kalex 5m: %s%s." % (kx["state"], (", %s symbols, %s" % (kx.get("symbols"), kx["path"]))
                                      if kx["state"] == "ok" else ""))
    ff = st["flatfiles"]
    lines.append("Flat files: %s%s." % (ff["state"], (", %s days %s to %s (unadjusted)" % (
        ff.get("files"), ff.get("first_day"), ff.get("last_day"))) if ff["state"] == "ok" else ""))
    emit(a, doc, lines)
    if not k["present"]:
        return REFUSED
    return {"authenticated": OK, "rejected": REFUSED}.get(doc["probe"]["outcome"], UNVERIFIED)


def cmd_calendar(a, client):
    doc = K.build_calendar_doc(client, a.now)
    out = a.out or K.calendar_path()
    write_json(out, doc, indent=1)
    emit(a, dict(doc, out=out), [
        "Wrote %s: %d holidays, %d early closes; covers %s (basis %s); vendor list through %s." % (
            out, len(doc["holidays"]), len(doc["early_closes"]), ", ".join(map(str, doc["covered_years"])),
            ", ".join("%s %s" % kv for kv in doc["basis"].items()), doc["known_through"])])
    return OK


def cmd_universe(a, client):
    t0 = time.time()
    cal = K.Calendar.load()
    mp, ma = U.floors()
    mp = a.min_price if a.min_price is not None else mp
    ma = a.min_adv_usd if a.min_adv_usd is not None else ma
    cache = CA.Cache()
    try:
        res = U.build(client, cal, a.as_of, mp, ma, sessions=a.sessions, cache=cache, clock=a.now)
    finally:
        cache.close()
    out, rec = U.write(res, a.out or os.path.join("trader", "universe.txt"))
    secs = round(time.time() - t0, 1)
    c = res["counts"]
    emit(a, {"out": out, "record": rec, "as_of": res["as_of"], "funnel": c, "kept": len(res["kept"]),
             "requests": client.requests, "seconds": secs},
         ["Universe as of %s: %d of %d reference rows kept (%s)." % (
             res["as_of"], len(res["kept"]), c["rows"],
             ", ".join("%s %d" % (k, v) for k, v in c.items() if k not in ("rows", "keep"))),
          "Wrote %s and %s (%d requests, %.1f s)." % (out, rec, client.requests, secs)])
    return OK


def cmd_daily(a, client):
    t0 = time.time()
    if a.symbols:
        syms = symbols_of(a.symbols)
    else:
        path = a.universe or os.path.join("trader", "universe.txt")
        if not os.path.exists(path):
            raise M.Refused("no %s: run `python3 -m mjonir.bridge universe` first, or pass --symbols" % path)
        with open(path, encoding="utf-8") as fh:
            syms = [ln.split("|")[0].strip().upper() for ln in fh if ln.strip() and not ln.startswith("#")]
    doc, info = Y.fetch_daily_bundle(client, None, syms, a.sessions, a.end, a.now)
    out = os.path.join(a.out or _data("daily"), "daily-spark-%s.json" % info["to"])
    write_json(out, doc)
    secs = round(time.time() - t0, 1)
    emit(a, dict(info, out=out, seconds=secs, failed_symbols=doc["mjonir"]["failed_symbols"]),
         ["Daily bundle: %d of %d symbols, %d sessions %s to %s (%d refetched for a split); %d failed." % (
             info["built"], info["symbols"], info["sessions"], info["from"], info["to"],
             len(info["split_refetched"]), info["failed"]),
          "Wrote %s (%d requests, %.1f s). Next: python3 trader-scanner/scan.py daily --offline %s" % (
              out, client.requests, secs, out)])
    return OK if info["built"] else REFUSED


def cmd_intraday(a, client):
    t0 = time.time()
    syms = symbols_of(a.symbols)
    day = K.as_date(a.day)
    out_dir = a.out or _data("intraday", day.isoformat())
    if len(syms) == 1 and not a.bundle:
        docs, errors = {}, {}
        try:
            docs[syms[0]] = Y.fetch_chart_doc(client, None, syms[0], day, a.interval)
        except Y.ERRORS as e:
            errors[syms[0]] = e
    else:
        docs, errs = Y.fetch_charts_bulk(client, None, syms, day, a.interval, workers=a.workers)
        errors = {k: (M.MassiveError(v) if re.search(r"network error|HTTP 5\d\d|no answer", v) else M.Refused(v))
                  for k, v in errs.items()}
    written = []
    if a.bundle:
        p = os.path.join(out_dir, "wall%s-%s.json.gz" % (a.interval, day.isoformat()))
        write_json(p, {Y.yahoo_symbol(s): d for s, d in sorted(docs.items())}, gz=True)
        written.append(p)
    else:
        for s, d in sorted(docs.items()):
            written.append(write_json(os.path.join(out_dir, "%s.json" % Y.yahoo_symbol(s)), d))
    secs = round(time.time() - t0, 1)
    emit(a, {"day": day.isoformat(), "interval": a.interval, "written": written, "symbols": len(syms),
             "built": len(docs), "failed": {k: str(v) for k, v in errors.items()}, "requests": client.requests,
             "seconds": secs},
         ["%s %s bars: %d of %d symbols built%s." % (day, a.interval, len(docs), len(syms),
                                                    ("; failed: " + "; ".join("%s (%s)" % (k, v) for k, v in
                                                                               sorted(errors.items())[:10]))
                                                    if errors else ""),
          "Wrote %s (%d requests, %.1f s)." % (written[0] if len(written) == 1 else "%d files in %s" % (
              len(written), out_dir), client.requests, secs)])
    if docs:
        return OK
    return max([code_of(e) for e in errors.values()] or [REFUSED])


def cmd_history(a, client):
    t0 = time.time()
    sym = a.symbol.upper()
    doc = Y.fetch_history_doc(client, None, sym, getattr(a, "from"), a.to, a.source)
    p = os.path.join(a.out or _data("history"), "%s-60d5m.json.gz" % Y.yahoo_symbol(sym))
    write_json(p, doc, gz=True)
    m = doc["chart"]["result"][0]["meta"]
    mj = m["mjonir"]
    secs = round(time.time() - t0, 1)
    emit(a, {"out": p, "range": m["range"], "first_session": mj["first_session"], "last_session": mj["last_session"],
             "bars": mj["bars"], "source": mj["source"], "adjusted": mj["adjusted"],
             "incomplete_sessions": mj["incomplete_sessions"], "early_closes": mj["early_closes"],
             "requests": client.requests if client else 0, "seconds": secs},
         ["%s history %s to %s: %s sessions, %d bars, source %s (%s)." % (
             sym, mj["first_session"], mj["last_session"], mj["sessions"], mj["bars"], mj["source"],
             "adjusted" if mj["adjusted"] else "UNADJUSTED"),
          "Incomplete sessions: %s." % (", ".join("%s (%d of %d)" % (x["date"], x["bars"], x["expected"])
                                                  for x in mj["incomplete_sessions"]) or "none"),
          "Wrote %s (%.1f s). Next: python3 trader-timemachine/timemachine.py run --offline %s" % (
              p, secs, os.path.dirname(p))])
    return OK


def cmd_quotes(a, client):
    syms = symbols_of(a.symbols)
    docs, errors = Y.fetch_quote_docs(client, None, syms, a.now)
    out_dir = a.out or _data("quotes")
    written = [write_json(os.path.join(out_dir, "massive-%s.json" % s), d) for s, d in sorted(docs.items())]
    lines = []
    for s, d in sorted(docs.items()):
        m = d["chart"]["result"][0]["meta"]
        lines.append("%-6s %10.2f  %s  %s%s" % (s, m["regularMarketPrice"], m["mjonir"]["regular_market_time_basis"],
                                                m["mjonir"]["session"], ("  withheld: " + m["mjonir"]["withheld"])
                                                if m["mjonir"].get("withheld") else ""))
    lines += ["error: %s" % e for e in errors.values()]
    lines.append("Wrote %d file(s) to %s. Next: python3 trader-alerts/alerts.py check --source massive --offline %s"
                 % (len(written), out_dir, out_dir))
    emit(a, {"written": written, "errors": errors}, lines)
    return OK if docs else REFUSED


def cmd_news(a, client):
    syms = symbols_of(a.symbols)
    since = K.now_et(a.now).astimezone(K.UTC) - _dt.timedelta(hours=a.hours)
    out_dir = a.out or _data("news")
    written, counts = [], {}
    for s in syms:
        rows = client.news(Y.massive_symbol(s), since, a.limit)
        counts[s] = len(rows)
        written.append(write_json(os.path.join(out_dir, "massive-news-%s.json" % s), rows, indent=1))
    emit(a, {"written": written, "rows": counts, "since": since.strftime("%Y-%m-%dT%H:%M:%SZ")},
         ["Massive news since %s UTC: %s." % (since.strftime("%Y-%m-%d %H:%M"),
                                              ", ".join("%s %d" % kv for kv in counts.items())),
          "Wrote %d file(s) to %s. Next: python3 trader-news/news.py --source massive --offline %s --tickers %s"
          % (len(written), out_dir, out_dir, " ".join(syms))])
    return OK


# ---------------------------------------------------------------- main

def build_parser():
    ap = argparse.ArgumentParser(prog="python3 -m mjonir.bridge",
                                 description="Massive data as the Yahoo-shaped files the trader scripts read.")
    sub = ap.add_subparsers(dest="verb")

    def common(p):
        p.add_argument("--now", help='pretend it is this New York time, e.g. "2026-10-19 10:15"')
        p.add_argument("--json", action="store_true")
        p.add_argument("--out", help="where to write (a file for calendar/universe, else a folder)")

    common(sub.add_parser("probe", help="is the key accepted? three outcomes"))
    common(sub.add_parser("status", help="key, probe, calendar, cache, universe, local stores"))
    common(sub.add_parser("calendar", help="trader/calendar.json from Massive market status"))
    p = sub.add_parser("universe", help="trader/universe.txt: common stocks and ADRs over the floors")
    common(p)
    p.add_argument("--as-of", help="the session to build on (default: the last complete one)")
    p.add_argument("--sessions", type=int, default=U.DEFAULT_SESSIONS)
    p.add_argument("--min-price", type=float, help="default: universe.min_price in trader/config.json, or 5")
    p.add_argument("--min-adv-usd", type=float, help="default: universe.min_adv_usd in trader/config.json, or 20M")
    p = sub.add_parser("daily", help="one spark bundle of daily bars for scan.py daily --offline")
    common(p)
    p.add_argument("--sessions", type=int, default=65)
    p.add_argument("--end", help="the last session (default: the last complete one)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--symbols", nargs="+")
    g.add_argument("--universe", help="default trader/universe.txt")
    p = sub.add_parser("intraday", help="one session's bars per symbol (or one bundle)")
    common(p)
    p.add_argument("symbols", nargs="+")
    p.add_argument("--day", required=True)
    p.add_argument("--interval", choices=["5m", "1m"], default="5m")
    p.add_argument("--bundle", action="store_true", help="one wall<interval>-<day>.json.gz for scan.py orb")
    p.add_argument("--workers", type=int, default=Y.MAX_WORKERS)
    p = sub.add_parser("history", help="<SYM>-60d5m.json.gz for timemachine.py --offline")
    common(p)
    p.add_argument("symbol")
    p.add_argument("--from", required=True)
    p.add_argument("--to", required=True)
    p.add_argument("--source", choices=["auto", "api", "kalex", "flatfile"], default="auto")
    p = sub.add_parser("quotes", help="massive-<SYM>.json quote files for alerts.py --offline")
    common(p)
    p.add_argument("symbols", nargs="+")
    p = sub.add_parser("news", help="massive-news-<SYM>.json for news.py --offline")
    common(p)
    p.add_argument("symbols", nargs="+")
    p.add_argument("--hours", type=float, default=48)
    p.add_argument("--limit", type=int, default=50)
    return ap


VERBS = {"probe": cmd_probe, "calendar": cmd_calendar, "universe": cmd_universe, "daily": cmd_daily,
         "intraday": cmd_intraday, "history": cmd_history, "quotes": cmd_quotes, "news": cmd_news}


def main(argv=None, client_factory=None):
    ap = build_parser()
    a = ap.parse_args(argv)
    if not a.verb:
        ap.print_help()
        return REFUSED
    factory = client_factory or M.Client
    try:
        if a.verb == "status":
            return cmd_status(a, factory)
        if a.verb == "history" and a.source == "kalex":
            return cmd_history(a, None)
        return VERBS[a.verb](a, factory())
    except Y.ERRORS as e:
        print("bridge %s: %s: %s" % (a.verb, Y.outcome_of(e), e), file=sys.stderr)
        return code_of(e)
    except ValueError as e:      # a broken trader/config.json, a bad date
        print("bridge %s: refused: %s" % (a.verb, e), file=sys.stderr)
        return REFUSED
    except KeyboardInterrupt:
        print("bridge %s: stopped" % a.verb, file=sys.stderr)
        return UNVERIFIED


if __name__ == "__main__":
    sys.exit(main())
