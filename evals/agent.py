"""Agents for golive-gate. golive calls each with case.input (one raw batch) and grades the output.

- recorded_agent: the full pipeline, with the Claude mapping step replayed from recordings/ (no key)
- live_agent:     the full pipeline, calling Claude now and recording each reply (needs ANTHROPIC_API_KEY)
- csv_import:     the no-model spreadsheet import the gate must block
Only the model's replies are recorded; cleaning, reconciliation, guardrails and the Clio load
always run as code, so CI tests the current code against the recorded model decisions.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from golive_gate import Response

from cutover import pipeline
from cutover.baseline import baseline
from cutover.recorded import ROOT, Tape, recording_mapper, replay_mapper

MAPPER_TAPE = Tape(ROOT / "mapper.jsonl")
_live = None


def _respond(out):
    return Response(out, cost_usd=out.get("_meta", {}).get("cost_usd", 0.0))


def recorded_agent(case_input):
    return _respond(pipeline.run(case_input, replay_mapper(MAPPER_TAPE)))


def live_agent(case_input):
    global _live
    if _live is None:  # created on first use, so importing this file needs no key
        from cutover.mapper import ClaudeMapper

        _live = recording_mapper(ClaudeMapper(), MAPPER_TAPE)
    return _respond(pipeline.run(case_input, _live))


def csv_import(case_input):
    return baseline(case_input)
