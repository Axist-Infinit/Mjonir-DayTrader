---
name: trader-record
description: >-
  Forward Record. NOT BUILT YET (chunk 3 of the Mjonir plan): there is no
  script in this folder, so nothing here can be run today. When built it
  keeps the append-only forward record of every opening-range trigger the
  entry timer sees, taken or skipped, scores each one after the close from
  that session's 5-minute bars net of costs, pairs it with a random-entry
  control, and prints the money gate. Until then, say it is not built and
  point the user to docs/RUNBOOK.md. Use when the user asks about "the
  record", "the gate", "score today's triggers", "how many trades so far",
  "is it time to trade money", or "show my journal".
argument-hint: "[report | journal]"
---

# trader-record

**Status: not built yet. See docs/RUNBOOK.md.** There is no `record.py` in
this folder. Do not try to run any command named below; tell the user the
record arrives in chunk 3 of the plan and show them docs/RUNBOOK.md.

What it will do: keep the forward record, the paper account that decides
whether this pack ever trades money. Every trigger the entry timer sees is
written once to `record/triggers.jsonl`, whether the owner takes it or skips
it, together with a matched random-entry control row. After the close each
trigger is scored once, from bars strictly after the trigger bar, into
`record/scores.jsonl`: target, stop or close, gross and net R, MFE and MAE.
The report then prints counts, net expectancy with its interval, the
decided rate against net break-even, the delta against the control, the
days elapsed, and the money gate. Both files are tracked in git and are
append-only: a line, once written, is never rewritten.

## Planned commands (not present yet)

| command | what it will do |
| --- | --- |
| `add` | append one trigger row (taken or skipped, with the reason) |
| `score --date D` | score that session's triggers and their control rows, once |
| `report` | counts, net expectancy and interval, control delta, the gate |
| `journal` | realized R, win rate with Wilson, MAE/MFE, by setup and month |

## The money gate (three outcomes, never two)

- **PASSES** when at least 40 trades are resolved, at least 180 days have
  passed, the net expectancy interval sits above zero, and the delta against
  the random-entry control sits above zero.
- **FAILS** when the count and the days are met and either interval sits
  below zero.
- **NOT YET** otherwise, with the reason (`n`, `days`, or the interval).

Every report ends with: "Money only past the gate; the gate is not a
forecast."

## Rules

- Append-only. `record/triggers.jsonl` is opened with mode `a` only.
- Python computes every number; this skill narrates the JSON keys it prints.
- Every check has three outcomes: pass, fail, unverified.
- No sentence promises a profit. A past sample is not a forward result.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Paper first: until the gate passes, the record is the paper account and the
  $100,000 notional is a unit of account, not an instruction to trade it.
- Nothing in this pack places an order. In this fork every order is typed by
  the owner at the broker by hand, and only after trader-risk passed that
  exact order and the owner said yes to it.
- No options, margin, short selling or leverage.
