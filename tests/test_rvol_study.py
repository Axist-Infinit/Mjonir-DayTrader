"""tools/rvol_study.py (docs/PREREG_RVOL_ORB.md section 12), offline: a synthetic market written as tiny flat-file
folders under a temp dir (tests/synth.make_session sessions), a fake client for the two reference tables, and a
throwaway git repo for the freeze checks. No test opens the real flat files or asks the network."""

import contextlib
import csv
import datetime as dt
import gzip
import importlib.util
import io
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

import _mj
import synth
from _load import ROOT, load
from mjonir import calendar as K
from mjonir import control as C
from mjonir import costs as CO
from mjonir import localstores as LS
from mjonir import outcomes as O
from mjonir import rvol as R
from mjonir import stats as S
from mjonir import yahoo_shape as Y

TOOL = os.path.join(ROOT, "tools", "rvol_study.py")
_spec = importlib.util.spec_from_file_location("rvol_study", TOOL)
study = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(study)

CAL = K.Calendar()
WIN = {"dev": ("2025-10-01", "2025-12-05"), "holdout": ("2025-12-08", "2025-12-19")}
NAMES = ["A" + chr(ord("A") + i) for i in range(24)]          # AA .. AX
ADR = "AX"
SPLIT = ("AC", "2025-10-15")
LATE = ("AI", dt.date(2025, 10, 20))                           # first daily row: insufficient history before
GAP = ("AG", dt.date(2025, 11, 10))                            # opens 3x the prior close
NOBAR = ("AH", dt.date(2025, 11, 12))                          # no 9:30 bucket
CHEAP = "AA"                                                   # a $3 stock
EARLY = dt.date(2025, 11, 28)
HEADER = ["ticker", "volume", "open", "close", "high", "low", "window_start", "transactions"]


def build_market(root):
    """Minute files for every session of WIN, daily files from 2025-08-15, both gzipped CSVs in the vendor's
    columns. Returns (minute_dir, daily_dir)."""
    md, dd = os.path.join(root, "minute"), os.path.join(root, "daily")
    os.makedirs(md)
    os.makedirs(dd)
    minute_days = CAL.sessions_between(WIN["dev"][0], WIN["holdout"][1])
    daily_days = CAL.sessions_between("2025-08-15", WIN["holdout"][1])
    sessions = {}
    for d in daily_days:
        per = {}
        for i, sym in enumerate(NAMES + ["SPY"]):
            price = 3.0 if sym == CHEAP else 20.0 + 2 * i
            if sym == GAP[0] and d == GAP[1]:
                price *= 3
            s = synth.make_session(d, "%s:%d" % (sym, i), early_close=(d == EARLY), start=price)
            rng = random.Random("v:%s:%s" % (sym, d))
            for b in s:
                b["v"] = 1000 + rng.randrange(1000)
            s[0]["v"] = 5000 + rng.randrange(20000)
            per[sym] = s
        sessions[d] = per
    for d in daily_days:
        with gzip.open(os.path.join(dd, "%s.csv.gz" % d), "wt", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(HEADER)
            for sym in sorted(sessions[d]):
                if sym == LATE[0] and d < LATE[1]:
                    continue
                s = sessions[d][sym]
                o = (s[0]["o"] / 3) if (sym == GAP[0] and d == GAP[1]) else s[0]["o"]
                w.writerow([sym, 2000000, o, s[-1]["c"] if not (sym == GAP[0] and d == GAP[1]) else s[-1]["c"] / 3,
                            max(b["h"] for b in s), min(b["l"] for b in s),
                            K.ms_of(dt.datetime.combine(d, dt.time(0, 0), tzinfo=K.ET)) * 1000000, 50000])
    for d in minute_days:
        with gzip.open(os.path.join(md, "%s.csv.gz" % d), "wt", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(HEADER)
            for sym in sorted(sessions[d]):
                if sym == LATE[0] and d < LATE[1]:
                    continue
                for b in sessions[d][sym]:
                    if sym == NOBAR[0] and d == NOBAR[1] and b["slot"] == 0:
                        continue
                    w.writerow([sym, b["v"], b["o"], b["c"], b["h"], b["l"], b["t"] * 1000000, 7])
                if sym == "SPY" and d == EARLY:      # the early close's 13:00:00 closing print
                    t = K.ms_of(dt.datetime.combine(d, dt.time(13, 0), tzinfo=K.ET))
                    w.writerow(["SPY", 99, 1.0, 1.0, 1.0, 1.0, t * 1000000, 1])
    return md, dd


def reference(url, path, q):
    ty = q.get("type")
    rows = [{"ticker": t, "name": t + " Inc", "market": "stocks", "locale": "us", "type": ty, "active": True}
            for t in NAMES if (t == ADR) == (ty == "ADRC")]
    return {"status": "OK", "count": len(rows), "results": rows}


def splits(url, path, q):
    rows = [{"ticker": SPLIT[0], "execution_date": SPLIT[1], "split_from": 1, "split_to": 2, "id": "E1"}]
    return {"status": "OK", "results": [r for r in rows if q["execution_date.gte"] <= r["execution_date"]
                                        <= q["execution_date.lte"]]}


def fake_client():
    return _mj.client(_mj.FakeOpener(extra={"/v3/reference/tickers": reference, "/v3/reference/splits": splits}))


def git(repo, *args):
    p = subprocess.run(["git", "-C", repo] + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode:
        raise AssertionError("git %s: %s" % (" ".join(args), p.stderr.decode()))
    return p.stdout.decode().strip()


def init_repo(repo):
    """An empty throwaway git repo with docs/reviews/ made and a test identity. Returns its path."""
    os.makedirs(os.path.join(repo, "docs", "reviews"))
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "tests@example.com")
    git(repo, "config", "user.name", "tests")
    git(repo, "config", "commit.gpgsign", "false")
    return repo


def draft_text():
    """The real prereg with its status line put back to the DRAFT line, whatever the real one reads now."""
    with open(os.path.join(ROOT, study.PREREG), encoding="utf-8") as fh:
        text = fh.read()
    return re.sub(r"(?m)^Status: .*$", study.STATUS_DRAFT, text, count=1)


def draft_repo(root):
    """A throwaway git repo whose committed prereg reads DRAFT, with a copy of the runner in its tools/, so the
    copy's REPO (from its own __file__) is this repo and not ROOT. Returns (repo, path of the copied runner)."""
    repo = init_repo(os.path.join(root, "draft-repo"))
    os.makedirs(os.path.join(repo, "tools"))
    tool = os.path.join(repo, "tools", "rvol_study.py")
    shutil.copyfile(TOOL, tool)
    with open(os.path.join(repo, study.PREREG), "w", encoding="utf-8") as fh:
        fh.write(draft_text())
    git(repo, "add", study.PREREG, "tools/rvol_study.py")
    git(repo, "commit", "-q", "-m", "D0")
    return repo, tool


def frozen_repo(root):
    """A throwaway git repo holding the prereg through D0, F1 and F2 (section 1). Returns (repo, F1 hash)."""
    repo = init_repo(os.path.join(root, "repo"))
    draft = draft_text()
    path = os.path.join(repo, study.PREREG)

    def commit(body, msg):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
        git(repo, "add", study.PREREG)
        git(repo, "commit", "-q", "-m", msg)
        return git(repo, "rev-parse", "HEAD")
    commit(draft, "D0")
    f1 = commit(draft.replace("Status: DRAFT (awaiting the owner's freeze)",
                              "Status: FROZEN (commit pending)\nFrozen by the owner's word on 2026-11-04", 1), "F1")
    commit(draft.replace("Status: DRAFT (awaiting the owner's freeze)",
                         "Status: FROZEN (commit %s)\nFrozen by the owner's word on 2026-11-04" % f1, 1), "F2")
    return repo, f1


def run_main(argv, **kw):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = study.main(argv, **kw)
    return code, out.getvalue(), err.getvalue()


def keys_deep(x):
    if isinstance(x, dict):
        for k, v in x.items():
            yield k
            for kk in keys_deep(v):
                yield kk
    elif isinstance(x, list):
        for v in x:
            for kk in keys_deep(v):
                yield kk


SHARED = {}


def setUpModule():
    root = tempfile.mkdtemp(prefix="rvol-study-")
    md, dd = build_market(root)
    repo, f1 = frozen_repo(root)
    SHARED.update(root=root, md=md, dd=dd, repo=repo, f1=f1)


def tearDownModule():
    shutil.rmtree(SHARED["root"], True)


class Market(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for k, v in SHARED.items():
            setattr(cls, k, v)

    def kw(self, data=None):
        return {"minute_dir": self.md, "daily_dir": self.dd, "data_dir": data or tempfile.mkdtemp(dir=self.root),
                "min_reference_rows": {"CS": 1, "ADRC": 1}, "windows": WIN}

    def make(self, window="dev", data=None):
        return study.Study(window, client=fake_client(), **self.kw(data))


class Freeze(Market):
    def test_the_frozen_repo_passes_and_names_f1(self):
        self.assertEqual(study.freeze_check(self.repo), self.f1)

    def test_the_real_document_is_frozen_at_f1(self):
        # F1 5631923 froze it and F2 recorded the hash; after F2 only section 13 may change
        with open(os.path.join(ROOT, study.PREREG), encoding="utf-8") as fh:
            line = next(ln for ln in fh.read().split("\n") if ln.startswith("Status: "))
        self.assertEqual(line, "Status: FROZEN (commit 56319239840bc3a54ae40649cb03314d880c1cb2)")
        self.assertEqual(study.freeze_check(ROOT), "56319239840bc3a54ae40649cb03314d880c1cb2")

    def test_this_documents_own_status_gives_the_matching_outcome(self):
        # reads the document's own status line, so F1 and F2 do not turn the suite red
        with open(os.path.join(ROOT, study.PREREG), encoding="utf-8") as fh:
            line = next(ln for ln in fh.read().split("\n") if ln.startswith("Status: "))
        m = study.STATUS_RE.match(line)
        if m:
            self.assertTrue(study.freeze_check(ROOT).startswith(m.group(1)), line)
        else:                                            # DRAFT, or F1's "commit pending"
            self.assertIn(line, (study.STATUS_DRAFT, study.STATUS_PENDING))
            with self.assertRaises(study.Refused) as e:
                study.freeze_check(ROOT)
            self.assertEqual(e.exception.check, "status")

    def test_a_retune_repointed_at_a_later_pending_commit_is_refused(self):
        repo = os.path.join(tempfile.mkdtemp(dir=self.root), "r")
        shutil.copytree(self.repo, repo)
        path = os.path.join(repo, study.PREREG)
        with open(path, encoding="utf-8") as fh:
            good = fh.read()
        frozen_line = "Status: FROZEN (commit %s)" % self.f1
        retuned = good.replace("| `TOP_K` | 20 |", "| `TOP_K` | 25 |")

        def commit(body, msg):
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(body)
            git(repo, "commit", "-q", "-am", msg)
            return git(repo, "rev-parse", "HEAD")
        c3 = commit(retuned.replace(frozen_line, study.STATUS_PENDING), "C3: retune, pending")
        commit(retuned.replace(frozen_line, "Status: FROZEN (commit %s)" % c3), "C4: points at C3")
        with self.assertRaises(study.Refused) as e:      # C3's parent is F2, not the draft
            study.freeze_check(repo)
        self.assertEqual(e.exception.check, "freeze commit")
        self.assertIn("parent", str(e.exception))
        c5 = commit(retuned.replace(frozen_line, study.STATUS_DRAFT), "C5: back to a draft")
        c6 = commit(retuned.replace(frozen_line, study.STATUS_PENDING), "C6: pending again")
        commit(retuned.replace(frozen_line, "Status: FROZEN (commit %s)" % c6), "C7: points at C6")
        with self.assertRaises(study.Refused) as e:      # a re-freeze: an earlier version already reads FROZEN
            study.freeze_check(repo)
        self.assertEqual(e.exception.check, "freeze commit")
        self.assertIn("frozen before", str(e.exception))
        self.assertTrue(c5)
        d0 = git(repo, "rev-list", "--max-parents=0", "HEAD")
        commit(good.replace(frozen_line, "Status: FROZEN (commit %s)" % d0), "points at D0")
        with self.assertRaises(study.Refused) as e:      # D0 reads DRAFT, not pending
            study.freeze_check(repo)
        self.assertEqual(e.exception.check, "freeze commit")
        self.assertEqual(study.freeze_check(self.repo), self.f1)      # the honest D0, F1, F2 path passes

    def test_an_altered_body_a_planted_hash_and_a_dirty_file(self):
        repo = os.path.join(tempfile.mkdtemp(dir=self.root), "r")
        shutil.copytree(self.repo, repo)
        path = os.path.join(repo, study.PREREG)
        with open(path, encoding="utf-8") as fh:
            good = fh.read()
        altered = good.replace("| `TOP_K` | 20 |", "| `TOP_K` | 25 |")
        self.assertNotEqual(altered, good)
        for body, check in ((altered, "body"),                                      # uncommitted: body first
                            (good.replace(self.f1, "f" * 40), "commit"),            # no such object
                            (good.replace("(None. Entries", "(None yet. Entries"), "clean")):  # section 13 only
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(body)
            with self.assertRaises(study.Refused) as e:
                study.freeze_check(repo)
            self.assertEqual(e.exception.check, check)
        with open(path, "w", encoding="utf-8") as fh:        # a commit that exists but never touched the document
            fh.write(good)
        with open(os.path.join(repo, "other.txt"), "w") as fh:
            fh.write("x\n")
        git(repo, "add", "other.txt")
        git(repo, "commit", "-q", "-m", "other")
        other = git(repo, "rev-parse", "HEAD")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(good.replace(self.f1, other))
        git(repo, "commit", "-q", "-am", "status points at another commit")
        with self.assertRaises(study.Refused) as e:
            study.freeze_check(repo)
        self.assertEqual(e.exception.check, "history")
        # a committed body change is still a refusal; a dated postscript in section 13 is not
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(altered)
        git(repo, "commit", "-q", "-am", "retune")
        with self.assertRaises(study.Refused) as e:
            study.freeze_check(repo)
        self.assertEqual(e.exception.check, "body")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(good.replace("(None. Entries here are dated and signed;",
                                  "2027-01-01, the lead: a postscript.\n\n(None. Entries here are dated and signed;"))
        git(repo, "commit", "-q", "-am", "postscript")
        self.assertEqual(study.freeze_check(repo), self.f1)

    def test_the_draft_refusal_opens_no_file_and_imports_no_pandas(self):
        # its own DRAFT repo and a copy of the runner there: the real document is frozen since F1/F2
        repo, tool = draft_repo(tempfile.mkdtemp(dir=self.root))
        locked = tempfile.mkdtemp(dir=self.root)
        data = tempfile.mkdtemp(dir=self.root)
        os.chmod(locked, 0)
        try:
            env = dict(os.environ, MJONIR_FLATFILE_DIR=locked, MJONIR_DAILY_DIR=locked, MJONIR_DATA_DIR=data,
                       PYTHONPATH=ROOT)                  # mjonir from ROOT, should the copy ever get past the check
            code = ("import runpy, sys\nsys.argv = ['tools/rvol_study.py', '--window', 'dev']\ntry:\n"
                    "    runpy.run_path(%r, run_name='__main__')\nexcept SystemExit as e:\n    print('EXIT', e.code)\n"
                    "print('PANDAS', 'pandas' in sys.modules)\n" % tool)
            p = subprocess.run([sys.executable, "-c", code], cwd=repo, env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
        finally:
            os.chmod(locked, 0o700)
        out, err = p.stdout.decode(), p.stderr.decode()
        self.assertIn("EXIT 1", out)
        self.assertIn("PANDAS False", out)
        self.assertIn("refused, check status", err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(os.listdir(data), [])

    def test_the_holdout_refusals(self):
        code, out, err = run_main(["--window", "holdout"], repo=self.repo)
        self.assertEqual((code, "check holdout flag" in err), (1, True))
        code, out, err = run_main(["--window", "holdout", "--i-have-read-the-prereg"], repo=self.repo)
        self.assertEqual((code, "check development sidecar" in err), (1, True))
        repo = os.path.join(tempfile.mkdtemp(dir=self.root), "r")
        shutil.copytree(self.repo, repo)
        rd = os.path.join(repo, "docs", "reviews")
        side = {"criteria": dict((k, {"state": "pass"}) for k in "1234"), "criteria_counted": list("1234")}
        with open(os.path.join(rd, "rvol_dev_2027-01-01.json"), "w") as fh:
            json.dump(dict(side, criteria=dict(side["criteria"], **{"4": {"state": "unverified"}})), fh)
        with open(os.path.join(rd, "rvol_dev_2027-01-01.md"), "w") as fh:
            fh.write("x\n")
        with self.assertRaises(study.Refused) as e:
            study.holdout_check(repo, True)
        self.assertEqual(e.exception.check, "development sidecar")
        with open(os.path.join(rd, "rvol_dev_2027-01-01.json"), "w") as fh:
            json.dump(side, fh)
        self.assertEqual(study.holdout_check(repo, True), "rvol_dev_2027-01-01.json")
        # the counted criteria come from the frozen text, never from the sidecar
        with open(os.path.join(rd, "rvol_dev_2027-01-01.json"), "w") as fh:
            json.dump(dict(side, criteria=dict(side["criteria"], **{"4": {"state": "unverified"}}),
                           criteria_counted=["1", "2", "3"]), fh)
        with self.assertRaises(study.Refused) as e:
            study.holdout_check(repo, True)
        self.assertEqual(e.exception.check, "development sidecar")
        doc = os.path.join(repo, study.PREREG)
        with open(doc, encoding="utf-8") as fh:
            text = fh.read()
        with open(doc, "w", encoding="utf-8") as fh:            # a text that strikes criterion 4
            fh.write(text.replace("4. The session-level interval", "4. ~~struck~~"))
        self.assertEqual(study.holdout_check(repo, True), "rvol_dev_2027-01-01.json")
        with open(doc, "w", encoding="utf-8") as fh:
            fh.write(text)
        with open(os.path.join(rd, "rvol_dev_2027-01-01.json"), "w") as fh:
            json.dump(side, fh)
        # the holdout review goes where the second-run refusal looks
        for bad in (os.path.join(self.root, "rvol_holdout_x.md"), os.path.join(rd, "holdout.md"),
                    os.path.join(rd, "rvol_holdout_x.json")):
            with self.assertRaises(study.Refused) as e:
                study.holdout_out_check(repo, bad)
            self.assertEqual(e.exception.check, "holdout out")
        self.assertIsNone(study.holdout_out_check(repo, os.path.join(rd, "rvol_holdout_2027-02-01.md")))
        self.assertIsNone(study.holdout_out_check(repo, None))
        code, out, err = run_main(["--window", "holdout", "--i-have-read-the-prereg", "--out",
                                   os.path.join(self.root, "elsewhere.md")], repo=repo)
        self.assertEqual((code, "check holdout out" in err), (1, True))
        with open(os.path.join(rd, "rvol_holdout_2027-02-01.md"), "w") as fh:
            fh.write("x\n")
        with self.assertRaises(study.Refused) as e:
            study.holdout_check(repo, True)
        self.assertEqual(e.exception.check, "second holdout")


class Pieces(Market):
    def test_the_first_bar_fold_from_three_minute_rows(self):
        st = self.make()
        day = dt.date(2025, 10, 6)

        def ns(h, m):
            return K.ms_of(dt.datetime.combine(day, dt.time(h, m), tzinfo=K.ET)) * 1000000
        rows = [("ZZZ", 100.0, 10.0, 10.2, 10.3, 9.9, ns(9, 30), 3),
                ("ZZZ", 50.0, 10.2, 10.1, 10.4, 10.0, ns(9, 31), 2),
                ("ZZZ", 70.0, 10.1, 10.5, 10.6, 10.05, ns(9, 34), 4),
                ("ZZZ", 999.0, 11.0, 11.0, 11.0, 11.0, ns(9, 35), 1)]
        df = st.pd.DataFrame(rows, columns=HEADER)
        off = K.tz_label(day)[1]
        df["mod"] = ((df["window_start"] // 1000000000 + off) % 86400) // 60
        got = st.fold(df[(df["mod"] >= 570) & (df["mod"] < 575)])["ZZZ"]
        self.assertEqual(len(got), 1)
        b = got[0]
        self.assertEqual((b["i"], b["o"], b["h"], b["l"], b["c"], b["v"]), (0, 10.0, 10.6, 9.9, 10.5, 220.0))
        ref = LS.fold_minutes_to_5m([{"t": r[6] // 1000000, "o": r[2], "h": r[4], "l": r[5], "c": r[3], "v": r[1],
                                      "n": r[7]} for r in rows[:3]])
        self.assertEqual(dict((k, b[k]) for k in ref[0]), ref[0])
        full = st.fold(df)["ZZZ"]
        self.assertEqual([x["i"] for x in full], [0, 1])

    def test_the_store_and_the_spy_count(self):
        st = self.make()
        firsts, meta, _ = st.build_store(EARLY)
        self.assertEqual(meta["spy_buckets"], 42)          # 9:30 to 12:55, the 13:00:00 print left out
        self.assertEqual(st.session_status(EARLY, meta)[1:], (True, "verified"))
        firsts2, meta2, _ = st.build_store(dt.date(2025, 11, 26))
        self.assertEqual(meta2["spy_buckets"], 78)
        with open(st.store_path(EARLY)) as fh:
            self.assertEqual(fh.readline().strip(), "ticker,open,close,volume")
        st._store.clear()
        self.assertEqual(st.store(EARLY)[0], firsts)        # the values come back unrounded
        self.assertNotIn(NOBAR[0], st.build_store(NOBAR[1])[0])

    def test_ties_and_the_doji_go_through_mjonir_rvol(self):
        def row(sym, rvol, o, c):
            return {"symbol": sym, "rvol": rvol, "first_bar": {"o": o, "h": None, "l": None, "c": c, "v": 1.0},
                    "direction": R.direction(o, c)}
        listed = self.make().R.rank([row("BBB", 2.0, 1.0, 1.1), row("AAA", 2.0, 1.0, 1.0), row("CCC", 3.0, 1.0, 0.9)],
                                    2)
        self.assertEqual([(r["symbol"], r["rank"], r["fire"]) for r in listed], [("CCC", 1, False), ("AAA", 2, False)])
        self.assertIs(study.Study.__init__.__globals__["_mj"]()["rvol"], R)

    def test_the_atr_is_trader_exits(self):
        exitp = load("trader-exit", "exit")
        rng = random.Random(5)
        day = dt.date(2025, 11, 20)
        days = CAL.sessions_back(CAL.prev_session(day), 30)
        rows = []
        prev = 50.0
        for d in days:
            o = prev * (1 + rng.gauss(0, 0.01))
            c = o * (1 + rng.gauss(0, 0.02))
            h, lo = max(o, c) * 1.01, min(o, c) * 0.99
            rows.append((K.ms_of(dt.datetime.combine(d, dt.time(9, 30), tzinfo=K.ET)), o, h, lo, c, 1e6))
            prev = c
        saved = Y.fetch_daily_rows
        Y.fetch_daily_rows = lambda client, cal, symbol, start, end: [r for r in rows if K.as_date(start) <= K.et_of_ms(
            r[0]).date() <= K.as_date(end)]
        try:
            want, n = exitp.daily_atr("SYN", day)
        finally:
            Y.fetch_daily_rows = saved
        self.assertEqual(n, 14)
        self.assertEqual(study.atr_of([r[1:] for r in rows], 14), want)

    def test_the_risk_floor_widens_and_keeps_its_controls(self):
        stop, risk, bound = study.stop_of(100.0, 3.0)
        self.assertEqual((stop, risk, bound), (100.0 - 0.3, 100.0 - (100.0 - 0.3), False))
        found = 0
        for k in range(600):
            e = 5.0 + k * 0.4321
            plain = e - e * 0.05 / 100.0
            stop, risk, bound = study.stop_of(e, 0.001)
            self.assertTrue(bound)
            self.assertFalse(100.0 * (e - stop) / e < C.RISK_FLOOR_PCT, e)
            self.assertLess(abs(risk - e * 0.0005), 1e-9 * e)
            if 100.0 * (e - plain) / e < C.RISK_FLOOR_PCT:
                found += 1
                bars = synth.make_session(dt.date(2025, 11, 3), k, start=e)
                bars[0]["c"] = e
                got, why = C.draw_controls(bars, "SYN", "2025-11-03", 19, 3, 1, 77, e, stop, None)
                self.assertEqual((len(got), why), (3, {}))
                self.assertEqual(C.draw_controls(bars, "SYN", "2025-11-03", 19, 3, 1, 77, e, plain, None)[1],
                                 {"risk_floor": 3})
        self.assertGreater(found, 100)       # the float edge the guard exists for is real

    def test_a_session_scored_with_other_code_is_scored_again(self):
        st = self.make()
        st.splits()
        day = CAL.sessions_between(WIN["dev"][0], WIN["dev"][1])[20]
        st.score_session(day, study._timemachine())
        with open(st.day_path(day)) as fh:
            rows = [json.loads(x) for x in fh]
        self.assertEqual((rows[0]["kind"], rows[-1]["kind"]), ("session", "end"))
        self.assertEqual(rows[0]["stamp"], st.stamp)
        self.assertEqual(rows[-1]["stamp"], st.stamp)
        self.assertEqual(sorted(st.stamp), ["code_sha256", "runner_commit"])
        self.assertEqual(len(st.stamp["code_sha256"]), 64)
        self.assertEqual(st.read_day(day), rows[:-1])
        good = st.stamp
        for other in (dict(good, code_sha256="0" * 64), dict(good, runner_commit="f" * 40)):
            st.stamp = other
            self.assertIsNone(st.read_day(day))
        st.stamp = good
        self.assertIsNotNone(st.read_day(day))
        saved = dict(study.PARAMS)
        try:
            study.PARAMS["POSTHOC_GATE_DATE"] = "2099-01-01"      # any parameter changes the hash
            self.assertNotEqual(study.code_stamp(study.REPO, R)["code_sha256"], good["code_sha256"])
        finally:
            study.PARAMS.clear()
            study.PARAMS.update(saved)
        self.assertEqual(study.code_stamp(study.REPO, R), good)

    def test_the_control_pinned_to_bar_zero_gives_a_delta_of_zero(self):
        rule, ctrl = {}, {}
        for k in range(45):
            day = CAL.sessions_back(dt.date(2025, 12, 31), 45)[k].isoformat()
            bars = synth.make_session(day, k, start=40.0)
            e = bars[0]["c"]
            stop, risk, _ = study.stop_of(e, 0.8)
            model = {"per_side_bps": 7.0, "commission_usd": 1.0, "shares": None, "max_loss_usd": 1000.0}

            def cost_fn(en, rk, model=model):
                return CO.trade_cost_r(en, rk, model)
            res = O.score_trade(bars, 0, e, stop, None, 76, cost_fn(e, risk))
            got, why = C.draw_controls(bars, "SYN", day, 19, 3, 1, 76, e, stop, None, cost_fn, force_bar=0)
            rule[day] = [res["net_r"]]
            ctrl[day] = [c["net_r"] for c in got]
        d = S.paired_delta_ci(rule, ctrl, seed=19, draws=2000)
        self.assertEqual(d["n_sessions"], 45)
        for k in ("delta", "lo", "hi"):          # zero up to the float mean of three equal draws
            self.assertAlmostEqual(d[k], 0.0, places=12)
        self.assertEqual(S.verdict_control(d)["reason"], "straddles")

    def test_the_parameters_are_the_documents(self):
        with open(os.path.join(ROOT, study.PREREG), encoding="utf-8") as fh:
            text = fh.read()
        table = dict(re.findall(r"(?m)^\| `([A-Z_0-9, `]+)` \| ([^|]+) \|", text))
        P = study.PARAMS
        expect = {"P_MIN": "5.00 USD", "ADV_USD_MIN": "20,000,000 USD", "ADV_SH_MIN": "1,000,000 shares",
                  "TOP_K": "20", "STOP_ATR_FRAC": "0.10", "CONTROL_K": "3 draws a fill", "SEED": "19",
                  "DRAWS": "2,000", "N_FLOOR": "40", "TICK": "0.01 USD", "OR15_MIN": "15 minutes",
                  "POSTHOC_GATE_DATE": "2027-02-04"}
        for k, v in expect.items():
            self.assertTrue(table[k].startswith(v), (k, table[k]))
        self.assertIn("| `ADV_N` (the ADV window) | 20 sessions strictly before D |", text)
        for k, v in (("RVOL_N", "14 sessions"), ("ATR_N", "14 daily true ranges, from 15"),
                     ("RISK_FLOOR_PCT", "0.05 percent"), ("FLAT_BY", "15:55 ET; 12:55 ET"),
                     ("GAP_GUARD", "the first bar's open under 0.4 or over 2.5"),
                     ("COST_TIERS", "[[100,000,000, 4], [30,000,000, 8], [0, 15]]"), ("HALF_SPREAD", "3.0 bp"),
                     ("COMMISSION", "1.00 USD"), ("SLIP_X2", "the tiers doubled: [[100,000,000, 8], [30,000,000, 16], "
                                                            "[0, 30]]"),
                     ("FRAGILE_R", "0.05 R"), ("ARM_TARGETS", "1R and 2R"), ("NO_ENTRIES_AFTER", "15:30 ET; 12:30 ET"),
                     ("LEVEL", "95 percent")):
            self.assertTrue(table[k].startswith(v), (k, table[k]))
        self.assertEqual((P["P_MIN"], P["ADV_USD_MIN"], P["ADV_SH_MIN"], P["ADV_N"], P["RVOL_N"], P["ATR_N"]),
                         (R.P_MIN, R.ADV_USD_MIN, R.ADV_SH_MIN, R.ADV_N, R.RVOL_N, 14))
        self.assertEqual((P["TOP_K"], tuple(P["GAP_GUARD"])), (R.TOP_K, R.GAP_GUARD))
        self.assertEqual((P["ATR_MIN"], P["RVOL_MIN"], P["TICK"]), (R.ATR_MIN, R.RVOL_MIN, R.TICK))
        for k, v in (("ATR_MIN", "0.50 USD"), ("RVOL_MIN", "1.0"), ("ENTRY_LEVEL", "the first bar's high plus `TICK`"),
                     ("ENTRY_UNTIL", "the `NO_ENTRIES_AFTER` bucket: index 71 on a full session, 35 on an early")):
            self.assertTrue(table[k].startswith(v), (k, table[k]))
        self.assertEqual(P["COST_TIERS"], CO.DEFAULTS["slippage_tiers_bps"])
        self.assertEqual(P["SLIP_X2"], [[f, 2 * b] for f, b in CO.DEFAULTS["slippage_tiers_bps"]])
        self.assertEqual((P["HALF_SPREAD"], P["COMMISSION"]), (CO.DEFAULTS["default_half_spread_bps"],
                                                              CO.DEFAULTS["commission_usd"]))
        self.assertEqual(P["SHARES_BASIS_MAX_LOSS"], 100000 * 1.0 / 100)
        self.assertEqual((P["SEED"], P["DRAWS"], P["LEVEL"], P["N_FLOOR"]), (S.SEED, S.DRAWS, S.LEVEL, S.N_FLOOR))
        self.assertEqual((P["FRAGILE_R"], P["RISK_FLOOR_PCT"]), (O.FRAGILE_R, C.RISK_FLOOR_PCT))
        self.assertEqual((P["FLAT_BY"], P["FLAT_BY_EARLY"], P["NO_ENTRIES_AFTER"], P["NO_ENTRIES_AFTER_EARLY"]),
                         ("15:55", "12:55", "15:30", "12:30"))
        self.assertEqual(P["ARM_TARGETS"], (1.0, 2.0))
        self.assertEqual(study.criteria_counted(text), ["1", "2", "3", "4"])
        self.assertEqual(study.criteria_counted(text.replace("4. The session-level interval", "4. ~~struck~~")),
                         ["1", "2", "3"])


class Window(Market):
    def test_counts_only_writes_counts_and_nothing_else(self):
        data = tempfile.mkdtemp(dir=self.root)
        out = os.path.join(data, "counts.json")
        calls = []
        real = R.bar_stage

        def spy(*a, **kw):
            calls.append(kw.get("rows", True))
            return real(*a, **kw)
        R.bar_stage = spy
        try:
            code, text, err = run_main(["--window", "dev", "--counts-only", "--out", out], repo=ROOT,
                                       client=fake_client(), study_kw=self.kw(data))
        finally:
            R.bar_stage = real
        self.assertEqual(code, 0, err)
        self.assertTrue(calls)
        self.assertEqual(set(calls), {False})           # counts-only computes no RVOL and no direction
        with open(out) as fh:
            doc = json.load(fh)
        self.assertEqual(set(doc), set(study.COUNT_KEYS))
        allowed = set(study.COUNT_KEYS) | {"CS", "ADRC", "date", "pages_CS", "pages_ADRC", "sessions", "median", "q1",
                                           "q3", "min", "max", "warmup_sessions"} | set(R.CAUSES)
        allowed |= set(doc["reference_rows_by_month"]) | set(doc["early_close_basis"])
        self.assertEqual(set(keys_deep(doc)) - allowed, set())
        blob = (json.dumps(doc) + text).lower()
        for word in ("fire", "doji", "outcome", "net_r", "gross_r", "direction", "\"up\"", "\"down\"", " up ",
                     " down ", "\"o\"", "\"c\"", "\"v\""):
            self.assertNotIn(word, blob)
        ex = doc["exclusions_by_cause"]
        self.assertEqual(ex["warmup_sessions"], 14)
        self.assertGreater(ex["split_guard"], 0)
        self.assertGreater(ex["insufficient_history"], 0)
        self.assertEqual(ex["below_price"], len(CAL.sessions_between(WIN["dev"][0], WIN["dev"][1])) - 14)
        self.assertEqual((ex["gap_guard"], ex["no_first_bar"]), (1, 1))
        self.assertEqual(doc["early_close_basis"], {EARLY.isoformat(): "verified"})
        self.assertEqual(doc["unlabelled_short_sessions"], 0)
        self.assertEqual(sorted(doc["reference_rows_by_month"]), ["2025-10", "2025-11", "2025-12"])
        self.assertEqual(doc["reference_rows_by_month"]["2025-11"], {"CS": 23, "ADRC": 1, "date": "2025-11-03",
                                                                     "pages_CS": 1, "pages_ADRC": 1})
        self.assertEqual((doc["reference_requests"], doc["requests_this_run"], doc["splits_rows"]), (6, 7, 1))
        self.assertEqual(ex["rvol_history_short"], 14)      # AH's missing 9:30 bar sits in the next 14 histories
        self.assertTrue(0.0 < doc["first_bar_coverage"] < 1.0)
        self.assertEqual(len(os.listdir(os.path.join(data, "rvol", "firstbars"))), 2 * len(
            CAL.sessions_between(WIN["dev"][0], WIN["dev"][1])))
        # a re-run reads the caches: no request, the same counts
        code, text2, err = run_main(["--window", "dev", "--counts-only", "--out", out], repo=ROOT,
                                    client=fake_client(), study_kw=self.kw(data))
        with open(out) as fh:
            again = json.load(fh)
        self.assertEqual(again["requests_this_run"], 0)
        self.assertEqual(dict(again, requests_this_run=7), doc)
        # the holdout's history comes from the development window's last sessions: no warm-up there
        code, text3, err = run_main(["--window", "holdout", "--counts-only"], repo=ROOT, client=fake_client(),
                                    study_kw=self.kw(data))
        self.assertEqual(code, 0, err)
        with open(os.path.join(data, "rvol", "counts-holdout.json")) as fh:
            ho = json.load(fh)
        self.assertEqual(ho["exclusions_by_cause"]["warmup_sessions"], 0)
        self.assertEqual(ho["eligible_per_session"]["sessions"], 10)

    def test_a_short_reference_walk_is_a_refusal_not_a_count(self):
        def short(url, path, q):
            doc = reference(url, path, q)
            doc["count"] += 1                          # the page says more rows than it holds
            return doc
        bad = _mj.client(_mj.FakeOpener(extra={"/v3/reference/tickers": short, "/v3/reference/splits": splits}))
        data = tempfile.mkdtemp(dir=self.root)
        code, text, err = run_main(["--window", "dev", "--counts-only"], repo=ROOT, client=bad, study_kw=self.kw(data))
        self.assertEqual(code, 1)
        self.assertIn("count", err)
        self.assertIn("refused", err)
        self.assertFalse(os.path.exists(os.path.join(data, "rvol", "counts-dev.json")))
        self.assertFalse(os.path.exists(os.path.join(data, "rvol", "reference")))

    def test_a_synthetic_window_scores_and_writes_the_sidecar(self):
        data = tempfile.mkdtemp(dir=self.root)
        out = os.path.join(self.repo, "docs", "reviews", "rvol_dev_test.md")
        code, text, err = run_main(["--window", "dev", "--out", out], repo=self.repo, client=fake_client(),
                                   study_kw=self.kw(data))
        self.assertEqual(code, 0, err)
        with open(out[:-3] + ".json") as fh:
            side = json.load(fh)
        for k in ("sessions", "funnel", "eligible_per_session", "orders", "fills", "primary", "control", "delta",
                  "session_level", "by_year", "by_year_note", "slippage_x2", "one_tick", "arms", "baselines", "data",
                  "criteria", "criteria_counted", "result", "freeze_hash", "runner_commit", "command", "window"):
            self.assertIn(k, side)
        self.assertEqual(side["freeze_hash"], self.f1)
        self.assertEqual(side["data"], {"source": "flatfile", "adjusted": False})
        self.assertEqual(side["sessions"]["warmup"], 14)
        self.assertEqual(side["sessions"]["early_close_basis"], {EARLY.isoformat(): "verified"})
        self.assertEqual(sorted(side["arms"]), ["A1", "A2", "B", "E"])
        self.assertEqual(sorted(side["criteria"]), ["1", "2", "3", "4"])
        self.assertIn(side["result"], ("pass", "closed"))
        o = side["orders"]
        self.assertGreater(side["fills"]["n"], 0)
        self.assertEqual((o["filled"], o["filled"] + o["no_fill"]), (side["fills"]["n"], o["n"]))
        self.assertGreater(o["no_fill"], 0)
        self.assertLessEqual(max(int(k) for k in o["per_session"]), 20)
        self.assertEqual(side["arms"]["E"]["n"], o["n"])               # the continuation on every order
        self.assertEqual(side["arms"]["B"]["n"], side["fills"]["n"])   # arm B on the fills
        self.assertEqual(side["primary"]["text"], S.verdict_history(
            {"triggered": side["fills"]["n"], "target": 0, "stop": side["fills"]["outcomes"]["stop"],
             "expectancy": dict(side["primary"], n=side["primary"]["n"], mean=side["primary"]["mean"])},
            None, side["fills"]["cost_r_mean"])["text"])
        with open(out) as fh:
            doc = fh.read()
        self.assertEqual(S.banned_words(doc), [])
        self.assertNotIn("\u2014", doc)
        for head in ("Availability funnel", "## Orders and fills", "criterion 1",
                     "criterion 2", "criterion 4", "By year",
                     "Slippage", "One-tick", "Arms", "Baselines", "## Data", "criteria of section 8", "Result:"):
            self.assertIn(head, doc)
        # the per-session lines: every fire scored once, three draws or a counted skip each
        rows = []
        for f in sorted(os.listdir(os.path.join(data, "rvol", "dev"))):
            with open(os.path.join(data, "rvol", "dev", f)) as fh:
                rows += [json.loads(x) for x in fh]
        fires = [r for r in rows if r["kind"] == "fill"]
        orders = dict(((r["date"], r["symbol"]), r) for r in rows if r["kind"] == "order")
        draws = [r for r in rows if r["kind"] == "draw" and r["arm"] == "primary"]
        skips = sum(sum(r["why"].values()) for r in rows if r["kind"] == "draw_skip" and r["arm"] == "primary")
        self.assertEqual(len(draws) + skips, 3 * len(fires))
        self.assertTrue(all(f["date"] != EARLY.isoformat() or f["last"] <= 40 for f in fires))
        for f in fires:                       # the fill: bucket 1 to the cancel bucket, at max(level, its open)
            od = orders[(f["date"], f["symbol"])]
            self.assertTrue(od["filled"] and 1 <= f["k"] <= od["until"] <= (71 if f["date"] != EARLY.isoformat()
                                                                             else 35))
            self.assertGreaterEqual(f["entry"], f["level"])
        by = dict(((d["date"], d["symbol"]), []) for d in draws)
        for d in draws:
            by[(d["date"], d["symbol"])].append(d)
        for (date, sym), ds in by.items():    # every primary control inside the order's own window
            self.assertTrue(all(1 <= d["bar"] <= orders[(date, sym)]["until"] for d in ds))
        # the same inputs, a fresh data folder: the same sidecar, byte for byte
        with open(out[:-3] + ".json", "rb") as fh:
            first = fh.read()
        code, text, err = run_main(["--window", "dev", "--out", out], repo=self.repo, client=fake_client(),
                                   study_kw=self.kw())
        self.assertEqual(code, 0, err)
        with open(out[:-3] + ".json", "rb") as fh:
            self.assertEqual(fh.read(), first)


if __name__ == "__main__":
    unittest.main()
