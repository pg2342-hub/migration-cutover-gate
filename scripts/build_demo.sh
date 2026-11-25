#!/usr/bin/env bash
# Rebuild the GitHub Pages demo in docs/ from the recorded live run (no API key needed).
set -euo pipefail
cd "$(dirname "$0")/.."
golive run evals/golive.yml --out docs >/dev/null || true
golive run evals/golive.baseline.yml --out docs/baseline >/dev/null || true
python scripts/summarize.py > docs/summary.json
rm -f docs/report.md docs/baseline/report.md
python scripts/build_demo.py
echo "demo written to docs/ (recorded Claude run) and docs/baseline/ (spreadsheet import)"
