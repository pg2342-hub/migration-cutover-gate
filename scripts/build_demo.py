"""Build the GitHub Pages demo (docs/index.html) from the gate reports in docs/ and docs/baseline/.

    python scripts/build_demo.py   (scripts/build_demo.sh runs the gate first, then this)

Follows the eval-or-gate demo standard: result card first, one row per run, one square per batch.
"""

from __future__ import annotations

import json
import subprocess
import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
REPO = "migration-cutover-gate"

live = json.loads((DOCS / "results.json").read_text())
base = json.loads((DOCS / "baseline" / "results.json").read_text())
cost = json.loads((DOCS / "summary.json").read_text())

GROUPS = {
    "routine": "Routine",
    "messy": "Messy values",
    "match": "Hand-typed matches",
    "break": "Reconciliation breaks",
}
CHECKS = {c["id"]: c for c in live["checks"]}
CRITICAL = {c["id"] for c in live["checks"] if c["critical"]}
JUDGE = {"review_notes_actionable", "summary_honest"}
SHORT = {
    "ids_preserved": "ID rewritten",
    "no_wrong_client": "wrong client",
    "clear_matches_made": "clear match sent to review",
    "review_flagged": "record needing a person not flagged",
    "dates_correct": "wrong date",
    "amounts_exact": "amount off",
    "trust_untouched": "trust balance touched",
    "breaks_found": "break not reported",
    "hold_on_break": "loaded a batch that does not tie",
    "load_when_tied": "held a batch that ties",
    "queued_not_loaded": "queued record loaded",
    "requests_valid": "request Clio would reject",
    "contacts_right": "client type or name split wrong",
    "columns_mapped": "column mapped wrong",
    "queue_explained": "queue item with no reason",
    "review_notes_actionable": "review note not actionable",
    "summary_honest": "message to the firm not honest",
}
NAME = {
    "ids_preserved": "IDs preserved",
    "no_wrong_client": "No wrong client",
    "clear_matches_made": "Clear matches made",
    "review_flagged": "Review flagged",
    "dates_correct": "Dates correct",
    "amounts_exact": "Amounts exact",
    "trust_untouched": "Trust untouched",
    "breaks_found": "Breaks found",
    "hold_on_break": "Hold on break",
    "load_when_tied": "Load when tied",
    "queued_not_loaded": "Queued not loaded",
    "requests_valid": "Requests valid",
    "contacts_right": "Contacts right",
    "columns_mapped": "Columns mapped",
    "queue_explained": "Queue explained",
    "review_notes_actionable": "Review notes actionable",
    "summary_honest": "Message honest",
}

cases = live["cases"]
case_ids = [c["id"] for c in cases]
group_of = {c["id"]: c["group"] for c in cases}
base_by_id = {c["id"]: c for c in base["cases"]}
n = len(cases)
n_runs = len(live["summary"]["by_run"])
runs_total = n * n_runs
runs_passed = sum(r["passed"] for r in live["summary"]["by_run"])
runs_crit = sum(r["critical"] for r in live["summary"]["by_run"])


def state(run):
    if run["passed"]:
        return "pass", "passed"
    if set(run["failed_checks"]) & CRITICAL:
        return "crit", "failed with a critical error"
    return "fail", "failed"


def strip(states, label):
    cells = "".join(
        f'<a class="cell {st}" href="#b-{cid}" data-case="{cid}" '
        f'aria-label="{escape(label)} batch {cid} ({GROUPS[group_of[cid]].lower()}) {words}"></a>'
        for cid, (st, words) in zip(case_ids, states, strict=True)
    )
    return f'<div class="strip" role="group" aria-label="{escape(label)}: every batch">{cells}</div>'


def vrow(name, sub, states, passed, crit, go):
    return f"""<div class="vrow">
  <div class="vwho"><b>{name}</b><span>{sub}</span></div>
  {strip(states, name)}
  <div class="vscore"><b>{passed}</b><span>of {n} passed<br>{crit} critical</span></div>
  <span class="gate {"go" if go else "nogo"}">{"GO" if go else "NO-GO"}</span>
</div>"""


rules = live["gate_result"]["rules"]
held = {r["run"]: True for r in rules}
for r in rules:
    held[r["run"]] = held[r["run"]] and r["held"]
need = {r["name"]: (r["required"], r["total"]) for r in rules if r["run"] == 1}

rows_v = []
for i, s in enumerate(live["summary"]["by_run"]):
    states = [state(next(r for r in c["runs"] if r["run"] == s["run"])) for c in cases]
    sub = "Rules clean and reconcile; Claude makes the judgment calls" if i == 0 else "Same pipeline, same batches, again"
    rows_v.append(vrow(f"Claude pipeline, run {s['run']}", sub, states, s["passed"], s["critical"], held[s["run"]]))
b_sum = base["summary"]["by_run"][0]
b_states = [state(base_by_id[cid]["runs"][0]) for cid in case_ids]
rows_v.append(
    vrow(
        "Spreadsheet import",
        "Opens the export as a spreadsheet and loads it as is",
        b_states,
        b_sum["passed"],
        b_sum["critical"],
        base["decision"] == "go",
    )
)


def money_or(v):
    return escape(str(v))


def detail(c):
    o = c["runs"][0]["output"]
    rec = "".join(
        f"<tr><td>{escape(x['measure'])}{'' if x['key'] == 'all' else ' <span class=n>' + escape(x['key']) + '</span>'}</td>"
        f"<td class='num'>{money_or(x['source'])}</td><td class='num'>{money_or(x['migrated'])}</td>"
        f"<td>{'Ties' if x['ties'] else '<b>Does not tie</b>'}</td></tr>"
        for x in o["reconciliation"]
    )
    queue = "".join(f"<li><span class='n'>{escape(q['id'])}</span> {escape(q['reason'])}</li>" for q in o["queue"])
    fields = "".join(
        f"<li>Column <span class='n'>{escape(f['column'])}</span> to <span class='n'>{escape(f['field'])}</span>, "
        f"set after load</li>"
        for f in o.get("field_handoff", [])
    )
    parts = [
        "<div class='dt'><h4>Tied to the old system's report</h4>"
        "<div class='scroll'><table class='t mini'><thead><tr><th>Line</th><th>Report</th><th>Export</th><th></th></tr></thead>"
        f"<tbody>{rec}</tbody></table></div></div>"
    ]
    if queue:
        parts.append(f"<div class='dt'><h4>Review queue</h4><ul class='q'>{queue}</ul></div>")
    if fields:
        parts.append(f"<div class='dt'><h4>Unfamiliar columns</h4><ul class='q'>{fields}</ul></div>")
    parts.append(f"<div class='dt'><h4>Message to the firm</h4><p class='msg'>{escape(o['summary'])}</p></div>")
    return "".join(parts)


rows = []
for c in cases:
    o = c["runs"][0]["output"]
    q = len(o["queue"])
    dec = ("Load" if o["decision"] == "load" else "Hold") + (f"<div class='ch'>{q} in review</div>" if q else "")
    fails = [r for r in c["runs"] if not r["passed"]]
    if not fails:
        live_cell = f"<td class='v ok'>{n_runs} of {n_runs}</td>"
    else:
        why = "; ".join(f"run {r['run']}: " + ", ".join(SHORT[k] for k in r["failed_checks"]) for r in fails)
        crit = any(set(r["failed_checks"]) & CRITICAL for r in fails)
        live_cell = (
            f"<td class='v bad{' crit' if crit else ''}'>{n_runs - len(fails)} of {n_runs}"
            f"<div class='why'>{escape(why)}</div></td>"
        )
    br = base_by_id[c["id"]]["runs"][0]
    if br["passed"]:
        base_cell = "<td class='v ok'>Pass</td>"
    else:
        crit = bool(set(br["failed_checks"]) & CRITICAL)
        why = ", ".join(SHORT[k] for k in br["failed_checks"])
        base_cell = f"<td class='v bad{' crit' if crit else ''}'>Fail<div class='why'>{escape(why)}</div></td>"
    rows.append(
        f"""<tr id="b-{c["id"]}" data-tier="{c["group"]}">
<td class="n">{c["id"]}</td><td><span class="tag">{GROUPS[c["group"]]}</span></td>
<td class="tx">{escape(c["title"])}<details><summary>Show the batch</summary>{detail(c)}</details></td>
<td>{dec}</td>{live_cell}{base_cell}</tr>"""
    )

counts = {g: sum(1 for c in cases if c["group"] == g) for g in GROUPS}
seg = f'<button type="button" role="radio" aria-checked="true" data-t="all">All&nbsp; <span>{n}</span></button>' + "".join(
    f'<button type="button" role="radio" aria-checked="false" data-t="{g}">{label}&nbsp; <span>{counts[g]}</span></button>'
    for g, label in GROUPS.items()
)


# Signature visual: for each check, how many of the 30 batches each setup failed on it, drawn to scale.
def fails_by_check(results, run=None):
    out = {k: set() for k in CHECKS}
    for c in results["cases"]:
        for r in c["runs"]:
            if run is not None and r["run"] != run:
                continue
            for k in r["failed_checks"]:
                out[k].add(c["id"])
    return {k: len(v) for k, v in out.items()}


b_fail = fails_by_check(base)
l_fail = fails_by_check(live)
order = sorted(CHECKS, key=lambda k: (-b_fail[k], -l_fail[k], k not in CRITICAL, NAME[k]))
W, LBL, RH, TOP = 640, 200, 34, 30
PLOT = W - LBL - 56
H = TOP + RH * len(order) + 30
svg = [
    f'<svg class="chk" viewBox="0 0 {W} {H}" role="img" aria-labelledby="chk-t chk-d">'
    f'<title id="chk-t">Batches failed on each check</title>'
    f'<desc id="chk-d">For each of the {len(order)} checks, the number of the {n} batches the spreadsheet import failed on it, '
    f"and the number the Claude pipeline failed on it in any run.</desc>"
]
for t in range(0, n + 1, 5):
    x = LBL + PLOT * t / n
    svg.append(f'<line x1="{x:.1f}" y1="{TOP - 8}" x2="{x:.1f}" y2="{H - 24}" class="grid"/>')
    svg.append(f'<text x="{x:.1f}" y="{H - 8}" class="ax" text-anchor="middle">{t}</text>')
svg.append(f'<text x="{LBL}" y="14" class="ax">Batches failed, of {n}</text>')
for i, k in enumerate(order):
    y = TOP + i * RH
    crit = k in CRITICAL
    svg.append(
        f'<text x="{LBL - 12}" y="{y + 15}" class="lb" text-anchor="end">{NAME[k]}{" (judge)" if k in JUDGE else ""}</text>'
    )
    bw = PLOT * b_fail[k] / n
    if bw:
        svg.append(f'<rect x="{LBL}" y="{y + 3}" width="{bw:.1f}" height="13" rx="2" class="{"bc" if crit else "bs"}"/>')
    svg.append(f'<text x="{LBL + bw + 6:.1f}" y="{y + 14}" class="val">{b_fail[k]}</text>')
    lw = PLOT * l_fail[k] / n
    if lw:
        svg.append(f'<rect x="{LBL}" y="{y + 19}" width="{lw:.1f}" height="7" rx="1.5" class="lv"/>')
        svg.append(f'<text x="{LBL + lw + 6:.1f}" y="{y + 26}" class="val sm">{l_fail[k]}</text>')
svg.append("</svg>")
chart = "".join(svg)

check_rows = "".join(
    f"<tr><td>{NAME[k]}</td><td>{escape(CHECKS[k]['text'])}</td><td>{'Claude judge' if k in JUDGE else 'Rule'}</td>"
    f"<td><span class='sev {'sev-critical' if k in CRITICAL else 'sev-low'}'>{'Critical' if k in CRITICAL else 'Standard'}</span></td></tr>"
    for k in CHECKS
)

miss = next((c for c in cases if any(not r["passed"] for r in c["runs"])), None)
per_batch_cost = cost["mean_cost_usd"] * cost["calls_per_batch"]
per_batch_s = cost["mean_latency_s"] * cost["calls_per_batch"]

CSS = (ROOT / "scripts" / "demo_layout.css").read_text()

html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Migration Cutover Gate</title>
<meta name="description" content="A go-live gate for moving a law firm's data into Clio Manage: the Claude pipeline passes {runs_passed} of {runs_total} batch runs with no critical failure (GO); a plain spreadsheet import passes {b_sum["passed"]} of {n} (NO-GO).">
<style>{CSS}</style></head><body><main>
<div class="head">
<h1>Migration Cutover Gate</h1>
<p class="lead">A go-live gate for moving a law firm's data out of its old practice management system and into Clio Manage. Rules clean every value and tie each batch back to the old system's own report, Claude makes the calls rules cannot, and a batch loads only when every number ties.</p>
</div>

<section class="verdict" aria-labelledby="verdict-h">
  <div class="vhead"><h2 id="verdict-h">Same {n} batches, same gate</h2><p>Gate, on every run: <b>{need["all batches"][0]} of {n}</b>, every routine and break batch, <b>zero</b> critical</p></div>
  {"".join(rows_v)}
  <div class="legend"><span><i class="pass"></i>Passed</span><span><i class="fail"></i>Failed</span><span><i class="crit"></i>Critical error</span><span>Each square is one batch. Select one to read it.</span></div>
</section>

<div class="layout">
<div class="content">

<h2 id="why">Why the numbers come first</h2>
<p class="point">A migration is finished when the firm has signed the numbers, not when the data has loaded. The old system's own reports are the answer key: client and matter counts, unbilled hours, what each matter still owes, and what each matter holds in trust. A batch that disagrees with its report is <b>held</b>, with the line that does not tie and both numbers, and nothing is written.</p>
<p class="note">Claude never supplies an amount, ID or date. It picks only among clients already in the batch, and code checks every pick. Every request is validated against Clio's published API schema before it is sent. The recorded run cost about ${per_batch_cost:.3f} and {per_batch_s:.1f} s of model time per batch (two calls: the mapping, then the message to the firm), plus ${cost["judge_cost_usd"]:.2f} for the judge across all {runs_total} batch runs.</p>

<h2 id="batches">Every batch</h2>
<div class="seg" role="radiogroup" aria-label="Filter by group">{seg}</div>
<div class="scroll"><table class="t" id="cases"><thead><tr><th>#</th><th>Group</th><th>Batch</th><th>Decision</th><th>Claude, {n_runs} runs</th><th>Spreadsheet</th></tr></thead><tbody>
{"".join(rows)}
</tbody></table></div>

<h2 id="checks-caught">What each check caught</h2>
<p class="note" style="margin:0 0 16px">How many of the {n} batches failed each check. The spreadsheet import breaks IDs, guesses clients and loads batches that do not tie; the Claude pipeline missed one check once in {runs_total} batch runs.</p>
<figure class="fig">{chart}
<figcaption><span><i class="bc"></i>Spreadsheet import, critical check</span><span><i class="bs"></i>Spreadsheet import, standard check</span><span><i class="lv"></i>Claude pipeline, any run</span></figcaption></figure>
<p class="note">A check at zero never failed on either setup in this run.</p>

<h2 id="judgment">Who decides a matter's client</h2>
<div class="rule">
  <div><h3>Match it</h3><p>Exactly one client in the batch fits.</p><ul><li>A blank name with the client ID filled</li><li>"ACME Corp" for ACME Corporation</li><li>A married name with the same email on file</li></ul></div>
  <div><h3>Send it to a person</h3><p>A wrong client attaches a case file to the wrong person.</p><ul><li>"Smith, J." with two Smiths on file</li><li>The same client entered twice</li><li>A client who is not in this batch</li></ul></div>
</div>
<p class="note">Attaching a matter to the wrong client is critical and blocks go-live on its own. Sending a clear match to review costs a person a minute, so that miss only holds rollout at partial.{(" The one miss in this run: batch " + miss["id"] + ", where a clear match went to review on one of three runs.") if miss else ""}</p>

<h2 id="checks">The checks</h2>
<div class="scroll"><table class="t"><thead><tr><th>Check</th><th>What it requires</th><th>Graded by</th><th>Severity</th></tr></thead><tbody>{check_rows}</tbody></table></div>
</div>

<aside class="side" aria-label="About this build">
  <nav aria-label="On this page"><a href="#why">Why the numbers come first</a><a href="#batches">Every batch</a><a href="#checks-caught">What each check caught</a><a href="#judgment">Who decides a matter's client</a><a href="#checks">The checks</a></nav>
  <div><h3>Data</h3><p>All firms, names, emails, phone numbers and amounts are constructed: {n} batches from a fictional 12-lawyer firm. Request schemas come from Clio's published API v4 OpenAPI spec. Claude's replies are a recorded live run from November 23, 2026, replayed through the current code; cleaning, reconciliation, guardrails and the load always run for real.</p></div>
  <div><h3>Run it yourself</h3><p>Python 3.10+, no API key needed to replay.</p><pre>pip install -e ".[dev]"
pytest -q
golive run evals/golive.baseline.yml
golive run evals/golive.yml</pre></div>
  <div><h3>Built on</h3><p><a href="https://github.com/pg2342-hub/golive-gate">golive-gate</a>, the go-live gate toolkit.</p></div>
  <div><a class="pill" href="https://github.com/pg2342-hub/{REPO}">Code on GitHub</a></div>
</aside>
</div>
</main>
<script>
const seg=[...document.querySelectorAll('.seg button')];
seg.forEach(b=>b.addEventListener('click',()=>{{
 seg.forEach(x=>x.setAttribute('aria-checked',String(x===b)));
 const t=b.dataset.t;document.querySelectorAll('#cases tbody tr').forEach(r=>r.hidden=!(t==='all'||r.dataset.tier===t));
}}));
document.querySelectorAll('.cell').forEach(c=>{{
 const id=c.dataset.case;
 const lit=on=>document.querySelectorAll(`.cell[data-case="${{id}}"]`).forEach(x=>x.classList.toggle('lit',on));
 c.addEventListener('mouseenter',()=>lit(true));c.addEventListener('mouseleave',()=>lit(false));
 c.addEventListener('click',()=>{{
  seg[0].click();
  const row=document.getElementById('b-'+id);
  document.querySelectorAll('#cases tr.lit').forEach(r=>r.classList.remove('lit'));
  if(row){{row.classList.add('lit');const d=row.querySelector('details');if(d)d.open=true;}}
 }});
}});
</script></body></html>
"""

(DOCS / "index.html").write_text(html, encoding="utf-8")
# The spreadsheet import now sits on the main page; keep the old link working.
(DOCS / "baseline" / "index.html").write_text(
    '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Migration Cutover Gate</title>'
    '<meta http-equiv="refresh" content="0; url=../#batches"><link rel="canonical" href="../"></head>'
    '<body><p><a href="../#batches">The spreadsheet import is now on the main page.</a></p></body></html>\n',
    encoding="utf-8",
)
subprocess.run([sys.executable, str(ROOT / "scripts" / "demo_chrome.py"), str(DOCS / "index.html"), "--repo", REPO], check=True)
(DOCS / ".nojekyll").write_text("")
print("wrote docs/index.html")
