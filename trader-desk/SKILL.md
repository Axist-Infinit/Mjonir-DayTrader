---
name: trader-desk
description: >-
  Trading Desk. NOT BUILT YET (chunk 4 of the Mjonir plan): there is no
  script in this folder, so nothing here can be run today. When built it is
  the daily runbook as one slash command: weekly prep, premarket scan, the
  09:35 relative-volume list, the opening-range scan, arming one name,
  managing the open trade, and the 16:30 close that scores the forward
  record and prints the money gate, each step with a pass, fail or
  unverified state. Until then, say it is not built and point the user to
  docs/RUNBOOK.md. Use when the user says "run the desk", "premarket",
  "open the desk", "arm TSLA", "close the day", or "what is my routine".
argument-hint: "[weekly | premarket | open | arm SYM | manage | close | review]"
---

# trader-desk

**Status: not built yet. See docs/RUNBOOK.md.** There is no `desk.py` in
this folder. Do not try to run any command named below; tell the user the
desk arrives in chunk 4 of the plan and walk them through docs/RUNBOOK.md
by hand with the skills that exist.

What it will do: run the day in the order docs/RUNBOOK.md lays out, from
the repo root, with `--source massive` on every call. Each subcommand chains
the existing skills and prints one line per step with its state (pass, fail
or unverified), so a missing input reads as unverified and never as a quiet
zero. On a trigger it builds the exit plan, the time machine replay, the
size and the risk check, then prints a human ticket for the owner to type at
E*TRADE, and appends the trigger to the forward record whether or not the
owner takes it. The close scores the record, prints the report and the gate,
and commits `record/`.

## Planned subcommands (not present yet)

| subcommand | when (ET) | what it will chain |
| --- | --- | --- |
| `weekly` | Sunday evening | calendar, universe rebuild, store status |
| `premarket` | 08:00 to 08:30 | daily bundle, daily scan, news, facts this week |
| `open` | 09:35, 09:45 to 10:15 | RVOL top 20, then the opening-range scan |
| `arm SYM` | on the pick | entry watch, exit plan, replay, size, risk, ticket, record |
| `manage` | while open | alerts from the plan, flat-by reminder |
| `close` | 16:30 | score the record, report, gate, commit `record/` |
| `review` | weekly | journal |

Each subcommand is a one-shot, so `/loop` can repeat it during the session.

## Rules

- Always run from the repo root: every script resolves `trader/` from the cwd.
- Every time printed is New York time from the scripts; the box clock is Mountain.
- Python computes every number; this skill narrates the JSON keys it prints.
- One name per day unless the owner says otherwise. No adds, no averaging
  down, no chasing past the risk check's limit.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- The desk never places an order. It prints a ticket; the owner types it at
  E*TRADE by hand, and only after trader-risk passed that exact order and the
  owner said yes to it.
- Paper first: money only after the forward record's gate passes, and the
  gate is not a forecast.
- No options, margin, short selling or leverage.
