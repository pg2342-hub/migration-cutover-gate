"""Rule checks plus two Claude judge checks for what a rule cannot state exactly.

The judge runs live (and records each reply) when GOLIVE_LIVE=1, and replays the recorded
replies otherwise, so CI and the demo page need no API key.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from checks import checks as rule_checks
from golive_gate import NA, CheckSet, judge_check

from cutover.recorded import ROOT, Tape, recording_judge, replay_judge

JUDGE_TAPE = Tape(ROOT / "judge.jsonl")
_judge = None


def judge(prompt):
    global _judge
    if _judge is None:
        if os.environ.get("GOLIVE_LIVE") == "1":
            from golive_gate import ClaudeJudge

            _judge = recording_judge(ClaudeJudge(model="claude-opus-5-5", effort="low"), JUDGE_TAPE)
        else:
            _judge = replay_judge(JUDGE_TAPE)
    return _judge(prompt)


def _queue(out):
    return "\n".join(f"- {q['type']} {q['id']}: {q['reason']}" for q in out["queue"])


def _summary(out):
    # fixed field order, so a replayed output renders the same prompt as the live one
    recon = [{k: r[k] for k in ("measure", "key", "source", "migrated", "ties")} for r in out["reconciliation"]]
    return (
        f"Decision the pipeline took: {out['decision']}\n"
        f"Reconciliation: {json.dumps(recon, sort_keys=True)}\n"
        f"Review queue:\n{_queue(out) or '(empty)'}\n\n"
        f"Message to the firm:\n{out['summary']}"
    )


checks = CheckSet(rule_checks)

_actionable = judge_check(
    "review_notes_actionable",
    "Each review-queue reason tells the firm's operations lead, in plain words, exactly which record to look at and "
    "what answer is needed (for example which of two clients a matter belongs to, or whether two rows are the same "
    "person). A reason that only names an error code, or that a non-technical reader could not act on, fails.",
    judge=judge,
    render_case=lambda case: f"Batch {case.id}: {case.title}",
    render_output=_queue,
)
_honest = judge_check(
    "summary_honest",
    "The message to the firm matches the decision and the reconciliation shown: it says the batch is on hold when the "
    "decision is hold and names the line(s) that do not tie with both numbers; it never says a held batch is ready or "
    "loaded; when the batch loads it says so and mentions any records still waiting for review. It asks only for "
    "sign-offs or answers that the queue or the breaks actually need.",
    judge=judge,
    render_case=lambda case: f"Batch {case.id}: {case.title}",
    render_output=_summary,
    critical=True,
)


@checks.check("review_notes_actionable", text=_actionable.text.split(".")[0] + ".")
def review_notes_actionable(case, out):
    if not out["queue"]:
        return NA
    return _actionable.run(case, out)


@checks.check("summary_honest", text=_honest.text.split(".")[0] + ".", critical=True)
def summary_honest(case, out):
    return _honest.run(case, out)
