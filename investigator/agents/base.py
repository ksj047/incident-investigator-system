"""Agent base classes: validated JSON calls to the LLM and a bounded tool-use loop."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

from ..config import Settings
from ..llm import LLMClient, LLMError, parse_json
from ..state import EVIDENCE_KINDS, SIGNALS, BudgetExceeded, Evidence, InvestigationState, Task
from ..tools import ToolExecutor, observation, tool_catalog


@dataclass
class Context:
    state: InvestigationState
    executor: ToolExecutor
    llm: LLMClient
    settings: Settings
    services: list[str]


def compact(obj, limit: int = 6000) -> str:
    text = json.dumps(obj, separators=(",", ":"), default=str)
    return text if len(text) <= limit else text[:limit] + "...<trimmed>"


def evidence_table(state: InvestigationState, limit: int = 60) -> str:
    rows = []
    for e in state.evidence[-limit:]:
        rows.append(f"{e.id} | {e.kind} | {e.signal} | {e.service} | {e.event_ts or '-'} | {e.claim} | refs={e.refs}")
    return "\n".join(rows) or "(no evidence yet)"


class BaseAgent:
    name = "agent"

    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.state = ctx.state

    async def llm_json(self, messages: list[dict], validate: Callable[[dict], dict], max_tokens: int = 1500) -> dict:
        """Call the LLM, parse + validate JSON; re-ask with the validation error (bounded)."""
        budget = self.state.budget
        msgs = list(messages)
        last_err = None
        for attempt in range(self.ctx.settings.limits.llm_retries + 1):
            budget.check("llm")
            resp = await self.ctx.llm.complete(msgs, max_tokens=max_tokens)
            budget.llm_calls += 1
            budget.prompt_tokens += resp.prompt_tokens
            budget.completion_tokens += resp.completion_tokens
            self.state.log(self.name, "llm_call", model=resp.model, prompt_tokens=resp.prompt_tokens,
                           completion_tokens=resp.completion_tokens, latency_s=round(resp.latency_s, 2), attempt=attempt + 1)
            try:
                return validate(parse_json(resp.text))
            except (ValueError, KeyError, TypeError, AttributeError) as e:
                last_err = e
                self.state.log(self.name, "invalid_llm_output", error=str(e)[:200])
                msgs = msgs + [{"role": "assistant", "content": resp.text[:4000]},
                               {"role": "user", "content": f"Your reply was invalid: {e}. Reply again with ONLY one JSON object that follows the required schema."}]
        raise LLMError(f"{self.name}: invalid output after retries: {last_err}")


FINDING_RULES = """Evidence rules:
- Every finding must cite dataset record ids exactly as they appear in tool results (log ids like L-0042, metric ids like M-orders-db-cpu_pct, deployment ids D-001, config ids C-001, history ids H-001).
- kind="fact" ONLY for something a tool result directly shows. Interpretations are kind="inference". Anything you believe but did not observe is kind="assumption".
- Report tool failures / incomplete data as findings with signal="tool_failure" - missing data is itself information.
- Prefer few, precise findings (max 10). Include timestamps (event_ts) when known.
- Do not decide the root cause; describe what you observed. Mention which service each observation is about."""


class ToolAgent(BaseAgent):
    """An agent that investigates with tools in a bounded loop, then reports structured findings."""

    tools: list[str] = []
    role = ""

    def system_prompt(self) -> str:
        lim = self.ctx.settings.limits
        return f"""You are the {self.name} agent in a multi-agent production incident investigation team.
{self.role}

Tools you may call:
{tool_catalog(self.tools)}

Protocol - reply with ONE JSON object per turn, either:
  {{"action":"tool_calls","reasoning":"<why>","calls":[{{"tool":"<name>","args":{{...}}}}]}}   (up to {lim.max_parallel_calls} calls; they run in parallel)
or, when you have enough (or after at most {lim.agent_max_steps} turns):
  {{"action":"finish","summary":"<2-3 sentences>","findings":[{{"claim":"...","kind":"fact|inference|assumption","signal":"{'|'.join(SIGNALS)}","service":"<service or null>","event_ts":"<ISO or null>","refs":["<record ids>"]}}]}}

Tools can time out or return partial data; retry once with different arguments or use another source, and note the gap.
{FINDING_RULES}"""

    def task_prompt(self, task: Task) -> str:
        s = self.state
        crit = [i for c in s.critiques for i in c.issues][-6:]
        hyps = [f"{h.id}: {h.statement} (conf {h.confidence})" for h in s.ranked()[:4]]
        return f"""Incident: {compact(s.incident)}
Data window: logs/metrics cover the 6h before symptom onset to 1h after. Known services: {', '.join(self.ctx.services)}

Your task ({task.id}, round {task.round}): {task.goal}
Focus services: {task.focus_services}

Shared investigation state (from other agents):
Evidence so far:
{evidence_table(s, 40)}
Current hypotheses: {hyps or 'none yet'}
Critic concerns: {crit or 'none yet'}"""

    def _validate_step(self, d: dict) -> dict:
        action = d.get("action")
        if action == "tool_calls":
            calls = d.get("calls")
            if not isinstance(calls, list) or not calls:
                raise ValueError("calls must be a non-empty list")
            for c in calls:
                if c.get("tool") not in self.tools:
                    raise ValueError(f"tool {c.get('tool')!r} not available to you; use one of {self.tools}")
            d["calls"] = calls[: self.ctx.settings.limits.max_parallel_calls]
            return d
        if action == "finish":
            if not isinstance(d.get("findings"), list):
                raise ValueError("findings must be a list")
            return d
        raise ValueError("action must be 'tool_calls' or 'finish'")

    async def run(self, task: Task) -> list[Evidence]:
        try:
            ev = await self._llm_loop(task)
            task.status = "done"
            return ev
        except BudgetExceeded:
            raise
        except (LLMError, Exception) as e:  # recovery: any agent failure -> deterministic path
            if isinstance(e, BudgetExceeded):
                raise
            self.state.log(self.name, "agent_fallback", task=task.id, reason=str(e)[:200])
            task.note = f"LLM path failed ({type(e).__name__}); recovered with deterministic analysis"
            ev = await self.fallback(task)
            task.status = "recovered"
            return ev

    async def _llm_loop(self, task: Task) -> list[Evidence]:
        lim = self.ctx.settings.limits
        msgs = [{"role": "system", "content": self.system_prompt()}, {"role": "user", "content": self.task_prompt(task)}]
        my_calls = []
        for step in range(lim.agent_max_steps + 1):
            if step == lim.agent_max_steps:
                msgs.append({"role": "user", "content": "Step budget exhausted. Reply now with action=finish."})
            d = await self.llm_json(msgs, self._validate_step)
            if d["action"] == "finish" or step == lim.agent_max_steps:
                if d["action"] != "finish":
                    raise LLMError("agent did not finish within step budget")
                return self._ingest(d, my_calls)
            calls = await self.ctx.executor.run_many(self.name, [(c["tool"], c.get("args") or {}) for c in d["calls"]])
            my_calls += calls
            obs = [observation(c) for c in calls]
            msgs += [{"role": "assistant", "content": compact(d, 2000)},
                     {"role": "user", "content": "Tool results:\n" + compact(obs, 9000)}]
        raise LLMError("unreachable")

    def _ingest(self, d: dict, my_calls) -> list[Evidence]:
        """Ground LLM findings against what tools actually returned."""
        from ..heuristics import evidence_from_calls
        known = self.state.known_record_ids()
        id_to_call = {}
        for c in self.state.tool_calls:
            for rid in c.record_ids:
                id_to_call.setdefault(rid, c.id)
        g = self.state.grounding
        out = []
        for f in d["findings"][:12]:
            if not isinstance(f, dict) or not f.get("claim"):
                continue
            refs = [str(r) for r in (f.get("refs") or [])]
            valid = [r for r in refs if r in known]
            g["refs_cited"] += len(refs)
            g["refs_valid"] += len(valid)
            kind = f.get("kind") if f.get("kind") in EVIDENCE_KINDS else "inference"
            if kind == "fact" and not valid:
                kind = "assumption"
                g["facts_downgraded"] += 1
            signal = f.get("signal") if f.get("signal") in SIGNALS else "other"
            svc = f.get("service") if f.get("service") in self.ctx.services else None
            out.append(self.state.add_evidence(Evidence(
                id="", agent=self.name, claim=str(f["claim"])[:400], kind=kind, signal=signal, service=svc,
                refs=valid, tool_calls=sorted({id_to_call[r] for r in valid}), event_ts=f.get("event_ts"), source="llm")))
        # Failed tool calls are always recorded so downstream agents see the data gaps.
        out += evidence_from_calls(self.state, self.name, [c for c in my_calls if not c.ok])
        self.state.log(self.name, "findings", count=len(out), summary=str(d.get("summary", ""))[:300])
        return out

    async def fallback(self, task: Task) -> list[Evidence]:
        raise NotImplementedError
