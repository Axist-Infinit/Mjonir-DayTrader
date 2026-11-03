#!/usr/bin/env python3
"""The runner of docs/PREREG_RVOL_ORB.md (plan step 3.5), from the repo root. The document is the spec; the
section numbers below are its own.

    python3 tools/rvol_study.py --window dev --counts-only        # the one mode a DRAFT allows (section 10)
    python3 tools/rvol_study.py --window dev                      # FROZEN only: the scoring run
    python3 tools/rvol_study.py --window holdout --i-have-read-the-prereg

Refusal first (section 1). Unless --counts-only, five checks run before pandas is imported and before any flat
file, cache file or API endpoint is touched, and the first that fails is named (exit 1):
  status   the status line reads "Status: FROZEN (commit <7 to 40 hex>)"
  commit   `git cat-file -e <hash>` succeeds
  history  the hash is in `git log --format=%H -- docs/PREREG_RVOL_ORB.md`
  freeze commit  the document at that commit reads "Status: FROZEN (commit pending)", at its parent "Status: DRAFT
           (awaiting the owner's freeze)", and no earlier version of it reads FROZEN: the hash names F1, the one
           step from the draft to the freeze, and a retune re-pointed at a later "pending" commit is refused
  body     `git show <hash>:docs/PREREG_RVOL_ORB.md` equals the working file once the status line and section 13
           are removed from both
  clean    `git status --porcelain docs/PREREG_RVOL_ORB.md` is empty
The holdout (section 7) also needs --i-have-read-the-prereg, a development review whose JSON sidecar carries
pass on every criterion the frozen text of section 8.1 counts, no earlier holdout review (a second holdout run is
a refusal), and an --out of the form docs/reviews/rvol_holdout_*.md (so that refusal always sees the review).

--counts-only (section 10) scores nothing: it prints and writes only counts (the monthly reference walks and
their requests, the split rows, eligible names per session, exclusions by cause, first-bar coverage, the
early-close basis). It never prints or writes a fire count, a first-bar direction, a price, a volume or an
outcome. On its way it builds the first-bar store (trader/data/rvol/firstbars/<D>.csv: every ticker's 09:30
bucket, ticker, open, close, volume, as the vendor printed it) and the reference and split caches, which the
scoring run reuses; nothing in counts-only reads a direction from the store.

The scoring run (section 12): one pass per day file; the funnel (mjonir/rvol.py, the live scanner's own rules)
on the as-of type list, the daily cache (unadjusted) and the first-bar store; the list L(D) and its fires; every
outcome through mjonir.outcomes.score_trade, every cost through mjonir.costs.trade_cost_r, every control through
mjonir.control.draw_controls, every interval through mjonir.stats.expectancy_ci / paired_delta_ci, every state
through verdict_history / verdict_control. Arm A enters by trader-timemachine's rule_trade (upstream's ORB rule).
One JSON line per fire, draw, arm trade and baseline trade goes to trader/data/rvol/<window>/<D>.jsonl; a
session's file is replaced when it is run again, so a crash resumes at the next session. The report is
docs/reviews/rvol_<window>_<date>.md with a JSON sidecar beside it (the same inputs give the same sidecar, byte
for byte: no clock in it).

Two readings of the text, stated: SPY's bucket count over 09:30 to 16:00 leaves out a 13:00:00 print that is its
last before 16:00 (an early close's closing print, the way 16:00:00 falls outside the window; on 2026-11-03 every
rule date from 2021 to 2025 showed 42 buckets before 13:00, that one print, then nothing); and a stop that the
unrounded 0.05% floor sets is
moved down by at most a few units in the last place, so that mjonir.control's own floor check sees 0.05% and not
0.0499999 (half of floor-bound fires would otherwise lose their controls to float rounding).
"""

import argparse
import datetime as dt
import json
import math
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PREREG = "docs/PREREG_RVOL_ORB.md"
STATUS_RE = re.compile(r"^Status: FROZEN \(commit ([0-9a-f]{7,40})\)$")
WINDOWS = {"dev": ("2021-01-04", "2023-12-29"), "holdout": ("2024-01-02", "2026-08-04")}
DEFAULT_DAILY_DIR = "/home/axis/Infinit/data/polygon/flatfiles_cache"
CHECKS = ("status", "commit", "history", "freeze commit", "body", "clean")
STATUS_PENDING = "Status: FROZEN (commit pending)"
STATUS_DRAFT = "Status: DRAFT (awaiting the owner's freeze)"
HOLDOUT_OUT = re.compile(r"^rvol_holdout_[^/\\]+\.md$")

#: Section 4.1, written once (tests compare this table with the document).
PARAMS = {
    "P_MIN": 5.00, "ADV_USD_MIN": 20000000.0, "ADV_SH_MIN": 1000000.0, "ADV_N": 20, "RVOL_N": 14, "ATR_N": 14,
    "TOP_K": 20, "STOP_ATR_FRAC": 0.10, "RISK_FLOOR_PCT": 0.05, "FLAT_BY": "15:55", "FLAT_BY_EARLY": "12:55",
    "GAP_GUARD": (0.4, 2.5), "COST_TIERS": [[100000000, 4], [30000000, 8], [0, 15]], "HALF_SPREAD": 3.0,
    "COMMISSION": 1.00, "SHARES_BASIS_MAX_LOSS": 1000.0, "SLIP_X2": [[100000000, 8], [30000000, 16], [0, 30]],
    "CONTROL_K": 3, "SEED": 19, "DRAWS": 2000, "LEVEL": 0.95, "N_FLOOR": 40, "FRAGILE_R": 0.05, "TICK": 0.01,
    "ARM_TARGETS": (1.0, 2.0), "OR15_MIN": 15, "NO_ENTRIES_AFTER": "15:30", "NO_ENTRIES_AFTER_EARLY": "12:30",
    "GATE_N": 40, "GATE_DAYS": 180, "POSTHOC_GATE_DATE": "2027-02-04",
}
OPEN_MIN = 9 * 60 + 30
EARLY_CLOSE_MIN = 13 * 60
CLOSE_MIN = 16 * 60
EARLY_BARS = 42
COUNT_KEYS = ("mode", "window", "from", "to", "sessions", "reference_rows_by_month", "reference_requests",
              "requests_this_run", "splits_rows", "splits_requests", "eligible_per_session", "exclusions_by_cause",
              "first_bar_coverage", "early_close_basis", "unlabelled_short_sessions", "refused_sessions",
              "funnel_order", "name_days")
COUNT_NOTE = "counts only (PREREG section 10): sessions, names, rows and requests, nothing else"


class Refused(Exception):
    def __init__(self, check, detail):
        Exception.__init__(self, "%s: %s" % (check, detail))
        self.check = check


def hhmm(text):
    h, m = text.split(":")
    return int(h) * 60 + int(m)


# ---------------------------------------------------------------- section 1: the freeze (stdlib, no data)

def _git(repo, *args):
    p = subprocess.run(["git", "-C", repo] + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p.returncode, p.stdout.decode("utf-8", "replace")


def comparable(text):
    """The document without its status line and without section 13 (Postscripts), for the body check."""
    out, skip, status_gone = [], False, False
    for ln in text.split("\n"):
        if not status_gone and ln.startswith("Status: "):
            status_gone = True
            continue
        if ln.startswith("## 13."):
            skip = True
            continue
        if skip and ln.startswith("## "):
            skip = False
        if not skip:
            out.append(ln)
    return "\n".join(out)


def freeze_check(repo=REPO, rel=PREREG):
    """The freeze hash, or Refused naming the first failed check (section 1). Opens nothing but the document
    and git."""
    path = os.path.join(repo, rel)
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as e:
        raise Refused("status", "no %s (%s)" % (rel, e))
    line = next((ln for ln in text.split("\n") if ln.startswith("Status: ")), None)
    m = STATUS_RE.match(line or "")
    if not m:
        raise Refused("status", "the status line reads %r, not 'Status: FROZEN (commit <hash>)'; only "
                                "--counts-only runs before the owner's freeze" % (line,))
    h = m.group(1)
    code, _ = _git(repo, "cat-file", "-e", h)
    if code != 0:
        raise Refused("commit", "git cat-file -e %s fails: no such object in this repository" % h)
    code, log = _git(repo, "log", "--format=%H", "--", rel)
    full = [x for x in log.split() if x.startswith(h)]
    if code != 0 or not full:
        raise Refused("history", "%s is not a commit in `git log -- %s`" % (h, rel))
    freeze_commit_check(repo, rel, full[0])
    code, then = _git(repo, "show", "%s:%s" % (full[0], rel))
    if code != 0 or comparable(then) != comparable(text):
        raise Refused("body", "%s differs from the document at %s outside the status line and section 13"
                              % (rel, h))
    code, st = _git(repo, "status", "--porcelain", "--", rel)
    if code != 0 or st.strip():
        raise Refused("clean", "%s has uncommitted changes (%s)" % (rel, st.strip() or "git status failed"))
    return full[0]


def status_at(repo, rev, rel=PREREG):
    """The document's status line at a revision, or None when the file is not there."""
    code, text = _git(repo, "show", "%s:%s" % (rev, rel))
    if code != 0:
        return None
    return next((ln for ln in text.split("\n") if ln.startswith("Status: ")), "")


def freeze_commit_check(repo, rel, h):
    """The sixth check: commit h is F1 (section 1, step 2): the document there reads pending, at its parent DRAFT,
    and no earlier version of it reads FROZEN."""
    now = status_at(repo, h, rel)
    if now != STATUS_PENDING:
        raise Refused("freeze commit", "the document at %s reads %r, not %r: the status line must name F1"
                                       % (h[:12], now, STATUS_PENDING))
    before = status_at(repo, h + "^", rel)
    if before != STATUS_DRAFT:
        raise Refused("freeze commit", "the document at the parent of %s reads %r, not %r: F1 is the one step "
                                       "from the draft to the freeze" % (h[:12], before, STATUS_DRAFT))
    code, older = _git(repo, "rev-list", h + "^", "--", rel)
    for c in older.split():
        st = status_at(repo, c, rel) or ""
        if st.startswith("Status: FROZEN"):
            raise Refused("freeze commit", "an earlier version of the document (%s) already reads %r: this "
                                           "document was frozen before %s" % (c[:12], st, h[:12]))


def reviews_dir(repo):
    return os.path.join(repo, "docs", "reviews")


def holdout_out_check(repo, out):
    """The holdout review goes to docs/reviews/rvol_holdout_*.md, where the second-run refusal looks."""
    if out is None:
        return
    if os.path.dirname(os.path.abspath(out)) != os.path.abspath(reviews_dir(repo)) or \
            not HOLDOUT_OUT.match(os.path.basename(out)):
        raise Refused("holdout out", "--out %s: the holdout review is written to docs/reviews/rvol_holdout_<date>.md "
                                     "only, so a second holdout run always finds it (section 7)" % out)


def holdout_check(repo, flag):
    """Section 7: the flag, no earlier holdout review, a development sidecar with pass on every criterion the frozen
    text counts (read from the document, never from the sidecar)."""
    if not flag:
        raise Refused("holdout flag", "the holdout is read once, with --i-have-read-the-prereg (section 7)")
    d = reviews_dir(repo)
    names = sorted(os.listdir(d)) if os.path.isdir(d) else []
    done = [n for n in names if n.startswith("rvol_holdout_")]
    if done:
        raise Refused("second holdout", "a holdout review exists (%s): a second holdout run under this document "
                                        "is a refusal (section 7)" % ", ".join(done))
    with open(os.path.join(repo, PREREG), encoding="utf-8") as fh:
        counted = criteria_counted(fh.read())
    ok = []
    for n in names:
        if n.startswith("rvol_dev_") and n.endswith(".json") and n[:-5] + ".md" in names:
            try:
                with open(os.path.join(d, n), encoding="utf-8") as fh:
                    side = json.load(fh)
                crit = side["criteria"]
                if all(crit[k]["state"] == "pass" for k in counted):
                    ok.append(n)
            except (OSError, ValueError, KeyError, TypeError):
                continue
    if not ok:
        raise Refused("development sidecar", "no development review in docs/reviews whose JSON sidecar carries "
                                             "pass on every criterion of section 8.1 (%s, as the frozen text "
                                             "counts them)" % ", ".join(counted))
    return ok[-1]


# ---------------------------------------------------------------- the data (imported after the refusal)

def code_stamp(repo, rvol_module):
    """What a session file was scored with: the runner's own commit and a sha256 over PARAMS, this file's source
    and mjonir/rvol.py's (the funnel). A session file with another stamp is scored again on a resume."""
    import hashlib
    h = hashlib.sha256(json.dumps(PARAMS, sort_keys=True).encode("utf-8"))
    for path in (os.path.abspath(__file__), rvol_module.__file__):
        with open(path, "rb") as fh:
            h.update(fh.read())
    _, commit = _git(repo, "log", "-1", "--format=%H", "--", "tools/rvol_study.py")
    return {"runner_commit": commit.strip(), "code_sha256": h.hexdigest()}


def _mj():
    if REPO not in sys.path:
        sys.path.insert(0, REPO)
    import importlib
    return dict((n, importlib.import_module("mjonir." + n)) for n in
                ("calendar", "config", "control", "costs", "localstores", "massive", "outcomes", "rvol", "stats",
                 "universe"))


def _timemachine():
    import importlib.util
    path = os.path.join(REPO, "trader-timemachine", "timemachine.py")
    spec = importlib.util.spec_from_file_location("rvol_study_timemachine", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def atr_of(rows, n):
    """trader-exit daily_atr's arithmetic: the mean of n true ranges from the last n + 1 daily rows
    (o, h, l, c, v), TR = max(high - low, |high - prior close|, |low - prior close|)."""
    rows = rows[-(n + 1):]
    trs = [max(r[1] - r[2], abs(r[1] - rows[i][3]), abs(r[2] - rows[i][3])) for i, r in enumerate(rows[1:])]
    return sum(trs) / len(trs)


def stop_of(entry, atr, frac=PARAMS["STOP_ATR_FRAC"], floor_pct=PARAMS["RISK_FLOOR_PCT"]):
    """Section 4.5: (stop, risk, floor_bound). risk = max(frac x ATR, floor_pct of the entry), unrounded; a stop
    the floor sets is moved down by a few units in the last place at most, so that 100 x (entry - stop) / entry
    is not under floor_pct (mjonir.control's check) by float rounding alone."""
    floor = entry * floor_pct / 100.0
    by_atr = frac * atr
    risk = max(by_atr, floor)
    stop = entry - risk
    for _ in range(8):
        if not 100.0 * (entry - stop) / entry < floor_pct:
            break
        stop = math.nextafter(stop, -math.inf)
    return stop, entry - stop, by_atr < floor


class Study(object):
    """One window's pass over the flat files (see the module docstring). client: a mjonir.massive.Client for
    the two reference tables (made on first need); log: a callable for progress lines (stderr)."""

    def __init__(self, window, minute_dir=None, daily_dir=None, data_dir=None, client=None, log=None,
                 min_reference_rows=None, windows=None, repo=REPO):
        import pandas as pd
        self.pd = pd
        self.mj = _mj()
        self.K = self.mj["calendar"]
        self.R = self.mj["rvol"]
        self.repo = repo
        self.window = window
        self.windows = windows or WINDOWS
        self.lo, self.hi = [dt.date.fromisoformat(x) for x in self.windows[window]]
        self.minute_dir = str(minute_dir or self.mj["config"].flatfile_dir())
        self.daily_dir = str(daily_dir or os.environ.get("MJONIR_DAILY_DIR") or DEFAULT_DAILY_DIR)
        self.data_dir = os.path.join(str(data_dir or self.mj["config"].data_dir()), "rvol")
        self._client = client
        self.log = log or (lambda msg: None)
        self.min_rows = min_reference_rows or self.mj["universe"].MIN_REFERENCE_ROWS
        self.minute_days = self._listing(self.minute_dir)
        self.daily_days = self._listing(self.daily_dir)
        self.days = [d for d in self.minute_days if self.lo <= d <= self.hi]
        if not self.days:
            raise RuntimeError("no minute file between %s and %s in %s" % (self.lo, self.hi, self.minute_dir))
        self._daily, self._store, self._types = {}, {}, {}
        self.requests_this_run = 0
        self.floors = {"min_price": PARAMS["P_MIN"], "min_adv_usd": PARAMS["ADV_USD_MIN"],
                       "min_avg_volume": PARAMS["ADV_SH_MIN"]}
        self.early_rule = set()
        for y in range(self.lo.year - 1, self.hi.year + 1):
            self.early_rule |= set(self.K.rule_early_closes(y))
        self.stamp = code_stamp(repo, self.R)

    # -- listings and the client
    @staticmethod
    def _listing(folder):
        out = []
        for f in sorted(os.listdir(folder)):
            if f.endswith(".csv.gz") and len(f) == 17:
                try:
                    out.append(dt.date.fromisoformat(f[:10]))
                except ValueError:
                    continue
        return out

    def client(self):
        if self._client is None:
            self._client = self.mj["massive"].Client()
        return self._client

    def before(self, days, day, n):
        """The n dates of `days` strictly before `day`, oldest first (fewer when the listing starts later)."""
        import bisect
        i = bisect.bisect_left(days, day)
        return days[max(0, i - n):i]

    # -- the reference tables (section 3.2, 3.4)
    def _json(self, path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def _write_json(self, path, doc):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)

    def month_session(self, month):
        """The first flat-file session of a month (the as-of date of its walk)."""
        return next(d for d in self.minute_days if d.strftime("%Y-%m") == month)

    def reference(self, month, ty):
        """The as-of walk for one month and type, cached once: {date, type, rows, pages, tickers}."""
        path = os.path.join(self.data_dir, "reference", "%s-%s.json" % (month, ty))
        if os.path.exists(path):
            return self._json(path)
        M = self.mj["massive"]
        d = self.month_session(month)
        c = self.client()
        before = c.requests
        pages = c.reference_pages({"type": ty, "date": d.isoformat()})
        rows, meta = M.check_reference(pages, want_type=ty, min_rows=self.min_rows.get(ty, 1))
        doc = {"date": d.isoformat(), "type": ty, "rows": len(rows), "pages": meta["pages"],
               "requests": c.requests - before, "tickers": sorted(rows)}
        self.requests_this_run += c.requests - before
        self._write_json(path, doc)
        self.log("reference %s %s as of %s: %d rows, %d pages" % (month, ty, d, len(rows), meta["pages"]))
        return doc

    def types(self, day):
        month = day.strftime("%Y-%m")
        if month not in self._types:
            TICKER = self.mj["universe"].TICKER
            names = set()
            for ty in self.mj["universe"].DEFAULT_TYPES:
                names |= set(self.reference(month, ty)["tickers"])
            self._types[month] = sorted(t for t in names if TICKER.match(t))
        return self._types[month]

    def splits_bounds(self):
        first = dt.date.fromisoformat(self.windows["dev"][0])
        pre = self.before(self.daily_days, first, PARAMS["ADV_N"])
        return (pre[0] if pre else first).isoformat(), self.windows["holdout"][1]

    def splits(self):
        """The one splits walk for both windows, cached once: {gte, lte, rows, pages, splits}."""
        path = os.path.join(self.data_dir, "splits.json")
        if os.path.exists(path):
            doc = self._json(path)
        else:
            M = self.mj["massive"]
            gte, lte = self.splits_bounds()
            c = self.client()
            before = c.requests
            out, ids, pages = [], set(), 0
            for p in c.pages("/v3/reference/splits", {"execution_date.gte": gte, "execution_date.lte": lte,
                                                       "limit": 1000, "sort": "execution_date", "order": "asc"}):
                pages += 1
                if p.get("status") not in M.OK_STATUSES:
                    raise M.Refused("splits page %d: status %r" % (pages, p.get("status")))
                rows = p.get("results") or []
                if p.get("count") is not None and int(p["count"]) != len(rows):
                    raise M.Refused("splits page %d: count %s but %d rows" % (pages, p["count"], len(rows)))
                for r in rows:
                    x = str(r.get("execution_date") or "")[:10]
                    if not (gte <= x <= lte):
                        raise M.Refused("splits page %d: %s outside %s..%s; the vendor ignored the filter"
                                        % (pages, x, gte, lte))
                    rid = r.get("id") or "%s|%s|%s|%s" % (r.get("ticker"), x, r.get("split_from"), r.get("split_to"))
                    if rid in ids:
                        raise M.Refused("splits page %d: %s listed twice; the cursor overlapped" % (pages, rid))
                    ids.add(rid)
                    out.append({"ticker": str(r.get("ticker") or "").upper(), "execution_date": x,
                                "split_from": r.get("split_from"), "split_to": r.get("split_to"), "id": rid})
            doc = {"gte": gte, "lte": lte, "rows": len(out), "pages": pages, "requests": c.requests - before,
                   "splits": out}
            self.requests_this_run += c.requests - before
            self._write_json(path, doc)
            self.log("splits %s..%s: %d rows, %d pages" % (gte, lte, len(out), pages))
        if not hasattr(self, "split_map"):
            self.split_map = self.R.split_days(doc["splits"])
        return doc

    # -- the daily cache (unadjusted, section 3.1)
    def daily_frame(self, day):
        if day not in self._daily:
            pd = self.pd
            p = os.path.join(self.daily_dir, "%s.csv.gz" % day.isoformat())
            df = pd.read_csv(p, compression="gzip", keep_default_na=False, na_values=[""],
                             dtype={"ticker": str, "volume": "float64", "open": "float64", "close": "float64",
                                    "high": "float64", "low": "float64", "window_start": "int64",
                                    "transactions": "float64"})
            self._daily[day] = dict(zip(df["ticker"].tolist(), zip(df["open"].tolist(), df["high"].tolist(),
                                                                   df["low"].tolist(), df["close"].tolist(),
                                                                   df["volume"].tolist())))
            while len(self._daily) > PARAMS["ADV_N"] + 5:      # the days are walked in order: drop the oldest
                del self._daily[min(self._daily)]
        return self._daily[day]

    # -- the minute files and the first-bar store (sections 4.2, 4.3, 12)
    def read_minutes(self, day):
        """One day file, with the New York minute of the day ("mod"); rows of another date are dropped."""
        pd = self.pd
        p = os.path.join(self.minute_dir, "%s.csv.gz" % day.isoformat())
        df = pd.read_csv(p, compression="gzip", keep_default_na=False, na_values=[""],
                         dtype={"ticker": str, "volume": "float64", "open": "float64", "close": "float64",
                                "high": "float64", "low": "float64", "window_start": "int64",
                                "transactions": "float64"})
        off = self.K.tz_label(day)[1]
        local = df["window_start"] // 1000000000 + off
        df = df[(local // 86400) == (day - dt.date(1970, 1, 1)).days].copy()
        df["mod"] = ((local[df.index] % 86400) // 60).astype("int64")
        return df

    def fold(self, df, names=None):
        """{ticker: [5-minute buckets]} through mjonir.localstores.fold_minutes_to_5m (each bucket gets its index
        "i" from 09:30), tickers sorted."""
        fold5 = self.mj["localstores"].fold_minutes_to_5m
        if names is not None:
            df = df[df["ticker"].isin(sorted(names))]
        df = df.sort_values(["ticker", "window_start"], kind="mergesort")
        tick = df["ticker"].tolist()
        cols = [df[c].tolist() for c in ("window_start", "open", "high", "low", "close", "volume", "transactions",
                                         "mod")]
        out, start = {}, 0
        n = len(tick)
        for j in range(1, n + 1):
            if j == n or tick[j] != tick[start]:
                rows = [{"t": cols[0][i] // 1000000, "o": cols[1][i], "h": cols[2][i], "l": cols[3][i],
                         "c": cols[4][i], "v": cols[5][i], "n": int(cols[6][i] or 0) if cols[6][i] == cols[6][i] else 0}
                        for i in range(start, j)]
                bars = fold5(rows)
                first_mod = dict((cols[0][i] // 1000000 - (cols[0][i] // 1000000) % 300000, cols[7][i])
                                 for i in range(start, j))
                for b in bars:
                    m = first_mod[b["t"]]
                    b["i"] = (m - m % 5 - OPEN_MIN) // 5
                out[tick[start]] = bars
                start = j
        return out

    def store_path(self, day):
        return os.path.join(self.data_dir, "firstbars", "%s.csv" % day.isoformat())

    def build_store(self, day, df=None):
        """Every ticker's 09:30 bucket of `day` (ticker, open, close, volume) and SPY's regular-hours bucket count,
        written to the first-bar store. Returns (firsts {ticker: (o, c, v)}, meta, df)."""
        if df is None:
            df = self.read_minutes(day)
        fb = self.fold(df[(df["mod"] >= OPEN_MIN) & (df["mod"] < OPEN_MIN + 5)])
        firsts = {}
        for t in sorted(fb):
            b = [x for x in fb[t] if x["i"] == 0]
            if b:
                firsts[t] = (b[0]["o"], b[0]["c"], b[0]["v"])
        spy = sorted(set(df.loc[(df["ticker"] == "SPY") & (df["mod"] >= OPEN_MIN) & (df["mod"] < CLOSE_MIN),
                                "mod"].tolist()))
        if spy and spy[-1] == EARLY_CLOSE_MIN:          # an early close's closing print, the day's last before 16:00
            spy = spy[:-1]
        meta = {"date": day.isoformat(), "spy_buckets": len(set((m - OPEN_MIN) // 5 for m in spy)),
                "tickers": len(firsts), "minute_rows": int(len(df))}
        path = self.store_path(day)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write("ticker,open,close,volume\n")
            for t in sorted(firsts):
                o, c, v = firsts[t]
                fh.write("%s,%r,%r,%r\n" % (t, o, c, v))
        os.replace(tmp, path)
        self._write_json(path[:-4] + ".meta.json", meta)
        self._store[day] = (firsts, meta)
        return firsts, meta, df

    def store(self, day):
        """(firsts, meta) of one session from the store, built from its day file when absent."""
        if day in self._store:
            return self._store[day]
        path = self.store_path(day)
        if os.path.exists(path) and os.path.exists(path[:-4] + ".meta.json"):
            firsts = {}
            with open(path, encoding="utf-8") as fh:
                next(fh)
                for ln in fh:
                    t, o, c, v = ln.rstrip("\n").split(",")
                    firsts[t] = (float(o), float(c), float(v))
            self._store[day] = (firsts, self._json(path[:-4] + ".meta.json"))
        else:
            self.build_store(day)
        if len(self._store) > PARAMS["RVOL_N"] + 3:
            for d in sorted(self._store)[:len(self._store) - PARAMS["RVOL_N"] - 3]:
                del self._store[d]
        return self._store[day]

    # -- one session
    def session_status(self, day, meta):
        """(status, early, basis): warmup, refused (a contradicted early close, or no SPY on a rule date) or ok."""
        early = day.isoformat() in self.early_rule
        hist = self.before(self.minute_days, day, PARAMS["RVOL_N"])
        n = meta["spy_buckets"]
        basis = None
        if early:
            basis = "no_spy" if n == 0 else ("verified" if n <= EARLY_BARS else "contradicted")
        if len(hist) < PARAMS["RVOL_N"]:
            return "warmup", early, basis
        if early and basis != "verified":
            return "refused", early, basis
        return "ok", early, basis

    def funnel(self, day, firsts, rows=True):
        """Sections 3.2 to 3.4 and 4.3 through mjonir.rvol: (eligible rows, counts by cause, population). rows=False
        (counts-only) gets the eligible symbols only: no RVOL and no direction is computed for any name."""
        R = self.R
        pop = self.types(day)
        adv_days = self.before(self.daily_days, day, PARAMS["ADV_N"])
        frames = [self.daily_frame(d) for d in adv_days]
        lo, hi = (adv_days[0].isoformat() if adv_days else day.isoformat()), day.isoformat()
        sp = self.split_map

        def daily(sym):
            return [f[sym] for f in frames if sym in f]

        def split_hit(sym):
            return any(lo <= x <= hi for x in sp.get(sym, ()))
        passed, c1 = R.floors_stage(pop, daily, split_hit, self.floors, PARAMS["ADV_N"])
        hist = [self.store(d)[0] for d in self.before(self.minute_days, day, PARAMS["RVOL_N"])]

        def history(sym):
            return [(h.get(sym) or (None, None, None))[2] for h in hist]
        fb = dict((t, {"o": o, "h": None, "l": None, "c": c, "v": v}) for t, (o, c, v) in firsts.items())
        elig, c2 = R.bar_stage(passed, fb, history, PARAMS["RVOL_N"], PARAMS["GAP_GUARD"], rows=rows)
        counts = dict(c1)
        counts.update(c2)
        counts["eligible"] = len(elig)
        if rows:
            for e in elig:
                e["daily"] = passed[e["symbol"]]["rows"]
        return elig, counts, len(pop)

    # -- counts-only (section 10)
    def counts(self):
        """The section 10 counts for this window (and nothing else)."""
        import statistics
        self.splits()
        months = sorted(set(d.strftime("%Y-%m") for d in self.days))
        ref = {}
        for m in months:
            ref[m] = {}
            for ty in self.mj["universe"].DEFAULT_TYPES:
                doc = self.reference(m, ty)
                ref[m][ty] = doc["rows"]
                ref[m]["date"] = doc["date"]
                ref[m]["pages_" + ty] = doc["pages"]
        causes = dict((c, 0) for c in self.R.CAUSES)
        per_session, early, refused, short, warmup, name_days = [], {}, [], 0, 0, 0
        for k, day in enumerate(self.days):
            if day not in self._store and not os.path.exists(self.store_path(day)):
                firsts, meta, _ = self.build_store(day)
            else:
                firsts, meta = self.store(day)
            status, is_early, basis = self.session_status(day, meta)
            if is_early:
                early[day.isoformat()] = basis
            elif meta["spy_buckets"] <= EARLY_BARS:
                short += 1
            if status == "warmup":
                warmup += 1
                continue
            if status == "refused":
                refused.append(day.isoformat())
                continue
            elig, counts, pop = self.funnel(day, firsts, rows=False)
            name_days += pop
            for c in self.R.CAUSES:
                causes[c] += counts[c]
            per_session.append(counts["eligible"])
            if (k + 1) % 25 == 0 or k + 1 == len(self.days):
                self.log("counts %s: %d of %d sessions" % (day, k + 1, len(self.days)))
        sp = self.splits()
        causes["warmup_sessions"] = warmup
        elig_total = sum(per_session)
        q = statistics.quantiles(per_session, n=4, method="inclusive") if len(per_session) > 1 else \
            [float(x) for x in per_session * 3]
        doc = {
            "mode": "counts-only", "window": self.window, "from": self.days[0].isoformat(),
            "to": self.days[-1].isoformat(), "sessions": len(self.days),
            "reference_rows_by_month": ref,
            "reference_requests": sum(ref[m]["pages_" + ty] for m in ref for ty in self.mj["universe"].DEFAULT_TYPES),
            "requests_this_run": self.requests_this_run, "splits_rows": sp["rows"], "splits_requests": sp["pages"],
            "eligible_per_session": {"sessions": len(per_session),
                                     "median": statistics.median(per_session) if per_session else None,
                                     "q1": q[0] if per_session else None, "q3": q[2] if per_session else None,
                                     "min": min(per_session) if per_session else None,
                                     "max": max(per_session) if per_session else None},
            "exclusions_by_cause": causes,
            "first_bar_coverage": (elig_total / float(elig_total + causes["rvol_history_short"])
                                   if elig_total + causes["rvol_history_short"] else None),
            "early_close_basis": early, "unlabelled_short_sessions": short, "refused_sessions": refused,
            "funnel_order": list(self.R.CAUSES), "name_days": name_days,
        }
        return doc

    # -- the scoring run (sections 4 to 6), never on a DRAFT
    def cost_model(self, adv_usd, tiers):
        costs = self.mj["costs"]
        tier, _ = costs.tier_bps(adv_usd, tiers)
        return {"per_side_bps": tier + PARAMS["HALF_SPREAD"], "commission_usd": PARAMS["COMMISSION"], "shares": None,
                "max_loss_usd": PARAMS["SHARES_BASIS_MAX_LOSS"]}, tier

    def day_path(self, day):
        return os.path.join(self.data_dir, self.window, "%s.jsonl" % day.isoformat())

    def score_session(self, day, tm):
        """Score one session and write its JSON lines (replacing an earlier file). Returns the lines."""
        O, C, costs = self.mj["outcomes"], self.mj["control"], self.mj["costs"]
        firsts, meta, df = self.build_store(day)
        status, early, basis = self.session_status(day, meta)
        lines = []
        head = {"kind": "session", "date": day.isoformat(), "status": status, "early": early, "basis": basis,
                "stamp": self.stamp}
        if status != "ok":
            lines.append(head)
            return self._write_day(day, lines)
        elig, counts, pop = self.funnel(day, firsts)
        listed = self.R.rank(elig, PARAMS["TOP_K"])
        flat_idx = (hhmm(PARAMS["FLAT_BY_EARLY"] if early else PARAMS["FLAT_BY"]) - 5 - OPEN_MIN) // 5
        nea_idx = (hhmm(PARAMS["NO_ENTRIES_AFTER_EARLY"] if early else PARAMS["NO_ENTRIES_AFTER"]) - OPEN_MIN) // 5 - 1
        end_min = hhmm(PARAMS["FLAT_BY_EARLY"] if early else PARAMS["FLAT_BY"])
        names = sorted(e["symbol"] for e in elig)
        rth = df[(df["mod"] >= OPEN_MIN) & (df["mod"] < end_min)]
        bars_of = self.fold(rth, names)
        date = day.isoformat()
        seed, K_ = PARAMS["SEED"], PARAMS["CONTROL_K"]
        by_sym = dict((e["symbol"], e) for e in elig)
        head.update(eligible=len(elig), population=pop, funnel=counts, list=[r["symbol"] for r in listed],
                    fires=sum(1 for r in listed if r["fire"]), flat_idx=flat_idx)
        lines.append(head)

        def prep(sym):
            e = by_sym[sym]
            bars = [b for b in bars_of.get(sym, []) if b["i"] <= flat_idx]
            if not bars or bars[0]["i"] != 0:
                return None
            atr = atr_of(e["daily"], PARAMS["ATR_N"])
            model, tier = self.cost_model(e["adv_usd"], PARAMS["COST_TIERS"])
            return e, bars, atr, model, tier
        for e in elig:                                   # B1 and B2 (section 6.2)
            p = prep(e["symbol"])
            if p is None:
                lines.append({"kind": "b", "date": date, "symbol": e["symbol"], "skip": "no_bars"})
                continue
            e, bars, atr, model, tier = p
            entry = bars[C.baseline_entry_bar(1)]["c"]
            stop, risk, _ = stop_of(entry, atr)
            last = len(bars) - 1
            res = O.score_trade(bars, 0, entry, stop, None, last, costs.trade_cost_r(entry, risk, model),
                                fill="close", gap_fill="open", long=True)
            lines.append({"kind": "b", "date": date, "symbol": e["symbol"], "up": e["direction"] == "up",
                          "outcome": res["outcome"], "gross_r": res["gross_r"], "net_r": res["net_r"]})
        for r in listed:
            sym = r["symbol"]
            p = prep(sym)
            if p is None:
                lines.append({"kind": "list_skip", "date": date, "symbol": sym, "why": "no_bars"})
                continue
            e, bars, atr, model, tier = p
            last = len(bars) - 1
            idx = [b["i"] for b in bars]

            def cost_fn(en, rk, model=model):
                return costs.trade_cost_r(en, rk, model)
            # arm A at each target, on every name of L(D) (section 5)
            if idx[:3] == [0, 1, 2]:
                fire_last = max(j for j in range(last + 1) if idx[j] <= nea_idx)
                for tr in PARAMS["ARM_TARGETS"]:
                    rt = tm.rule_trade(bars, {"stop_rule": "or_mid", "target_r": tr}, 3, fire_last, True)
                    row = {"kind": "armA", "date": date, "symbol": sym, "target_r": tr}
                    if rt is None:
                        lines.append(dict(row, fired=False))
                        continue
                    kk, en, st, tg = rt
                    if 100.0 * (en - st) / en < PARAMS["RISK_FLOOR_PCT"]:
                        lines.append(dict(row, fired=False, skip="risk_floor"))
                        continue
                    res = O.score_trade(bars, kk, en, st, tg, last, cost_fn(en, en - st), fill="close",
                                        gap_fill="open", long=True)
                    lines.append(dict(row, fired=True, **self._res(res, en, st)))
                    got, why = C.draw_controls(bars, sym, date, seed=seed, draws=K_, n_or=3, last=last, rule_entry=en,
                                               rule_stop=st, target_r=tr, cost_fn=cost_fn, gap_fill="open", long=True,
                                               entry_until=fire_last)
                    self._draws(lines, "A%g" % tr, date, sym, got, why)
            else:
                lines.append({"kind": "armA", "date": date, "symbol": sym, "fired": False, "skip": "or_incomplete"})
            if not r["fire"]:
                continue
            entry = bars[0]["c"]
            stop, risk, bound = stop_of(entry, atr)
            cr = cost_fn(entry, risk)
            res = O.score_trade(bars, 0, entry, stop, None, last, cr, fill="close", gap_fill="open", long=True)
            model2, tier2 = self.cost_model(e["adv_usd"], PARAMS["SLIP_X2"])
            res2 = O.score_trade(bars, 0, entry, stop, None, last, costs.trade_cost_r(entry, risk, model2),
                                 fill="close", gap_fill="open", long=True)
            ticks = {}
            for name, shift in (("up", PARAMS["TICK"]), ("down", -PARAMS["TICK"])):
                en = entry + shift
                st, rk, _ = stop_of(en, atr)
                ticks[name] = O.score_trade(bars, 0, en, st, None, last, cost_fn(en, rk), fill="close",
                                            gap_fill="open", long=True)["outcome"]
            fire = dict({"kind": "fire", "date": date, "symbol": sym, "rank": r["rank"], "rvol": r["rvol"],
                         "atr": atr, "adv_usd": e["adv_usd"], "tier_bps": tier, "risk_floor_bound": bound,
                         "missing_buckets": idx[last] - idx[0] != last, "exit_before_flat_by": idx[last] < flat_idx,
                         "last": last, "early": early, "net_r_slip_x2": res2["net_r"], "cost_r_slip_x2": res2["cost_r"],
                         "tick_up": ticks["up"], "tick_down": ticks["down"]}, **self._res(res, entry, stop))
            lines.append(fire)
            got, why = C.draw_controls(bars, sym, date, seed=seed, draws=K_, n_or=1, last=last, rule_entry=entry,
                                       rule_stop=stop, target_r=None, cost_fn=cost_fn, gap_fill="open", long=True,
                                       entry_until=None)
            self._draws(lines, "primary", date, sym, got, why)
            tb = max(PARAMS["ARM_TARGETS"])
            resb = O.score_trade(bars, 0, entry, stop, entry + tb * risk, last, cr, fill="close", gap_fill="open",
                                 long=True)
            lines.append(dict({"kind": "armB", "date": date, "symbol": sym, "target_r": tb},
                              **self._res(resb, entry, stop)))
            got, why = C.draw_controls(bars, sym, date, seed=seed, draws=K_, n_or=1, last=last, rule_entry=entry,
                                       rule_stop=stop, target_r=tb, cost_fn=cost_fn, gap_fill="open", long=True,
                                       entry_until=None)
            self._draws(lines, "B", date, sym, got, why)
        return self._write_day(day, lines)

    @staticmethod
    def _res(res, entry, stop):
        return {"entry": entry, "stop": stop, "outcome": res["outcome"], "exit_bar": res["exit_bar"],
                "gross_r": res["gross_r"], "net_r": res["net_r"], "cost_r": res["cost_r"], "mfe_r": res["mfe_r"],
                "mae_r": res["mae_r"], "fragile": res["fragile"], "decision_margin_r": res["decision_margin_r"],
                "gap": res["gap"]}

    @staticmethod
    def _draws(lines, arm, date, sym, got, why):
        for i, c in enumerate(got):
            lines.append({"kind": "draw", "arm": arm, "date": date, "symbol": sym, "draw": i, "bar": c["bar"],
                          "outcome": c["outcome"], "gross_r": c["gross_r"], "net_r": c["net_r"], "cost_r": c["cost_r"]})
        if why:
            lines.append({"kind": "draw_skip", "arm": arm, "date": date, "symbol": sym, "why": why})

    def _write_day(self, day, lines):
        path = self.day_path(day)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            for ln in lines:
                fh.write(json.dumps(ln, sort_keys=True) + "\n")
            fh.write(json.dumps({"kind": "end", "date": day.isoformat(), "stamp": self.stamp}, sort_keys=True) + "\n")
        os.replace(tmp, path)
        return lines

    def read_day(self, day):
        """A session's lines from an earlier run, or None (score it again): no file, a cut file, or a head or end
        row stamped with another runner commit or code hash."""
        path = self.day_path(day)
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as fh:
            rows = [json.loads(x) for x in fh]
        if len(rows) < 2 or rows[-1].get("kind") != "end" or rows[0].get("kind") != "session":
            return None
        if rows[-1].get("stamp") != self.stamp or rows[0].get("stamp") != self.stamp:
            return None
        return rows[:-1]

    def score(self, resume=True):
        """Every session of the window (a complete day file is kept when resume), then the aggregate."""
        self.splits()
        tm = _timemachine()
        out = []
        for k, day in enumerate(self.days):
            got = self.read_day(day) if resume else None
            if got is None:
                got = self.score_session(day, tm)
            out.extend(got)
            if (k + 1) % 25 == 0 or k + 1 == len(self.days):
                self.log("scored %s: %d of %d sessions" % (day, k + 1, len(self.days)))
        return out


# ---------------------------------------------------------------- the aggregate and the report (section 12)

def _ci(stats, xs):
    return stats.expectancy_ci(xs, seed=PARAMS["SEED"], draws=PARAMS["DRAWS"]) if xs else None


def _hist(stats, trades, target_r):
    nets = [t["net_r"] for t in trades]
    return {"triggered": len(trades), "target": sum(1 for t in trades if t["outcome"] == "target"),
            "stop": sum(1 for t in trades if t["outcome"] == "stop"), "expectancy": _ci(stats, nets)}


def _cost_mean(trades):
    return sum(t["cost_r"] for t in trades) / len(trades) if trades else 0.0


def by_year(stats, trades):
    years = {}
    for t in trades:
        years.setdefault(t["date"][:4], []).append(t)
    out = {}
    for y in sorted(years):
        rows = years[y]
        n = len(rows)
        out[y] = {"n": n, "net": _ci(stats, [t["net_r"] for t in rows]),
                  "stop_share": sum(1 for t in rows if t["outcome"] == "stop") / float(n),
                  "close_share": sum(1 for t in rows if t["outcome"] == "close") / float(n),
                  "target_share": sum(1 for t in rows if t["outcome"] == "target") / float(n),
                  "fragile": sum(1 for t in rows if t.get("fragile"))}
    note = stats.sign_flip_note(dict((y, (v["n"], v["net"]["mean"] if v["net"] else None)) for y, v in out.items()))
    return out, note


def _delta(stats, rule_trades, draws):
    rule_by, ctrl_by = {}, {}
    for t in rule_trades:
        rule_by.setdefault(t["date"], []).append(t["net_r"])
    for c in draws:
        ctrl_by.setdefault(c["date"], []).append(c["net_r"])
    if not any(d in ctrl_by for d in rule_by):
        return None
    return stats.paired_delta_ci(rule_by, ctrl_by, seed=PARAMS["SEED"], draws=PARAMS["DRAWS"])


def criteria_counted(text):
    """The criteria of section 8.1 the frozen text holds (criterion 4 may be struck before the freeze)."""
    sec = text.split("### 8.1", 1)[1].split("### 8.2", 1)[0] if "### 8.1" in text else ""
    out = []
    for n in ("1", "2", "3", "4"):
        if re.search(r"(?m)^%s\. " % n, sec):
            out.append(n)
    if "4" in out and not re.search(r"(?m)^4\. The session-level interval", sec):
        out.remove("4")
    return out or ["1", "2", "3", "4"]


def aggregate(stats, rows, counted=("1", "2", "3", "4")):
    """Every number the report prints (P12): the funnel, the fires, the verdicts, the four criteria."""
    sessions = [r for r in rows if r["kind"] == "session"]
    fires = [r for r in rows if r["kind"] == "fire"]
    draws = [r for r in rows if r["kind"] == "draw"]
    skips = [r for r in rows if r["kind"] == "draw_skip"]
    ok = [s for s in sessions if s["status"] == "ok"]
    funnel = {}
    for s in ok:
        for k, v in s["funnel"].items():
            funnel[k] = funnel.get(k, 0) + v
    eligible = sorted(s["eligible"] for s in ok)
    dist = {}
    for s in ok:
        dist[s["fires"]] = dist.get(s["fires"], 0) + 1
    cost_mean = _cost_mean(fires)
    primary = stats.verdict_history(_hist(stats, fires, None), None, cost_mean)
    p_draws = [d for d in draws if d["arm"] == "primary"]
    delta = _delta(stats, fires, p_draws)
    control = stats.verdict_control(delta)
    sess_means = {}
    for f in fires:
        sess_means.setdefault(f["date"], []).append(f["net_r"])
    sess_vals = [sum(v) / len(v) for _, v in sorted(sess_means.items())]
    sess_ci = _ci(stats, sess_vals)
    sess_state = stats.verdict_history({"triggered": len(sess_vals), "expectancy": sess_ci}, None, cost_mean)
    years, year_note = by_year(stats, fires)
    c3 = stats.verdict_years(dict((y, (v["n"], v["net"]["mean"])) for y, v in years.items()), stats.N_FLOOR)
    criteria = {"1": {"state": primary["state"], "reason": primary["reason"], "text": primary["text"]},
                "2": {"state": control["state"], "reason": control["reason"], "text": control["text"]},
                "3": c3,
                "4": {"state": sess_state["state"], "reason": sess_state["reason"], "text": sess_state["text"]}}
    result = "pass" if all(criteria[k]["state"] == "pass" for k in counted) else "closed"
    slip = _ci(stats, [f["net_r_slip_x2"] for f in fires])
    flips = {"up": sum(1 for f in fires if f["tick_up"] != f["outcome"]),
             "down": sum(1 for f in fires if f["tick_down"] != f["outcome"])}
    arms = {}
    for tr in PARAMS["ARM_TARGETS"]:
        name = "A%g" % tr
        tr_rows = [r for r in rows if r["kind"] == "armA" and r.get("fired") and r["target_r"] == tr]
        d = _delta(stats, tr_rows, [x for x in draws if x["arm"] == name])
        arms[name] = {"n": len(tr_rows), "history": stats.verdict_history(_hist(stats, tr_rows, tr), tr,
                                                                           _cost_mean(tr_rows)),
                      "control": stats.verdict_control(d), "delta": d, "by_year": by_year(stats, tr_rows)[0],
                      "risk_floor_skips": sum(1 for r in rows if r["kind"] == "armA" and r.get("skip") == "risk_floor"
                                              and r.get("target_r") == tr),
                      "or_incomplete": sum(1 for r in rows if r["kind"] == "armA" and r.get("skip") == "or_incomplete")}
    b_rows = [r for r in rows if r["kind"] == "armB"]
    tb = max(PARAMS["ARM_TARGETS"])
    db = _delta(stats, b_rows, [x for x in draws if x["arm"] == "B"])
    arms["B"] = {"n": len(b_rows), "history": stats.verdict_history(_hist(stats, b_rows, tb), tb, _cost_mean(b_rows)),
                 "control": stats.verdict_control(db), "delta": db, "by_year": by_year(stats, b_rows)[0]}
    base = [r for r in rows if r["kind"] == "b" and "outcome" in r]
    baselines = {}
    for name, sel in (("B1", base), ("B2", [r for r in base if r["up"]])):
        baselines[name] = {"n": len(sel), "net": _ci(stats, [r["net_r"] for r in sel]),
                           "by_year": by_year(stats, sel)[0]}
    skipped = {}
    for s in skips:
        if s["arm"] == "primary":
            for k, v in s["why"].items():
                skipped[k] = skipped.get(k, 0) + v
    return {
        "sessions": {"total": len(sessions), "ok": len(ok),
                     "warmup": sum(1 for s in sessions if s["status"] == "warmup"),
                     "refused": sorted(s["date"] for s in sessions if s["status"] == "refused"),
                     "early_close_basis": dict((s["date"], s["basis"]) for s in sessions if s.get("early"))},
        "funnel": funnel,
        "eligible_per_session": {"median": _median(eligible), "q1": _q(eligible, 0.25), "q3": _q(eligible, 0.75)},
        "fires": {"n": len(fires), "per_session": dict((str(k), v) for k, v in sorted(dist.items())),
                  "fragile": sum(1 for f in fires if f["fragile"]),
                  "missing_buckets": sum(1 for f in fires if f["missing_buckets"]),
                  "exit_before_flat_by": sum(1 for f in fires if f["exit_before_flat_by"]),
                  "risk_floor_bound": sum(1 for f in fires if f["risk_floor_bound"]),
                  "outcomes": dict((o, sum(1 for f in fires if f["outcome"] == o)) for o in ("stop", "close")),
                  "cost_r_mean": cost_mean, "gross": _ci(stats, [f["gross_r"] for f in fires])},
        "primary": primary, "control": control, "delta": delta, "control_skipped": skipped,
        "session_level": {"n_sessions": len(sess_vals), "interval": sess_ci, "state": sess_state["state"],
                          "reason": sess_state["reason"], "text": sess_state["text"]},
        "by_year": years, "by_year_note": year_note, "slippage_x2": slip,
        "one_tick": {"tick": PARAMS["TICK"], "of": len(fires), "up": flips["up"], "down": flips["down"],
                     "flips": flips["up"] + flips["down"]},
        "arms": arms, "baselines": baselines,
        "data": {"source": "flatfile", "adjusted": False},
        "criteria": criteria, "criteria_counted": list(counted), "result": result,
    }


def _median(xs):
    if not xs:
        return None
    import statistics
    return statistics.median(xs)


def _q(xs, p):
    if len(xs) < 2:
        return xs[0] if xs else None
    import statistics
    q = statistics.quantiles(xs, n=4, method="inclusive")
    return q[0] if p == 0.25 else q[2]


def _iv(ci):
    return "n/a" if not ci else "%+.3f [%+.3f, %+.3f] (n %d)" % (ci["mean"], ci["lo"], ci["hi"], ci["n"])


def report_text(agg, window, freeze_hash, runner_commit, argv):
    """The review document (section 12's order); Python computed every number, this only places them."""
    a = agg
    L = ["# RVOL ORB study: the %s window" % window, "",
         "Freeze hash: `%s`. Runner commit: `%s`." % (freeze_hash, runner_commit), "",
         "Command: `%s`" % " ".join(argv), "", "## Availability funnel (section 10, as measured)", "",
         "Sessions %d: %d scored, %d warm-up, %d refused (%s). Early-close basis: %s." % (
             a["sessions"]["total"], a["sessions"]["ok"], a["sessions"]["warmup"], len(a["sessions"]["refused"]),
             ", ".join(a["sessions"]["refused"]) or "none",
             ", ".join("%s %s" % kv for kv in sorted(a["sessions"]["early_close_basis"].items())) or "none"),
         "Eligible names per session: median %s, quartiles %s and %s." % (
             a["eligible_per_session"]["median"], a["eligible_per_session"]["q1"], a["eligible_per_session"]["q3"]),
         "Exclusions by cause: %s." % ", ".join("%s %d" % (k, a["funnel"].get(k, 0)) for k in sorted(a["funnel"])),
         "", "## Fires", "",
         "%d fires; per session %s; fragile %d; missing_buckets %d; exit_before_flat_by %d; risk_floor_bound %d; "
         "outcomes %s; mean round trip %.3f R; gross %s." % (
             a["fires"]["n"], ", ".join("%s: %d" % kv for kv in a["fires"]["per_session"].items()),
             a["fires"]["fragile"], a["fires"]["missing_buckets"], a["fires"]["exit_before_flat_by"],
             a["fires"]["risk_floor_bound"], ", ".join("%s %d" % kv for kv in sorted(a["fires"]["outcomes"].items())),
             a["fires"]["cost_r_mean"], _iv(a["fires"]["gross"])),
         "", "## The primary rule (criterion 1)", "", a["primary"]["text"], "",
         "## The matched random-entry control (criterion 2)", "", a["control"]["text"],
         "Control draws skipped: %s." % (", ".join("%s %d" % kv for kv in sorted(a["control_skipped"].items()))
                                         or "none"), "",
         "## The session-level interval (criterion 4)", "",
         "One value a session with at least one fire (%d sessions); the template's fires are sessions here: %s"
         % (a["session_level"]["n_sessions"], a["session_level"]["text"]), "",
         "## By year (arm D, criterion 3)", "", "| year | n | net mean [95%] | stop | close | fragile |",
         "| --- | --- | --- | --- | --- | --- |"]
    for y, v in sorted(a["by_year"].items()):
        L.append("| %s | %d | %s | %.3f | %.3f | %d |" % (y, v["n"], _iv(v["net"]), v["stop_share"],
                                                         v["close_share"], v["fragile"]))
    L += ["", a["by_year_note"] or "No sign flip between years.", "",
          "## Slippage sensitivity (arm C, never the headline)", "",
          "Tiers doubled: net %s." % _iv(a["slippage_x2"]), "",
          "## One-tick sensitivity", "",
          "Entry %.2f up: %d flips; down: %d flips; of %d fires." % (a["one_tick"]["tick"], a["one_tick"]["up"],
                                                                     a["one_tick"]["down"], a["one_tick"]["of"]),
          "", "## Arms (reported, never promoted)", ""]
    for name in sorted(a["arms"]):
        v = a["arms"][name]
        L += ["### Arm %s (%d trades)" % (name, v["n"]), "", v["history"]["text"], v["control"]["text"], ""]
    L += ["## Baselines (diagnostic only)", ""]
    for name in ("B1", "B2"):
        v = a["baselines"][name]
        L.append("%s: net %s; by year %s." % (name, _iv(v["net"]), "; ".join(
            "%s %s" % (y, _iv(w["net"])) for y, w in sorted(v["by_year"].items())) or "none"))
    L += ["", "## Data", "", "Source %s, adjusted %s (the flat files, unadjusted; splits excluded by the guard)."
          % (a["data"]["source"], str(a["data"]["adjusted"]).lower()), "", "## The criteria of section 8", ""]
    for k in ("1", "2", "3", "4"):
        c = a["criteria"][k]
        L.append("%s. %s%s: %s" % (k, c["state"], "" if k in a["criteria_counted"] else " (struck, not counted)",
                                   c["text"]))
    L += ["", "Result: **%s**." % a["result"], ""]
    return "\n".join(L)


# ---------------------------------------------------------------- the command line

def parse(argv):
    ap = argparse.ArgumentParser(description="The runner of docs/PREREG_RVOL_ORB.md (from the repo root).")
    ap.add_argument("--window", choices=sorted(WINDOWS), required=True)
    ap.add_argument("--counts-only", action="store_true",
                    help="section 10's availability counts only: the one mode allowed before the freeze")
    ap.add_argument("--i-have-read-the-prereg", dest="read_it", action="store_true",
                    help="the holdout's own flag (section 7)")
    ap.add_argument("--out", help="the review document (default docs/reviews/rvol_<window>_<date>.md); with "
                                  "--counts-only, the counts file (default trader/data/rvol/counts-<window>.json)")
    return ap.parse_args(argv)


def counts_lines(doc):
    """The counts as lines (no price, no volume, no direction, no outcome)."""
    e = doc["eligible_per_session"]
    out = ["RVOL study, %s window, %s: %d sessions %s to %s." % (doc["window"], COUNT_NOTE, doc["sessions"],
                                                                doc["from"], doc["to"]),
           "reference_rows_by_month (CS, ADRC; as of the month's first session):"]
    for m, v in sorted(doc["reference_rows_by_month"].items()):
        out.append("  %s  CS %d  ADRC %d  (as of %s)" % (m, v["CS"], v["ADRC"], v["date"]))
    out += ["reference_requests: %d (pages over every monthly walk); requests this run: %d"
            % (doc["reference_requests"], doc["requests_this_run"]),
            "splits_rows: %d (%d pages)" % (doc["splits_rows"], doc["splits_requests"]),
            "eligible_per_session: median %s, interquartile range %s to %s (min %s, max %s, over %d sessions)"
            % (e["median"], e["q1"], e["q3"], e["min"], e["max"], e["sessions"]),
            "exclusions_by_cause (name-days; first failed cause, in the order %s): %s"
            % (", ".join(doc["funnel_order"]), ", ".join("%s %d" % (k, doc["exclusions_by_cause"][k])
                                                       for k in doc["funnel_order"])),
            "warmup sessions: %d" % doc["exclusions_by_cause"]["warmup_sessions"],
            "first_bar_coverage: %s" % ("n/a" if doc["first_bar_coverage"] is None
                                        else "%.4f" % doc["first_bar_coverage"]),
            "early_close_basis: %s" % (", ".join("%s %s" % kv for kv in sorted(doc["early_close_basis"].items()))
                                       or "none in the window"),
            "unlabelled short sessions (SPY at or under %d buckets, not a rule date): %d"
            % (EARLY_BARS, doc["unlabelled_short_sessions"]),
            "refused sessions: %s" % (", ".join(doc["refused_sessions"]) or "none")]
    return out


def main(argv=None, repo=None, client=None, study_kw=None):
    a = parse(argv)
    repo = repo or REPO
    freeze_hash = None
    if not a.counts_only:
        try:
            freeze_hash = freeze_check(repo)
            if a.window == "holdout":
                holdout_check(repo, a.read_it)
                holdout_out_check(repo, a.out)
        except Refused as e:
            print("rvol_study: refused, check %s" % e, file=sys.stderr)
            return 1
    # past the refusal: pandas, the data, the API
    log = lambda msg: print("rvol_study: %s" % msg, file=sys.stderr, flush=True)  # noqa: E731
    st = Study(a.window, client=client, log=log, repo=repo, **(study_kw or {}))
    M = st.mj["massive"]
    try:
        return _run(a, argv, repo, st, freeze_hash)
    except M.MassiveError as e:    # P2: an answer that is no, or no answer, is never a partial count
        print("rvol_study: %s (%s); nothing more was written" % (e, e.outcome), file=sys.stderr)
        return 2 if e.outcome == "unverified" else 1


def _run(a, argv, repo, st, freeze_hash):
    if a.counts_only:
        doc = st.counts()
        assert set(doc) <= set(COUNT_KEYS), sorted(set(doc) - set(COUNT_KEYS))
        out = a.out or os.path.join(st.data_dir, "counts-%s.json" % a.window)
        st._write_json(out, doc)
        print("\n".join(counts_lines(doc)))
        print("Wrote %s." % out)
        return 0
    stats = st.mj["stats"]
    rows = st.score()
    with open(os.path.join(repo, PREREG), encoding="utf-8") as fh:
        counted = criteria_counted(fh.read())
    agg = aggregate(stats, rows, counted)
    runner = st.stamp["runner_commit"]
    argv_text = ["tools/rvol_study.py"] + list(argv if argv is not None else sys.argv[1:])
    side = dict(agg, window=a.window, freeze_hash=freeze_hash, runner_commit=runner, command=argv_text)
    out = a.out or os.path.join(repo, "docs", "reviews", "rvol_%s_%s.md" % (
        a.window, st.K.today_et().isoformat()))
    text = report_text(agg, a.window, freeze_hash, runner, argv_text)
    bad = stats.banned_words(text)
    if bad:
        print("rvol_study: the report would carry banned words %s; not written" % bad, file=sys.stderr)
        return 1
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(text)
    with open(os.path.splitext(out)[0] + ".json", "w", encoding="utf-8") as fh:
        json.dump(side, fh, indent=1, sort_keys=True)
        fh.write("\n")
    print(text)
    print("Wrote %s and its sidecar." % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
