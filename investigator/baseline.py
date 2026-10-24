"""Single-agent baseline: one ReAct-style agent with ALL the same tools, the same
budgets and the same report schema - but no specialist decomposition, no shared
critique loop and no parallel task planning."""
from __future__ import annotations

import asyncio
from datetime import timedelta

from .agents.analysts import ReportingAgent
from .agents.base import Context, ToolAgent, compact
from .config import Settings
from .heuristics import confidences, evidence_from_calls, extract, rank_candidates
from .llm import LLMClient, LLMError
from .report import build_report
from .state import CAUSE_TYPES, Budget, BudgetExceeded, Evidence, Hypothesis, InvestigationState, Task
from .tools import TOOL_SPECS, ToolBox, ToolExecutor, World, _iso, _parse_ts, observation, tool_catalog


class SingleAgent(ToolAgent):
    name = "single_agent"
    tools = list(TOOL_SPECS)
    MAX_STEPS = 12

    def system_prompt(self) -> str:
        return f"""You are an SRE investigating a production incident on your own. Find the root cause.
Tools:
{tool_catalog()}

Reply with ONE JSON object per turn, either
  {{"action":"tool_calls","reasoning":"...","calls":[{{"tool":"...","args":{{...}}}}]}}  (up to {self.ctx.settings.limits.max_parallel_calls} calls)
or, when done (at most {self.MAX_STEPS} turns):
  {{"action":"finish","summary":"...","outcome":"conclusive|inconclusive",
    "hypotheses":[{{"statement":"...","suspect_service":"<service or null>","cause_type":"{'|'.join(CAUSE_TYPES)}","confidence":0-1,
      "supporting":[{{"claim":"...","kind":"fact|inference|assumption","refs":["record ids"]}}],
      "contradicting":[{{"claim":"...","kind":"fact|inference|assumption","refs":["..."]}}],
      "assumptions":["..."]}}],
    "actions":[{{"priority":"P0|P1|P2","action":"...","rationale":"..."}}]}}
Cite dataset record ids exactly as returned by tools (L-0001, M-svc-metric, D-001, C-001, H-001). Tools can fail; note gaps.
Rank hypotheses, distinguish facts from assumptions, and say inconclusive when evidence is insufficient."""

    def _validate_step(self, d: dict) -> dict:
        if d.get("action") == "finish":
            hyps = d.get("hypotheses")
            if not isinstance(hyps, list):
                raise ValueError("hypotheses must be a list")
            for h in hyps:
                if h.get("cause_type") not in CAUSE_TYPES:
                    raise ValueError(f"cause_type must be one of {CAUSE_TYPES}")
                if h.get("suspect_service") not in self.ctx.services + [None]:
                    h["suspect_service"] = None
            return d
        return super()._validate_step(d)

    async def investigate(self) -> tuple[str, dict]:
        s = self.state
        msgs = [{"role": "system", "content": self.system_prompt()},
                {"role": "user", "content": f"Incident: {compact(s.incident)}\nKnown services: {', '.join(self.ctx.services)}\n"
                                            "Data covers 6h before symptom onset to 1h after."}]
        for step in range(self.MAX_STEPS + 1):
            if step == self.MAX_STEPS:
                msgs.append({"role": "user", "content": "Turn budget exhausted. Reply now with action=finish."})
            d = await self.llm_json(msgs, self._validate_step, max_tokens=2000)
            if d["action"] == "finish":
                return self._ingest_final(d)
            if step == self.MAX_STEPS:
                raise LLMError("did not finish")
            calls = await self.ctx.executor.run_many(self.name, [(c["tool"], c.get("args") or {}) for c in d["calls"]])
            msgs += [{"role": "assistant", "content": compact(d, 2000)},
                     {"role": "user", "content": "Tool results:\n" + compact([observation(c) for c in calls], 9000)}]
        raise LLMError("unreachable")

    def _ingest_final(self, d: dict) -> tuple[str, dict]:
        s = self.state
        known = s.known_record_ids()
        g = s.grounding
        hyps = []
        for i, h in enumerate(d["hypotheses"][:4]):
            ids = {"supporting": [], "contradicting": []}
            for key in ids:
                for f in h.get(key) or []:
                    if not isinstance(f, dict):
                        continue
                    refs = [str(r) for r in f.get("refs") or []]
                    valid = [r for r in refs if r in known]
                    g["refs_cited"] += len(refs)
                    g["refs_valid"] += len(valid)
                    kind = f.get("kind") if f.get("kind") in ("fact", "inference", "assumption") else "inference"
                    if kind == "fact" and not valid:
                        kind = "assumption"
                        g["facts_downgraded"] += 1
                    e = s.add_evidence(Evidence(id="", agent=self.name, claim=str(f.get("claim", ""))[:400], kind=kind,
                                                signal="other", service=None, refs=valid, tool_calls=[]))
                    ids[key].append(e.id)
            conf = max(0.0, min(1.0, float(h.get("confidence", 0))))
            hyps.append(Hypothesis(id=f"H{i + 1}", statement=str(h.get("statement", "")), suspect_service=h.get("suspect_service"),
                                   cause_type=h["cause_type"], confidence=conf if ids["supporting"] else min(conf, 0.2),
                                   supporting=ids["supporting"], contradicting=ids["contradicting"],
                                   assumptions=[str(a) for a in h.get("assumptions") or []][:5]))
        s.hypotheses = hyps
        s.emit_hypotheses()
        outcome = d.get("outcome") if d.get("outcome") in ("conclusive", "inconclusive") else "conclusive"
        top = s.ranked()[0] if hyps else None
        if not top or top.confidence < self.ctx.settings.limits.inconclusive_threshold:
            outcome = "inconclusive"
        return outcome, {"summary": d.get("summary", ""), "actions": d.get("actions") or [], "open_questions": []}

    async def heuristic_single_pass(self) -> tuple[str, dict]:
        """Offline / recovery path: one pass over the reported service + global changes, rank once."""
        s, ex = self.state, self.ctx.executor
        rep = s.incident["reported_service"]
        onset = _parse_ts(s.incident["symptom_onset"])
        rng = {"start": _iso(onset - timedelta(hours=6)), "end": _iso(onset + timedelta(minutes=30))}
        calls = await ex.run_many(self.name, [
            ("query_logs", {"service": rep, "level": "ERROR"}), ("query_logs", {"service": rep, "level": "WARN"}),
            ("query_metrics", {"service": rep}), ("get_service_dependencies", {"service": "*"}),
            ("get_deployments", dict(rng)), ("get_config_changes", dict(rng))])
        evidence_from_calls(s, self.name, calls)
        cands = rank_candidates(extract(s))[:4]
        by_ref = {r: e.id for e in s.evidence for r in e.refs}
        s.hypotheses = [Hypothesis(id=f"H{i + 1}", statement=f"{c.cause_type} in {c.service}: " + "; ".join(c.rationale[:3]),
                                   suspect_service=c.service, cause_type=c.cause_type, confidence=conf,
                                   supporting=[by_ref[r] for r in c.support if r in by_ref],
                                   contradicting=[by_ref[r] for r in c.contradict if r in by_ref], assumptions=c.assumptions)
                        for i, (c, conf) in enumerate(zip(cands, confidences(cands)))]
        s.emit_hypotheses()
        top = s.ranked()[0] if s.hypotheses else None
        outcome = "conclusive" if top and top.confidence >= self.ctx.settings.limits.inconclusive_threshold else "inconclusive"
        return outcome, ReportingAgent(self.ctx).fallback(outcome)


async def investigate_single(world: World, settings: Settings, llm: LLMClient, listener=None) -> dict:
    lim = settings.limits
    state = InvestigationState(world.public_incident(),
                               Budget(lim.max_tool_calls, lim.max_llm_calls, lim.max_tokens, lim.max_wall_seconds))
    if listener:
        state.listeners.append(listener)
    tb = ToolBox(world, chaos_rate=settings.chaos_rate, seed=settings.seed)
    ex = ToolExecutor(tb, state, lim.tool_timeout_s, lim.tool_retries)
    agent = SingleAgent(Context(state, ex, llm, settings, world.services))
    state.tasks["SINGLE-1"] = Task(id="SINGLE-1", agent=agent.name, goal="investigate", focus_services=[], status="running")
    state.emit_task(state.tasks["SINGLE-1"])
    try:
        outcome, writeup = await asyncio.wait_for(agent.investigate(), timeout=lim.max_wall_seconds)
        state.tasks["SINGLE-1"].status = "done"
        state.termination_reason = "agent finished"
    except (LLMError, BudgetExceeded, asyncio.TimeoutError, Exception) as e:
        state.log(agent.name, "agent_fallback", reason=f"{type(e).__name__}: {str(e)[:200]}")
        state.tasks["SINGLE-1"].status = "recovered"
        state.termination_reason = f"LLM path failed ({type(e).__name__}); heuristic single pass"
        outcome, writeup = await agent.heuristic_single_pass()
    state.emit_task(state.tasks["SINGLE-1"])
    return build_report(state, outcome, writeup, system="single-agent")
