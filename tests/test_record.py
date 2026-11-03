"""Chunk 3.1: the forward record (trader-record/record.py, mjonir/ledger.py). Append-only files, ids written once,
scoring exactly as the time machine's history scores the same plan, the control inside the entry window, the
decisions from trader-broker, the broker fills, the gate in three outcomes, the journal. No network."""

import ast
import contextlib
import datetime as dt
import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import unittest

import _mj  # noqa: F401  (sys.path, throwaway data dirs, no key)
import synth
from _load import FIX, ROOT, load
from mjonir import calendar as K
from mjonir import costs as C
from mjonir import ledger as L
from mjonir import stats as S

record = load("trader-record", "record")
entry = load("trader-entry", "entry")
ticket = load("trader-broker", "ticket")
tm = load("trader-timemachine", "timemachine")

TSLA = os.path.join(FIX, "trader-entry", "TSLA-2026-10-19-5m.json")
MASSIVE_DAY = os.path.join(FIX, "mjonir", "aggs-TSLA-5m-2026-10-19.json")


def run(mod, argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = mod.main(argv)
    return code, out.getvalue(), err.getvalue()


def sha(path):
    if not os.path.exists(path):
        return None
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def cents_session(date, seed, early=False, start=400.0, up=True):
    """A synthetic session in whole cents whose bar 4 closes 50 cents over the opening-range high (or under the
    low), so the record's cent prices and the time machine's unrounded ones are the same numbers."""
    s = synth.breakout_session(date, seed, early_close=early, start=start, up=up)
    for b in s:
        for k in ("o", "h", "l", "c"):
            b[k] = round(b[k], 2)
    oh = max(b["h"] for b in s[:3])
    ol = min(b["l"] for b in s[:3])
    s[3]["c"] = min(s[3]["c"], oh) if up else max(s[3]["c"], ol)
    s[4]["c"] = round(oh + 0.5, 2) if up else round(ol - 0.5, 2)
    for b in s[3:5]:
        b["h"], b["l"] = max(b["h"], b["o"], b["c"]), min(b["l"], b["o"], b["c"])
    return s


LIGHT = {"min_reward_risk": 0, "max_loss_per_trade_usd": 500,
         "costs": {"slippage_tiers_bps": [[0, 2]], "commission_usd": 1.0, "default_half_spread_bps": 1.0,
                   "spread_source": "default"}}


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.rec = os.path.join(self.d, "record")
        self.saved_env = os.environ.get("TRADER_RECORD_DIR")
        os.environ["TRADER_RECORD_DIR"] = self.rec
        self.tp, self.sp = L.paths(self.rec)
        self.cfg = os.path.join(self.d, "config.json")
        with open(self.cfg, "w") as fh:
            json.dump(LIGHT, fh)

    def tearDown(self):
        os.environ["TRADER_RECORD_DIR"] = self.saved_env
        shutil.rmtree(self.d)

    def chart_file(self, sym, sessions, name=None):
        p = os.path.join(self.d, name or (sym + ".json"))
        with open(p, "w") as fh:
            fh.write(synth.chart_text(sym, sessions))
        return p

    def trigger(self, sym, session, now_text, plan=None, decision=None, cfg=None):
        ch = entry.parse_chart(synth.chart_text(sym, [session]), sym)
        now = entry.parse_now(now_text)
        res = entry.evaluate(ch, now)
        self.assertEqual(res["status"], "triggered", res.get("reason"))
        doc = entry.entry_doc(res, now)
        return doc, record.record_trigger(doc, plan, decision, cfg or self.cfg, "yahoo", now, now_text,
                                          bars_label="offline", extra={"volume_x": res["trigger"]["volume_x"]},
                                          record_dir=self.rec)


class AppendOnly(unittest.TestCase):
    """P7: the two files are opened with mode "a" to write and "r" to read, nowhere else, by nothing else."""

    SOURCES = (os.path.join(ROOT, "mjonir", "ledger.py"), os.path.join(ROOT, "trader-record", "record.py"))

    def test_open_modes(self):
        modes = []
        for path in self.SOURCES:
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "open":
                    mode = node.args[1].value if len(node.args) > 1 else "r"
                    for kw in node.keywords:
                        if kw.arg == "mode":
                            mode = kw.value.value
                    modes.append((os.path.basename(path), mode))
        self.assertEqual(sorted(set(m for _, m in modes)), ["a", "r"])
        self.assertEqual([p for p, m in modes if m == "a"], ["ledger.py"])     # the one writer
        for path in self.SOURCES:
            with open(path, encoding="utf-8") as fh:
                src = re.sub(r'""".*?"""', "", fh.read(), flags=re.S)
            src = re.sub(r"#.*", "", src)
            for bad in ("os.replace", "os.rename", "truncate", "shutil", '"w"', "'w'", '"w+"', '"r+"', '"x"'):
                self.assertNotIn(bad, src, (path, bad))

    def test_only_the_ledger_names_the_files(self):
        for folder in os.listdir(ROOT):
            d = os.path.join(ROOT, folder)
            if not (folder.startswith("trader-") or folder == "mjonir") or not os.path.isdir(d):
                continue
            for f in os.listdir(d):
                if f.endswith(".py") and f != "ledger.py":
                    with open(os.path.join(d, f), encoding="utf-8") as fh:
                        src = fh.read()
                    code = re.sub(r'""".*?"""', "", src, flags=re.S)     # docstrings may name them
                    self.assertNotIn("triggers.jsonl", code, f)
                    self.assertNotIn("scores.jsonl", code, f)

    def test_python_3_8(self):
        for path in self.SOURCES:
            with open(path, encoding="utf-8") as fh:
                ast.parse(fh.read(), feature_version=(3, 8))


class Files(Base):
    def test_corrupt_and_cut_lines_name_the_line(self):
        os.makedirs(self.rec)
        with open(self.tp, "w") as fh:
            fh.write('{"id": "a", "kind": "trigger"}\n{"id": "b", "kind": "trigger"}\n{"id": "c", "ki\n')
        with self.assertRaises(L.RecordError) as cm:
            L.load(self.rec)
        self.assertIn("line 3 is not valid JSON", str(cm.exception))
        self.assertIn(self.tp, str(cm.exception))
        with open(self.tp, "w") as fh:
            fh.write('{"id": "a", "kind": "trigger"}\n{"id": "b"}')
        with self.assertRaises(L.RecordError) as cm:
            L.load(self.rec)
        self.assertIn("line 2 has no newline", str(cm.exception))
        with open(self.tp, "w") as fh:
            fh.write('{"id": "a"}\n[1, 2]\n')
        with self.assertRaises(L.RecordError) as cm:
            L.load(self.rec)
        self.assertIn("line 2 is not a record row", str(cm.exception))
        code, _, err = run(record, ["report", "--record-dir", self.rec])
        self.assertEqual(code, 1)
        self.assertIn("line 2 is not a record row", err)

    def test_one_score_line_per_id(self):
        L.append_rows(self.sp, [{"id": "x", "outcome": "stop"}, {"id": "x", "outcome": "target"}])
        with self.assertRaises(L.RecordError) as cm:
            L.load(self.rec)
        self.assertIn("scores x a second time", str(cm.exception))

    def test_absent_files_are_an_empty_book(self):
        b = L.load(self.rec)
        self.assertEqual((b["exists"], b["triggers"], b["scores"], b["as_of"]), (False, [], {}, None))


class AddOnce(Base):
    def test_a_trigger_is_appended_once(self):
        s = cents_session("2026-10-19", 1)
        doc, got = self.trigger("SYN", s, "2026-10-19 10:00")
        self.assertEqual(got["state"], "appended")
        row = got["row"]
        self.assertEqual(row["id"], L.trigger_id("SYN", "2026-10-19", "orb", "09:55", row["rule_hash"]))
        self.assertEqual((row["trigger"]["time"], row["trigger"]["bar_index"]), ("09:55", 4))
        self.assertEqual(row["plan"]["target_r"], 2.0)
        self.assertEqual(row["rule"]["stop_rule"], "or_mid")
        self.assertEqual(row["costs_basis"], "the plan's cost card")
        self.assertIsNone(row["decision"]["taken"])
        h = sha(self.tp)
        _, again = self.trigger("SYN", s, "2026-10-19 10:20")
        self.assertEqual(again["state"], "exists")
        self.assertEqual(sha(self.tp), h)

    def test_a_level_setup_without_a_plan_is_recorded_and_scored_no_data(self):
        s = cents_session("2026-10-19", 2)
        ch = entry.parse_chart(synth.chart_text("SYN", [s]), "SYN")
        now = entry.parse_now("2026-10-19 11:00")
        res = entry.evaluate(ch, now, setup="level", level=s[2]["h"])
        got = record.record_trigger(entry.entry_doc(res, now), None, None, self.cfg, "yahoo", now, record_dir=self.rec)
        self.assertEqual(got["state"], "appended")
        self.assertIsNone(got["row"]["plan"])
        self.assertIn("level setup has no opening-range stop to default to", got["row"]["plan_note"])
        out = record.score_day("2026-10-19", offline=self.chart_file("SYN", [s]),
                               now_utc=entry.parse_now("2026-10-19 16:30"), record_dir=self.rec, state_path=None)
        sc = L.load(self.rec)["scores"][got["id"]]
        self.assertEqual(sc["outcome"], "no_data")
        self.assertIn("no plan", out["lines"][0])

    def test_a_plan_for_another_day_is_not_used(self):
        s = cents_session("2026-10-19", 3)
        plan = {"symbol": "SYN", "date": "2026-10-20", "entry": 1.0, "stop": 0.5}
        _, got = self.trigger("SYN", s, "2026-10-19 10:00", plan=plan)
        self.assertIn("not this trigger: not used", got["row"]["notes"][0])
        self.assertIn("trader-exit defaults", got["row"]["plan"]["basis"])

    def test_the_cli_add(self):
        s = cents_session("2026-10-19", 4)
        ch = entry.parse_chart(synth.chart_text("SYN", [s]), "SYN")
        now = entry.parse_now("2026-10-19 10:00")
        e = os.path.join(self.d, "entry.json")
        with open(e, "w") as fh:
            json.dump(entry.entry_doc(entry.evaluate(ch, now), now), fh)
        code, out, err = run(record, ["add", "--from", e, "--skipped", "too extended", "--config", self.cfg,
                                      "--now", "2026-10-19 10:01"])
        self.assertEqual(code, 0, err)
        self.assertIn("Recorded SYN 2026-10-19 09:55", out)
        b = L.load(self.rec)
        self.assertEqual(L.decision_of(b, b["triggers"][0]), {"taken": False, "reason": "too extended",
                                                               "decided_at": "2026-10-19T14:01:00Z"})
        code, out, _ = run(record, ["add", "--from", e, "--skipped", "too extended", "--config", self.cfg])
        self.assertIn("already in", out)
        self.assertEqual(len(L.load(self.rec)["rows"]), 1)
        code, _, err = run(record, ["add", "--from", e, "--taken"])
        self.assertEqual(code, 1)
        self.assertIn("--fingerprint", err)


class ScoresLikeTheTimeMachine(Base):
    """score_day on a recorded trigger == the time machine's history_replay of the same plan on that session."""

    def check_day(self, date, seed, early=False, up=True):
        s = cents_session(date, seed, early=early)
        tt = "13:00" if early else "15:00"
        doc, got = self.trigger("SYN", s, "%s %s" % (date, tt))
        row = got["row"]
        out = record.score_day(date, offline=self.chart_file("SYN", [s]), draws=0,
                               now_utc=entry.parse_now("%s 16:30" % date), record_dir=self.rec, state_path=None)
        self.assertEqual(out["pending"], 0, out["lines"])
        sc = L.load(self.rec)["scores"][row["id"]]
        p = row["plan"]
        rule = {"setup": "orb", "or_minutes": 15, "stop_rule": "or_mid", "target_r": p["target_r"]}
        model = C.model_of(row["costs"])
        if early:
            h = tm.history_replay([(date, s)], rule, 76, "buy", model, "open", lasts={date: tm.early_last(15 * 60 + 55,
                                                                                                      False)},
                                  summary=False)
        else:
            last = (tm.parse_clock(p["flat_by"], "flat_by") - tm.OPEN_MIN) // 5 - 1
            h = tm.history_replay([(date, s)], rule, last, "buy", model, "open", summary=False)
        t = h["trades"][0]
        self.assertEqual((t["_bar"], t["stop"]), (p["entry_bar"], p["stop"]))
        self.assertAlmostEqual(t["_entry"], p["entry"], places=9)
        self.assertEqual(sc["outcome"], t["outcome"], (date, seed))
        self.assertAlmostEqual(sc["gross_r"], t["_gross"], places=5)
        self.assertAlmostEqual(sc["net_r"], t["_net"], places=5)
        self.assertEqual(sc["last_bar"], t["last_bar"])
        self.assertAlmostEqual(sc["cost_r"], t["cost_r"], places=4)
        return sc

    def test_full_sessions(self):
        seen = set()
        for seed in range(12):
            seen.add(self.check_day("2026-10-%02d" % (5 + seed % 5 + 7 * (seed // 5)), seed)["outcome"])
        self.assertGreaterEqual(len(seen), 2)

    def test_an_early_close_is_scored_to_bar_40(self):
        sc = self.check_day("2026-11-27", 5, early=True)
        self.assertEqual(sc["last_bar"], 40)
        self.assertEqual(record.last_bar("15:55", True), 40)
        self.assertEqual(record.last_bar("12:55", True), 40)
        self.assertEqual(record.last_bar("16:00", True), 41)
        self.assertEqual(record.last_bar("15:55", False), 76)
        self.assertEqual(record.last_bar(None, False), 77)
        for fb in (12 * 60 + 30, 15 * 60 + 55, 16 * 60):
            self.assertEqual(record.last_bar("%02d:%02d" % divmod(fb, 60), True), tm.early_last(fb, False))

    def test_the_entry_window(self):
        self.assertEqual(record.entry_until("15:30", False), 71)
        self.assertEqual(record.entry_until("15:30", True), 35)
        self.assertEqual(record.entry_until("12:00", True), 29)

    def test_a_spike_before_the_entry_moves_nothing(self):
        date = "2026-10-21"
        s = cents_session(date, 7)
        doc, got = self.trigger("SYN", s, date + " 15:00")
        spiked = [dict(b) for b in s]
        spiked[4]["h"] = spiked[4]["c"] + 50.0          # the trigger bar itself: not after it
        spiked[3]["h"] = spiked[3]["h"] + 50.0          # nor the bar before
        a = record.score_day(date, offline=self.chart_file("SYN", [spiked]), draws=0,
                             now_utc=entry.parse_now(date + " 16:30"), record_dir=self.rec, state_path=None)
        self.assertEqual(a["pending"], 0)
        sc = L.load(self.rec)["scores"][got["id"]]
        other = os.path.join(self.d, "plain")
        os.makedirs(other)
        record.record_trigger(doc, None, None, self.cfg, "yahoo", entry.parse_now(date + " 15:00"), record_dir=other)
        record.score_day(date, offline=self.chart_file("SYN", [s], "plain.json"), draws=0,
                         now_utc=entry.parse_now(date + " 16:30"), record_dir=other, state_path=None)
        plain = L.load(other)["scores"][got["id"]]
        for k in ("mfe_r", "mae_r", "outcome", "net_r", "exit_bar"):
            self.assertEqual(sc[k], plain[k], k)

    def test_bars_not_all_in_yet_are_not_scored(self):
        date = "2026-10-22"
        s = cents_session(date, 8)
        _, got = self.trigger("SYN", s, date + " 15:00")
        out = record.score_day(date, offline=self.chart_file("SYN", [s]), now_utc=entry.parse_now(date + " 14:00"),
                               record_dir=self.rec, state_path=None)
        self.assertEqual(out["pending"], 1)
        self.assertIn("unverified, not scored", out["lines"][0])
        self.assertFalse(os.path.exists(self.sp))


class Controls(Base):
    def test_one_control_in_the_window_seeded_by_identifiers_and_idempotent(self):
        date = "2026-10-23"
        s = cents_session(date, 9)
        _, got = self.trigger("SYN", s, date + " 15:00")
        f = self.chart_file("SYN", [s])
        out = record.score_day(date, offline=f, draws=1, now_utc=entry.parse_now(date + " 16:30"), record_dir=self.rec,
                               state_path=None)
        self.assertEqual(out["appended"], {"triggers": 1, "scores": 2})
        b = L.load(self.rec)
        (c,) = b["controls"]
        self.assertEqual(c["paired_id"], got["id"])
        self.assertEqual(c["id"], L.control_id(got["id"], 0, 19))
        self.assertEqual(c["control"]["seed"], "19:SYN:%s" % date)
        self.assertEqual(c["control"]["entry_until"], 71)
        self.assertTrue(3 <= c["control"]["bar_index"] <= 71)
        # the same draw as mjonir.control with the plan's window and the record's seed
        from mjonir import control as CT
        rng = CT.session_rng(19, "SYN", date)
        self.assertEqual(c["control"]["bar_index"], rng.choice(CT.eligible_bars(3, 76, 71)))
        self.assertEqual(b["scores"][c["id"]]["kind"], "control")
        h = (sha(self.tp), sha(self.sp))
        again = record.score_day(date, offline=f, draws=1, now_utc=entry.parse_now(date + " 16:31"),
                                 record_dir=self.rec, state_path=None)
        self.assertEqual(again["appended"], {"triggers": 0, "scores": 0})
        self.assertEqual((sha(self.tp), sha(self.sp)), h)
        code, out, _ = run(record, ["score", "--date", date, "--offline", f, "--now", date + " 16:32",
                                    "--record-dir", self.rec])
        self.assertEqual(code, 0)
        self.assertIn("already scored", out)
        self.assertEqual((sha(self.tp), sha(self.sp)), h)

    def test_a_late_window_keeps_controls_inside_it(self):
        date = "2026-10-26"
        s = cents_session(date, 10)
        _, got = self.trigger("SYN", s, date + " 15:00")
        b = L.load(self.rec)
        self.assertEqual(b["triggers"][0]["rule"]["no_entries_after"], "15:30")
        record.score_day(date, offline=self.chart_file("SYN", [s]), draws=5,
                         now_utc=entry.parse_now(date + " 16:30"), record_dir=self.rec, state_path=None)
        bars = [c["control"]["bar_index"] for c in L.load(self.rec)["controls"]]
        self.assertEqual(len(bars), 5)
        self.assertTrue(all(3 <= j <= 71 for j in bars), bars)


class Decisions(Base):
    def order(self, row, qty="10"):
        p = row["plan"]
        return {"symbol": "SYN", "side": "buy", "qty": qty, "type": "market", "time_in_force": "day",
                "order_class": "bracket", "take_profit_limit_price": "%.2f" % p["target"],
                "stop_loss_stop_price": "%.2f" % p["stop"],
                "plan": {"entry": p["entry"], "stop": p["stop"], "target": p["target"], "max_loss": 25.0,
                         "setup": "orb", "entry_time": p["entry_time"], "flat_by": p["flat_by"]}}

    def test_decline_through_ticket_appends_the_skipped_decision(self):
        date = "2026-10-27"
        s = cents_session(date, 11)
        doc, got = self.trigger("SYN", s, date + " 10:00")
        row = got["row"]
        orders = os.path.join(self.d, "orders.json")
        with open(orders, "w") as fh:
            json.dump({"orders": [self.order(row)]}, fh)
        e = os.path.join(self.d, "entry.json")
        with open(e, "w") as fh:
            json.dump(doc, fh)
        base = ["--orders", orders, "--config", self.cfg, "--risk", os.path.join(self.d, "risk.json"),
                "--state", os.path.join(self.d, "broker.json"), "--now", date + " 10:05", "--entry", e,
                "--plan", os.path.join(self.d, "none.json")]
        h = sha(self.tp)
        code, out, err = run(ticket, ["decline", "--index", "1", "--reply", "no, too late"] + base)
        self.assertEqual(code, 0, err)
        self.assertIn("Record: recorded the decision (skipped: no, too late)", out)
        b = L.load(self.rec)
        self.assertNotEqual(sha(self.tp), h)
        self.assertEqual(len(b["rows"]), 2)
        d = L.decision_of(b, b["triggers"][0])
        self.assertEqual((d["taken"], d["reason"], d["plan_matches_record"]), (False, "no, too late", True))
        code, out, _ = run(ticket, ["decline", "--index", "1", "--reply", "no, too late"] + base)
        self.assertIn("already in", out)
        self.assertEqual(len(L.load(self.rec)["rows"]), 2)
        code, out, _ = run(ticket, ["decline", "--index", "1", "--reply", "no", "--no-record"] + base)
        self.assertNotIn("Record:", out)
        self.assertEqual(len(L.load(self.rec)["rows"]), 2)

    def test_no_trigger_no_record(self):
        order = {"symbol": "ZZZ", "side": "buy", "qty": "1", "plan": {"entry_time": "10:15 AM", "setup": "orb"}}
        got = record.decide(order, {"taken": False, "reason": "no"}, "2026-10-27", entry.parse_now("2026-10-27 10:20"),
                            os.path.join(self.d, "none"), os.path.join(self.d, "none"), self.cfg, None, self.rec)
        self.assertEqual(got["state"], "skipped")
        self.assertIn("no trigger row for ZZZ 2026-10-27 10:15", got["message"])
        self.assertFalse(os.path.exists(self.tp))

    def test_taken_with_fills_scores_from_the_broker(self):
        date = "2026-10-28"
        s = cents_session(date, 12)
        doc, got = self.trigger("SYN", s, date + " 10:00")
        row = got["row"]
        order = self.order(row)
        fp = ticket.fingerprint(order)
        dec = {"taken": True, "reason": "approved", "risk_fingerprint": fp, "broker_fingerprint": fp,
               "risk_verdict": "PASS", "qty": 10.0, "max_loss_usd": 25.0}
        e = os.path.join(self.d, "entry.json")
        with open(e, "w") as fh:
            json.dump(doc, fh)
        out = record.decide(order, dec, date, entry.parse_now(date + " 10:05"), e, "/nonexistent", self.cfg, None,
                            self.rec)
        self.assertEqual(out["state"], "decided")
        state = os.path.join(self.d, "broker.json")
        p = row["plan"]
        with open(state, "w") as fh:
            json.dump({"orders": [
                {"date": date, "fingerprint": fp, "status": "approved", "symbol": "SYN"},
                {"date": date, "status": "filled", "symbol": "SYN", "side": "buy", "qty": "10", "price": p["entry"] + 0.02},
                {"date": date, "status": "filled", "symbol": "SYN", "side": "sell", "qty": "10", "price": p["entry"] + 1.02},
            ]}, fh)
        b0 = L.load(self.rec)
        self.assertEqual(L.realized(b0, date, date), {"realized_usd": 0.0, "open_usd": 25.0, "scored": 0, "open": 1,
                                                       "unknown": []})
        record.score_day(date, offline=self.chart_file("SYN", [s]), draws=1, now_utc=entry.parse_now(date + " 16:30"),
                         record_dir=self.rec, state_path=state)
        b = L.load(self.rec)
        sc = b["scores"][row["id"]]
        self.assertEqual(sc["fill_basis"], "broker")
        self.assertEqual(sc["broker"]["qty"], 10.0)
        self.assertAlmostEqual(sc["broker"]["net_usd"], 10.0 - 2.0, places=6)        # $1 a share, $1 a side
        self.assertAlmostEqual(sc["broker"]["net_r"], 8.0 / (10 * p["risk_per_share"]), places=5)
        self.assertEqual(L.realized(b, date, date)["realized_usd"], 8.0)
        self.assertIn(sc["outcome"], L.SCORED)          # the paper score is still the rule's
        rep = record.report_doc(b, dt.date(2026, 10, 28))
        self.assertEqual((rep["taken"]["n"], rep["taken"]["broker_basis"]), (1, 1))
        self.assertEqual(rep["paper"]["n"], 1)
        self.assertAlmostEqual(rep["taken"]["realized"]["mean"], sc["broker"]["net_r"])
        self.assertAlmostEqual(rep["paper"]["expectancy"]["mean"], sc["net_r"])

    def test_fills_missing_a_leg_stay_paper(self):
        date = "2026-10-29"
        s = cents_session(date, 13)
        doc, got = self.trigger("SYN", s, date + " 10:00", decision={"taken": True, "reason": "taken",
                                                                     "broker_fingerprint": "f00", "qty": 5})
        state = os.path.join(self.d, "broker.json")
        with open(state, "w") as fh:
            json.dump({"orders": [{"date": date, "fingerprint": "f00", "status": "approved"},
                                  {"date": date, "status": "filled", "symbol": "SYN", "side": "buy", "qty": "5",
                                   "price": 400}]}, fh)
        record.score_day(date, offline=self.chart_file("SYN", [s]), draws=0, now_utc=entry.parse_now(date + " 16:30"),
                         record_dir=self.rec, state_path=state)
        sc = L.load(self.rec)["scores"][got["id"]]
        self.assertEqual(sc["fill_basis"], "paper")
        self.assertIn("both legs are needed", sc["broker_note"])
        b = L.load(self.rec)
        self.assertAlmostEqual(L.realized(b, date, date)["realized_usd"],
                               round(sc["net_r"] * 5 * got["row"]["plan"]["risk_per_share"], 2))


class Streak(unittest.TestCase):
    def book(self, nets, taken=True):
        trig, scores = [], {}
        for i, r in enumerate(nets):
            tid = "t%d" % i
            trig.append({"id": tid, "kind": "trigger", "date": "2026-10-%02d" % (5 + i), "symbol": "X",
                         "trigger": {"time": "10:00"}, "plan": {"risk_per_share": 1.0},
                         "decision": {"taken": taken, "qty": 100, "max_loss_usd": 120.0}})
            if r is not None:
                scores[tid] = {"id": tid, "outcome": "stop" if r < 0 else "target", "net_r": r}
        return {"triggers": trig, "scores": scores, "decisions": {}}

    def test_the_streak(self):
        self.assertEqual(L.loss_streak(self.book([0.5, -1.0, -1.1, -0.2]), 3), "2026-10-08")
        self.assertIsNone(L.loss_streak(self.book([-1.0, 0.5, -1.1, -0.2]), 3))
        self.assertIsNone(L.loss_streak(self.book([-1.0, -1.0]), 3))
        self.assertIsNone(L.loss_streak(self.book([-1.0, -1.0, -1.0], taken=False), 3))
        self.assertEqual(L.loss_streak(self.book([-1.0, -1.0, -1.0, None]), 3), "2026-10-07")

    def test_realized(self):
        b = self.book([-1.0, 0.5, None])
        r = L.realized(b, "2026-10-05", "2026-10-07")
        self.assertEqual((r["realized_usd"], r["open_usd"], r["scored"], r["open"]), (-50.0, 120.0, 2, 1))
        self.assertEqual(L.realized(b, "2026-10-06", "2026-10-06")["realized_usd"], 50.0)


class Gate(unittest.TestCase):
    def ex(self, lo, hi, n=40):
        return {"n": n, "mean": (lo + hi) / 2, "lo": lo, "hi": hi}

    def dl(self, lo, hi, m=40):
        return {"n_sessions": m, "delta": (lo + hi) / 2, "lo": lo, "hi": hi}

    def test_three_outcomes(self):
        g = record.gate_of
        self.assertEqual(g(39, 200, "2026-01-01", self.ex(0.1, 0.3, 39), self.dl(0.1, 0.2), 40)["state"], "not_yet")
        self.assertIn("n 39 of the 40", g(39, 200, None, self.ex(0.1, 0.3, 39), self.dl(0.1, 0.2), 40)["text"])
        r = g(40, 179, "2026-01-01", self.ex(0.1, 0.3), self.dl(0.1, 0.2), 40)
        self.assertEqual(r["state"], "not_yet")
        self.assertIn("179 of the 180 days", r["text"])
        self.assertEqual(g(40, 180, "x", self.ex(0.1, 0.3), self.dl(0.1, 0.2), 40)["state"], "pass")
        self.assertEqual(g(40, 180, "x", self.ex(-0.3, -0.1), self.dl(0.1, 0.2), 40)["state"], "fail")
        self.assertEqual(g(40, 180, "x", self.ex(0.1, 0.3), self.dl(-0.3, -0.1), 40)["state"], "fail")
        # a control delta under its 40-session floor never fails the gate, and never passes it
        self.assertEqual(g(40, 180, "x", self.ex(0.1, 0.3), self.dl(-0.3, -0.1, 39), 40)["state"], "not_yet")
        self.assertEqual(g(40, 180, "x", self.ex(0.1, 0.3), self.dl(0.1, 0.3, 39), 40)["state"], "not_yet")
        st = g(40, 180, "x", self.ex(-0.1, 0.3), self.dl(0.1, 0.2), 40)
        self.assertEqual(st["state"], "not_yet")
        self.assertIn("is not wholly over 0", st["text"])
        self.assertEqual(g(40, 180, "x", self.ex(0.1, 0.3), self.dl(-0.1, 0.2), 40)["state"], "not_yet")
        self.assertEqual(g(0, 0, None, None, None, 40)["state"], "not_yet")
        for args in ((40, 180, "x", self.ex(0.1, 0.3), self.dl(0.1, 0.2), 40),
                     (40, 180, "x", self.ex(-0.3, -0.1), self.dl(-0.3, -0.2), 40),
                     (3, 2, "x", self.ex(-0.3, 0.1, 3), None, 40), (0, 0, None, None, None, 40)):
            self.assertEqual(S.banned_words(g(*args)["text"]), [])

    def test_every_report_ends_with_the_footer(self):
        d = tempfile.mkdtemp()
        try:
            for argv in (["report"], ["report", "--setup", "orb"], ["journal"]):
                code, out, _ = run(record, argv + ["--record-dir", d, "--now", "2026-11-02 17:00"])
                self.assertEqual(code, 0)
                self.assertEqual(out.rstrip().splitlines()[-1], record.FOOTER)
            code, out, _ = run(record, ["report", "--record-dir", d, "--json", "--now", "2026-11-02 17:00"])
            doc = json.loads(out)
            self.assertEqual((doc["gate"]["state"], doc["footer"]), ("not_yet", record.FOOTER))
            self.assertIn("no scored trigger yet", doc["gate"]["text"])
        finally:
            shutil.rmtree(d)


class Journal(unittest.TestCase):
    def test_blocks(self):
        rows = [({}, {"mae_r": -0.5, "mfe_r": 1.0}, r) for r in (1.0, 0.5)]
        b = record._block(S, rows)
        self.assertIsNone(b["profit_factor"])
        self.assertIn("profit factor n/a (no losing trade)", record._bline("taken", b))
        rows.append(({}, {"mae_r": -1.0, "mfe_r": 0.2}, -1.0))
        b = record._block(S, rows)
        self.assertAlmostEqual(b["profit_factor"], 1.5)
        self.assertEqual((b["wins"], b["losses"], b["largest_loss_r"]), (2, 1, -1.0))
        self.assertAlmostEqual(b["avg_winner_r"], 0.75)
        self.assertAlmostEqual(b["mae_mean_r"], -2.0 / 3)
        self.assertEqual(b["wilson"], list(S.wilson(2, 3)))


class EntryHook(Base):
    def test_check_records_once_and_no_record_records_nothing(self):
        cwd = os.getcwd()
        os.mkdir(os.path.join(self.d, "cwd"))
        os.chdir(os.path.join(self.d, "cwd"))
        try:
            code, out, err = run(entry, ["check", "TSLA", "--offline", TSLA, "--now", "2026-10-19 10:15"])
            self.assertEqual(code, 0)
            self.assertIn("record: recorded TSLA 2026-10-19 10:15", err)
            self.assertNotIn("record:", out)
            b = L.load(self.rec)
            (t,) = b["triggers"]
            self.assertEqual((t["trigger"]["price"], t["trigger"]["bar_index"], t["plan"]["target"], t["plan"]["stop"]),
                             (364.18, 8, 375.9, 358.32))
            self.assertEqual(t["source"]["bars"], "offline")
            h = sha(self.tp)
            code, _, err = run(entry, ["check", "TSLA", "--offline", TSLA, "--now", "2026-10-19 10:20"])
            self.assertIn("already in", err)
            code, _, err = run(entry, ["watch", "TSLA", "--offline", TSLA, "--now", "2026-10-19 09:50",
                                       "--out", "w.json"])
            self.assertEqual(code, 0)
            self.assertIn("already in", err)
            self.assertEqual(sha(self.tp), h)
            os.environ["TRADER_RECORD_DIR"] = os.path.join(self.d, "other")
            code, _, err = run(entry, ["check", "TSLA", "--offline", TSLA, "--now", "2026-10-19 10:15", "--no-record"])
            self.assertEqual((code, err), (0, ""))
            code, _, err = run(entry, ["check", "TSLA", "--offline", TSLA, "--now", "2026-10-19 10:12"])
            self.assertEqual((code, err), (1, ""))                  # waiting: nothing to record
            self.assertFalse(os.path.exists(os.path.join(self.d, "other")))
            self.assertFalse(os.path.exists("record"))
        finally:
            os.chdir(cwd)

    def test_a_plan_given_to_entry_is_the_plan_recorded(self):
        plan = os.path.join(FIX, "trader-budget", "plan-tsla.json")
        code, _, err = run(entry, ["check", "TSLA", "--offline", TSLA, "--now", "2026-10-19 10:15", "--plan", plan,
                                   "--config", self.cfg])
        self.assertEqual(code, 0, err)
        (t,) = L.load(self.rec)["triggers"]
        self.assertEqual((t["plan"]["target"], t["plan"]["target_r"], t["plan"]["basis"]), (370.04, 1.0, "the plan file"))
        # the plan file has no cost card: the time machine's default card, ADV unverified
        self.assertIn("default card", t["costs_basis"])
        cfg = dict(LIGHT)
        with open(plan) as fh:
            tm_card = tm.cost_card_for(tm.normalize_plan(json.load(fh)), "auto", cfg)
        self.assertEqual(t["costs"]["cost_r"], tm_card["cost_r"])
        self.assertEqual(t["costs"]["per_side_bps"], tm_card["per_side_bps"])


class Clock(unittest.TestCase):
    def test_today_agrees_with_the_one_clock_across_dst(self):
        for text in ("2026-03-08 01:59", "2026-03-08 03:00", "2026-11-01 01:30", "2026-11-01 23:30",
                     "2026-11-02T04:59:00Z", "2026-11-02T05:00:00Z", "2026-07-01T03:59:00Z"):
            self.assertEqual(record.today_et(record.parse_now(text)), K.today_et(K.parse_now(text)), text)


if __name__ == "__main__":
    unittest.main()
