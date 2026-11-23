#!/usr/bin/env bash
# Rebuild the GitHub Pages demo in docs/ from the recorded live run (no API key needed).
set -euo pipefail
cd "$(dirname "$0")/.."
golive run evals/golive.yml --out docs >/dev/null || true
golive run evals/golive.baseline.yml --out docs/baseline >/dev/null || true
python scripts/summarize.py > docs/summary.json
rm -f docs/report.md docs/baseline/report.md
python - <<'PY'
import json
from pathlib import Path

s = json.loads(Path("docs/summary.json").read_text())
notes = {
    "docs/index.html": (
        "A go-live gate for moving a law firm's data into Clio Manage, one batch at a time: 30 constructed batches "
        "(3 runs each) from a fictional 12-lawyer firm's old practice management system, graded with "
        "<a href='https://github.com/pg2342-hub/golive-gate'>golive-gate</a>. Rules clean every value and tie each "
        "batch to the old system's own report; Claude makes the calls rules cannot (who a hand-typed matter belongs "
        "to, duplicate clients, unfamiliar columns, review notes); a batch loads only when every line ties, and "
        "every request is checked against Clio's published API schema. "
        f"Recorded live run of {s['model']}: {s['calls']} mapping calls, mean {s['mean_latency_s']:.1f} s and "
        f"${s['mean_cost_usd']:.4f} per batch; judge ${s['judge_cost_usd']:.2f} in total. "
        "<a href='baseline/'>See a plain spreadsheet import blocked by the same gate</a>. "
        "<a href='https://github.com/pg2342-hub/migration-cutover-gate'>Code on GitHub</a>."
    ),
    "docs/baseline/index.html": (
        "A plain spreadsheet import on the same 30 batches: it drops leading zeros, guesses clients, never "
        "reconciles and always loads, so the gate blocks it. <a href='../'>Back to the Claude pipeline</a>."
    ),
}
for path, note in notes.items():
    p = Path(path)
    p.write_text(p.read_text().replace("</h1>", f"</h1>\n<p>{note}</p>", 1))
PY
touch docs/.nojekyll
echo "demo written to docs/ (recorded Claude run) and docs/baseline/ (spreadsheet import)"
