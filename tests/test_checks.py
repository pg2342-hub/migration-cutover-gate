"""The pipeline with a correct mapping step passes every rule check; planted mistakes are caught by the right check."""

import copy

import pytest
from checks import checks
from golive_gate import FAIL, NA, PASS
from oracle import CASES, oracle

from cutover import pipeline
from cutover.baseline import baseline


def grade(case, out):
    return {c.id: c.run(case, out).result for c in checks}


@pytest.mark.parametrize("cid", sorted(CASES))
def test_oracle_passes_every_check(cid):
    case = CASES[cid]
    out = pipeline.run(case.input, oracle(case))
    verdicts = grade(case, out)
    failed = {k: checks[k].run(case, out).reason for k, v in verdicts.items() if v == FAIL}
    assert not failed, failed
    assert out["decision"] == case.expected["decision"]


def _with(case, edit):
    base = oracle(case)

    def mapper(view):
        d = base(view)
        edit(d)
        return d

    return mapper


def test_wrong_client_is_critical():
    case = CASES["a01"]

    def edit(d):
        for p in d["matter_clients"]:
            if p["matter_id"] == "M2026":
                p.update(client_id="C1022", certain=True)

    out = pipeline.run(case.input, _with(case, edit))
    v = checks["no_wrong_client"].run(case, out)
    assert v.result == FAIL and "M2026" in v.reason


def test_uncertain_match_goes_to_review_even_with_a_client():
    case = CASES["a01"]

    def edit(d):
        for p in d["matter_clients"]:
            if p["matter_id"] == "M2026":
                p.update(client_id="C1022", certain=False)

    out = pipeline.run(case.input, _with(case, edit))
    assert "M2026" in {q["id"] for q in out["queue"]}
    assert checks["no_wrong_client"].run(case, out).result == PASS


def test_client_outside_batch_is_refused():
    case = CASES["a05"]

    def edit(d):
        for p in d["matter_clients"]:
            if p["matter_id"] == "M2031":
                p.update(client_id="C9999", certain=True)

    out = pipeline.run(case.input, _with(case, edit))
    m = next(m for m in out["matters"] if m["id"] == "M2031")
    assert m["route"] == "review" and "not in this batch" in m["reason"]


def test_missed_duplicate_fails_review_flagged():
    case = CASES["a03"]

    def edit(d):
        for c in d["contacts"]:
            c["duplicate_of"] = None

    out = pipeline.run(case.input, _with(case, edit))
    assert checks["review_flagged"].run(case, out).result == FAIL


def test_held_batch_writes_nothing():
    for cid in ("b01", "b02", "b03", "b04"):
        out = pipeline.run(CASES[cid].input, oracle(CASES[cid]))
        assert out["decision"] == "hold" and out["load_plan"] == []


def test_trust_is_never_written():
    out = pipeline.run(CASES["r01"].input, oracle(CASES["r01"]))
    assert out["load_plan"] and not any("trust" in c["path"] for c in out["load_plan"])
    assert out["trust_handoff"] == [{"matter": "M2001", "balance": "2500.00"}]


def test_damaged_value_is_queued_and_not_loaded():
    case = CASES["m07"]
    out = pipeline.run(case.input, oracle(case))
    assert "M2022" in {q["id"] for q in out["queue"]}
    refs = {c["body"]["data"].get("client_reference") for c in out["load_plan"]}
    assert "M2022" not in refs and "M2023" in refs


def test_baseline_is_blocked_on_critical_checks():
    crit = set()
    for case in CASES.values():
        out = baseline(case.input)
        crit |= {c.id for c in checks if c.critical and c.run(case, out).result == FAIL}
    assert {"ids_preserved", "no_wrong_client", "amounts_exact", "hold_on_break"} <= crit


def test_judge_checks_skip_cleanly_without_queue():
    from judge_checks import checks as all_checks

    case = CASES["r09"]
    out = pipeline.run(case.input, oracle(case))
    assert all_checks["review_notes_actionable"].run(case, out).result == NA


def test_inputs_are_not_mutated():
    case = CASES["m04"]
    before = copy.deepcopy(case.input)
    pipeline.run(case.input, oracle(case))
    assert case.input == before
