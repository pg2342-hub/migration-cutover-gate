"""The live path end to end with a fake Anthropic client, then the same run replayed from the recording.

The fake returns the oracle's decisions and the judge always passes, so both runs reach GO, and
the replay makes no API calls.
"""

import json
import sys
import types

import agent as agent_mod
import judge_checks
from golive_gate import Gate, evaluate, load_cases, run_eval
from oracle import CASES, oracle

from cutover import mapper as M
from cutover import pipeline
from cutover.recorded import Tape


class FakeMessages:
    def __init__(self):
        self.by_prompt = {}
        for c in CASES.values():
            views = []
            pipeline.run(c.input, lambda view, c=c, views=views: views.append(view) or oracle(c)(view))
            decisions = oracle(c)(views[0])
            decisions.pop("_meta")
            self.by_prompt[M.prompt(views[0])] = decisions
        self.calls = 0

    def create(self, **kw):
        self.calls += 1
        if kw.get("system") == M.SYSTEM:
            assert kw["output_config"]["format"]["type"] == "json_schema"
            text = json.dumps(self.by_prompt[kw["messages"][0]["content"]])
        else:
            text = "VERDICT: PASS - meets the criterion"
        usage = types.SimpleNamespace(
            input_tokens=3000, output_tokens=600, cache_creation_input_tokens=0, cache_read_input_tokens=0
        )
        return types.SimpleNamespace(
            model=kw["model"], stop_reason="end_turn", content=[types.SimpleNamespace(type="text", text=text)], usage=usage
        )


def test_live_then_replay(tmp_path, monkeypatch):
    fake = FakeMessages()
    client = types.SimpleNamespace(beta=types.SimpleNamespace(messages=fake))
    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=lambda: client))
    monkeypatch.setenv("GOLIVE_LIVE", "1")
    monkeypatch.setattr(agent_mod, "MAPPER_TAPE", Tape(tmp_path / "mapper.jsonl"))
    monkeypatch.setattr(agent_mod, "_live", None)
    monkeypatch.setattr(judge_checks, "JUDGE_TAPE", Tape(tmp_path / "judge.jsonl"))
    monkeypatch.setattr(judge_checks, "_judge", None)

    cases = load_cases("evals/cases.yml")
    gate = Gate.load("evals/gate.yml")
    live = run_eval(agent_mod.live_agent, cases, judge_checks.checks, runs=2)
    assert evaluate(gate, live).decision == "go", evaluate(gate, live).reasons
    live_calls = fake.calls
    assert live_calls > 60

    monkeypatch.delenv("GOLIVE_LIVE")
    monkeypatch.setattr(agent_mod, "MAPPER_TAPE", Tape(tmp_path / "mapper.jsonl"))
    monkeypatch.setattr(judge_checks, "JUDGE_TAPE", Tape(tmp_path / "judge.jsonl"))
    monkeypatch.setattr(judge_checks, "_judge", None)
    replay = run_eval(agent_mod.recorded_agent, cases, judge_checks.checks, runs=2)
    assert evaluate(gate, replay).decision == "go"
    assert fake.calls == live_calls  # the replay made no API calls


def test_model_refusal_is_an_error_not_a_pass():
    msgs = types.SimpleNamespace(
        create=lambda **kw: types.SimpleNamespace(stop_reason="refusal", content=[], usage=None, model=kw["model"])
    )
    mapper = M.ClaudeMapper(client=types.SimpleNamespace(beta=types.SimpleNamespace(messages=msgs)))
    try:
        mapper({"clients": []})
    except RuntimeError as e:
        assert "declined" in str(e)
    else:
        raise AssertionError("a refusal must raise")
