"""Run one batch through the pipeline and load it into a real Clio Manage account.

    CLIO_ACCESS_TOKEN=... python scripts/load_to_clio.py r01            # replayed Claude decisions
    CLIO_ACCESS_TOKEN=... ANTHROPIC_API_KEY=... python scripts/load_to_clio.py r01 --live

Use a Clio Manage trial or developer account, never a firm's production account. The token is an
OAuth access token from an app registered in the Clio developer portal. Nothing loads when the batch
does not tie; queued records and trust balances are never sent.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from golive_gate import load_cases

from cutover import clio, pipeline
from cutover.recorded import ROOT as TAPES
from cutover.recorded import Tape, replay_mapper

case_id, live = sys.argv[1], "--live" in sys.argv
case = {c.id: c for c in load_cases(ROOT / "evals" / "cases.yml")}[case_id]
if live:
    from cutover.mapper import ClaudeMapper

    mapper = ClaudeMapper()
else:
    mapper = replay_mapper(Tape(TAPES / "mapper.jsonl"))
out = pipeline.run(case.input, mapper, make_target=clio.LiveClio)
print(
    json.dumps(
        {
            "decision": out["decision"],
            "breaks": out["breaks"],
            "queue": out["queue"],
            "created": [(c["path"], c["id"]) for c in out["load_plan"]],
        },
        indent=2,
    )
)
