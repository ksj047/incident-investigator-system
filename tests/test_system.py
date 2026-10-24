import asyncio
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eval.run_eval import score  # noqa: E402
from investigator.agents.orchestrator import investigate  # noqa: E402
from investigator.baseline import investigate_single  # noqa: E402
from investigator.config import Settings  # noqa: E402
from investigator.llm import OfflineLLM, ScriptedLLM, parse_json  # noqa: E402
from investigator.state import Budget, InvestigationState  # noqa: E402
from investigator.tools import ToolBox, ToolExecutor, World, validate_args, ToolFailure  # noqa: E402

INC = ROOT / "data" / "incidents"
GT = ROOT / "data" / "ground_truth"


def world(i):
    return World.load(INC / f"{i}.json")


def run(coro):
    return asyncio.run(coro)


def make_exec(w, chaos=0.0, max_tool_calls=100):
    st = InvestigationState(w.public_incident(), Budget(max_tool_calls, 50, 100000, 60))
    return st, ToolExecutor(ToolBox(w, chaos_rate=chaos, seed=1), st, timeout_s=0.2, retries=2)


# ---------------------------------------------------------------- dataset
def test_dataset_has_at_least_10_incidents_with_ground_truth():
    ids = sorted(p.stem for p in INC.glob("*.json"))
    assert len(ids) >= 10
    assert ids == sorted(p.stem for p in GT.glob("*.json"))
    gts = [json.loads((GT / f"{i}.json").read_text()) for i in ids]
    assert any(g["expected_outcome"] == "inconclusive" for g in gts)
    assert sum(1 for i in ids if json.loads((INC / f"{i}.json").read_text())["faults"]) >= 4


def test_world_files_contain_no_ground_truth():
    for p in INC.glob("*.json"):
        d = json.loads(p.read_text())
        assert "root_cause_service" not in json.dumps(d["incident"]) and "ground_truth" not in d


def test_investigator_code_never_reads_ground_truth():
    for p in (ROOT / "investigator").rglob("*.py"):
        assert "ground_truth" not in p.read_text(), p


# ---------------------------------------------------------------- tools
def test_tool_argument_validation():
    with pytest.raises(ToolFailure):
        validate_args("query_logs", {})
    with pytest.raises(ToolFailure):
        validate_args("query_logs", {"service": "x", "level": "LOUD"})
    assert validate_args("query_logs", {"service": "x", "limit": "5", "junk": 1}) == {"service": "x", "limit": 5}


def test_unknown_service_is_structured_non_retryable_error():
    st, ex = make_exec(world("INC-001"))
    call = run(ex.run("t", "query_logs", {"service": "nope"}))
    assert not call.ok and call.error.startswith("not_found") and call.attempts == 1


def test_scripted_timeout_is_retried_then_succeeds():
    # INC-003: first metrics call for payment-service times out once
    st, ex = make_exec(world("INC-003"))
    call = run(ex.run("t", "query_metrics", {"service": "payment-service"}))
    assert call.ok and call.attempts == 2


def test_persistent_timeout_fails_after_bounded_retries():
    st, ex = make_exec(world("INC-007"))
    call = run(ex.run("t", "query_logs", {"service": "redis-cache"}))
    assert not call.ok and call.attempts == 3 and "timeout" in call.error


def test_partial_results_are_flagged():
    st, ex = make_exec(world("INC-009"))
    call = run(ex.run("t", "query_metrics", {"service": "user-service"}))
    assert call.ok and call.incomplete and call.result["metrics"][0]["recent_mean"] is None


def test_tool_budget_is_enforced():
    st, ex = make_exec(world("INC-001"), max_tool_calls=2)
    calls = run(ex.run_many("t", [("get_deployments", {})] * 4))
    assert sum(c.ok for c in calls) == 2
    assert all("budget_exceeded" in c.error for c in calls if not c.ok)


def test_logs_tool_returns_record_ids_for_grounding():
    st, ex = make_exec(world("INC-001"))
    call = run(ex.run("t", "query_logs", {"service": "payment-service", "level": "ERROR"}))
    assert call.ok and any(re.fullmatch(r"L-\d{4}", r) for r in call.record_ids)


# ---------------------------------------------------------------- llm parsing
def test_parse_json_tolerates_fences_and_chatter():
    assert parse_json('Sure!\n```json\n{"a": {"b": "}"}}\n```') == {"a": {"b": "}"}}
    assert parse_json('<think>hmm {x}</think> {"ok": true} trailing') == {"ok": True}
    with pytest.raises(ValueError):
        parse_json("no json here")


# ---------------------------------------------------------------- orchestration
def offline():
    return Settings(backend="offline", chaos_rate=0.0)


def test_parallel_dispatch_and_dag_order():
    r = run(investigate(world("INC-001"), offline(), OfflineLLM()))
    assert r["outcome"] == "conclusive"
    tasks = r["investigation"]["tasks"]
    assert [t["agent"] for t in tasks][:2] == ["observability", "dependency"]


def test_feedback_loop_adds_rounds_when_critic_unsatisfied():
    r = run(investigate(world("INC-010"), offline(), OfflineLLM()))
    assert r["investigation"]["rounds"] >= 2
    assert r["investigation"]["critiques"][0]["verdict"] == "investigate"


def test_inconclusive_outcome_allowed():
    r = run(investigate(world("INC-009"), offline(), OfflineLLM()))
    assert r["outcome"] == "inconclusive" and r["root_cause"] is None


def test_budget_exhaustion_terminates_gracefully():
    s = offline()
    s.limits.max_tool_calls = 5
    r = run(investigate(world("INC-002"), s, OfflineLLM()))
    assert r["investigation"]["tool_calls"] <= 5
    assert r["summary"]  # a report is still produced


def test_reports_separate_facts_from_assumptions():
    r = run(investigate(world("INC-004"), offline(), OfflineLLM()))
    assert r["facts"] and all(isinstance(x, str) for x in r["assumptions"])
    assert all(e["kind"] in ("fact", "inference", "assumption") for h in r["hypotheses"] for e in h["supporting"])


# ---------------------------------------------------------------- LLM path (scripted model)
def scripted_responder(messages):
    system, last = messages[0]["content"], messages[-1]["content"]
    if "Orchestrator" in system:
        return json.dumps({"tasks": [{"agent": "observability", "goal": "check payment", "focus_services": ["payment-service"]},
                                     {"agent": "dependency", "goal": "changes", "focus_services": []}]})
    if "observability agent" in system:
        if "Tool results" not in last:
            return json.dumps({"action": "tool_calls", "calls": [
                {"tool": "query_logs", "args": {"service": "payment-service", "level": "ERROR"}},
                {"tool": "query_metrics", "args": {"service": "payment-service"}}]})
        real = re.search(r'example_id\\?":\\?"(L-\d{4})', last).group(1)
        return json.dumps({"action": "finish", "summary": "errors", "findings": [
            {"claim": "payment-service NPE errors", "kind": "fact", "signal": "error_logs", "service": "payment-service", "refs": [real]},
            {"claim": "made-up observation", "kind": "fact", "signal": "other", "service": "payment-service", "refs": ["L-9999"]}]})
    if "dependency agent" in system:
        if "Tool results" not in last:
            return json.dumps({"action": "tool_calls", "calls": [{"tool": "get_deployments", "args": {}}]})
        return json.dumps({"action": "finish", "summary": "deploy", "findings": [
            {"claim": "payment-service v2.14.0 deployed 9 min before onset", "kind": "fact", "signal": "deployment",
             "service": "payment-service", "refs": ["D-001"], "event_ts": "2026-03-02T13:51:00Z"}]})
    if "Reasoning agent" in system:
        ids = re.findall(r"^(E\d\d) \| fact", last, flags=re.M)
        return json.dumps({"hypotheses": [{"statement": "bad payment deploy", "suspect_service": "payment-service",
                                           "cause_type": "deployment_bug", "confidence": 0.8, "supporting": ids[:3], "contradicting": []}]})
    if "Critic agent" in system:
        return "not json at all"  # forces critic fallback to rules
    return json.dumps({"summary": "Rollback payment-service.", "actions": [{"priority": "P0", "action": "rollback"}]})


def test_llm_path_grounds_findings_and_recovers_from_bad_output():
    llm = ScriptedLLM(scripted_responder)
    r = run(investigate(world("INC-001"), offline(), llm))
    g = r["investigation"]["grounding"]
    assert g["facts_downgraded"] == 1            # the fabricated L-9999 "fact" became an assumption
    assert g["refs_valid"] < g["refs_cited"]
    assert r["root_cause"]["service"] == "payment-service"
    statuses = {t["agent"]: t["status"] for t in r["investigation"]["tasks"]}
    assert statuses["observability"] == "done" and statuses["critic"] == "recovered"
    assert r["investigation"]["llm_calls"] > 5 and r["investigation"]["prompt_tokens"] > 0


def test_agent_failure_falls_back_to_deterministic_path():
    def broken(messages):
        raise RuntimeError("model crashed")
    llm = ScriptedLLM(lambda m: broken(m))
    r = run(investigate(world("INC-002"), offline(), llm))
    assert r["root_cause"] and r["root_cause"]["service"] == "orders-db"
    assert all(t["status"] in ("recovered", "done") for t in r["investigation"]["tasks"])


# ---------------------------------------------------------------- evaluation
@pytest.mark.parametrize("system", ["multi", "single"])
def test_eval_scoring_runs(system):
    fn = investigate if system == "multi" else investigate_single
    w = world("INC-009")
    gt = json.loads((GT / "INC-009.json").read_text())
    sc = score(run(fn(w, offline(), OfflineLLM())), gt)
    assert sc["correct"] and sc["expected"] == "inconclusive"


def test_offline_multi_agent_regression():
    ok = 0
    for p in sorted(INC.glob("*.json")):
        gt = json.loads((GT / p.name).read_text())
        ok += score(run(investigate(World.load(p), offline(), OfflineLLM())), gt)["correct"]
    assert ok >= 10
