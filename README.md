# migration-cutover-gate

[![CI](https://github.com/pg2342-hub/migration-cutover-gate/actions/workflows/ci.yml/badge.svg)](https://github.com/pg2342-hub/migration-cutover-gate/actions/workflows/ci.yml)

Demo page: https://pg2342-hub.github.io/migration-cutover-gate/ (every batch, check and judge verdict from the latest recorded live run; no install needed)

A go-live gate for moving a law firm's data out of its old practice management system and into Clio Manage. Each batch of the old system's export (clients, matters, unbilled time, billed invoices, trust balances) is cleaned by rules, tied back to the totals the old system prints on its own reports, mapped by Claude where a rule cannot decide, and loaded only when every number ties. The result for each batch is **load or hold**, a review queue with a plain reason for each record a person must check, and a message to the firm. 30 constructed batches and a gate decide whether the pipeline is ready to run a real migration: **go, partial or no-go**.

Built on [golive-gate](https://github.com/pg2342-hub/golive-gate).

## Why the numbers come first

A migration is finished when the customer has signed the numbers, not when the data has loaded. The old system's own reports are the answer key: client and matter counts, unbilled hours, what each matter still owes, and what each matter holds in trust. A batch whose export disagrees with its report (a missing invoice, a dropped time entry, a trust balance a cent off) is held with the line that does not tie, both numbers, and nothing written. Clio's standard migration does not bring over billed history, so each matter's old invoices go into one reconciled ledger note, and the balance owed is the figure the firm signs.

## What is in it

| Part | File |
|---|---|
| Rule cleaning: IDs stay text (leading zeros, 16-digit numbers), five date forms incl. Excel serial days, money to the cent incl. bracketed credits, h:mm hours, phone numbers; values a spreadsheet already damaged (`4-Mar`, `4.01289E+15`) go to review | `cutover/clean.py` |
| Reconciliation against the old system's report, in exact decimals | `cutover/reconcile.py` |
| The Claude steps, two calls per batch with structured output. First: person or company and the name split, which client a hand-typed matter belongs to, duplicate client rows, where an unfamiliar column goes in Clio, a review note per flagged record. Then, after code has applied the guardrails and decided load or hold: the message to the firm, written from that final state so it never guesses what the guardrails did. Claude never supplies an amount, ID or date: it picks only among client IDs already in the batch, and code checks every pick | `cutover/mapper.py` |
| Guardrails and the decision: uncertain or out-of-batch matches go to review, a possible duplicate holds both rows and their matters, the batch holds on any break, queued records never load, trust balances are never written | `cutover/pipeline.py` |
| Load to Clio Manage API v4: contacts, matters, time entries (quantity in seconds) and ledger notes. Every request is validated against the request schemas in Clio's published OpenAPI spec before it is sent, and a field name the spec does not list is rejected | `cutover/clio.py`, `cutover/clio_openapi_subset.json` |
| 30 constructed batches in four groups: routine (10), messy values (8), hand-typed client matches (6), reconciliation breaks (6) | `scripts/make_cases.py` → `evals/cases.yml` |
| 15 rule checks, 7 critical (rewritten ID, wrong client, wrong amount, touched trust balance, loaded break, queued record loaded, request Clio would reject or silently drop) | `evals/checks.py` |
| 2 Claude judge checks: is each review note something a non-technical ops lead can act on, and is the message to the firm honest about the decision and the numbers (critical) | `evals/judge_checks.py` |
| The gate, on each of 3 runs: 28 of 30 batches, every routine and break batch, 7 of 8 messy, 0 critical failures; under 5 of 6 hand-typed matches holds rollout at partial | `evals/gate.yml` |
| A plain spreadsheet import the gate must block | `cutover/baseline.py` |

## The judgment call: who decides a matter's client

The old system lets staff type the client's name on a matter by hand, so "Smith, J." can mean two different clients. Claude picks the client only when exactly one fits and marks it certain; otherwise the matter waits in the review queue with a note saying which clients could fit and what the firm needs to answer. Code then refuses any match to a client outside the batch. Attaching a case file to the wrong client is a critical failure that blocks go-live on its own; sending a clear match to review only costs a person a minute, so that miss holds rollout at partial instead.

## Run it

```
pip install -e ".[dev]"
pytest -q                                       # 76 tests, no network
golive run evals/golive.baseline.yml            # spreadsheet import: NO-GO
golive run evals/golive.yml                     # replays the recorded Claude run: no key needed
GOLIVE_LIVE=1 ANTHROPIC_API_KEY=... golive run evals/golive.live.yml   # a fresh live run, recorded to recordings/
CLIO_ACCESS_TOKEN=... python scripts/load_to_clio.py r01               # load one batch into a Clio trial account
```

`load_to_clio.py` sends the same validated requests to a real Clio Manage account (use a trial or developer account). Without a token, the pipeline loads into `FakeClio`, which validates every request against Clio's published schema and returns ids the way the API does.

## How the live run is recorded

The mapping step and the judge call Claude (`claude-opus-5-5`, low effort, structured output for the mapping step). A live run writes every reply to `recordings/`, with cost and latency per call. CI and the demo page replay those replies through the current code (cleaning, reconciliation, guardrails and the Clio load always run for real), so they need no API key and give the same result every time; `tests/test_pipeline.py` checks that a replay makes no API calls and reaches the same decision. The **Record a live run** workflow (Actions tab, needs the `ANTHROPIC_API_KEY` secret) refreshes the recording and the demo page.

## CI

Every push runs ruff, the tests on Python 3.10 and 3.12, the spreadsheet import (which must come out no-go), and the gate on the recorded run, which fails the build on no-go and writes the report to the job summary. The gate job runs only once a live run has been recorded to `recordings/mapper.jsonl`; before that, CI checks the code and the spreadsheet import only.

All firms, names, emails, phone numbers and amounts are constructed.
