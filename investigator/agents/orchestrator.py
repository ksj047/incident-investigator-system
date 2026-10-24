"""Orchestrator: plans the investigation, schedules a task DAG with parallelism,
runs the reason -> critique -> gather-more-evidence feedback loop and enforces
budgets / termination conditions."""
from __future__ import annotations

import asyncio

from ..config import Settings
from ..llm import LLMClient
from ..report import build_report
from ..state import Budget, BudgetExceeded, InvestigationState, Task
from ..tools import ToolBox, ToolExecutor, World
from .analysts import CriticAgent, ReasoningAgent, ReportingAgent
from .base import BaseAgent, Context, compact
from .specialists import DependencyAgent, ObservabilityAgent


class Orchestrator(BaseAgent):
    name = "orchestrator"

    PLAN_SYSTEM = """You are the Orchestrator of a production incident investigation team. Plan the FIRST round of
evidence gathering. Agents available: "observability" (logs + metrics) and "dependency" (deployments, config changes,
dependency graph, incident history). These tasks run in parallel. Keep the plan small (2-4 tasks) and specific.
Reply with ONE JSON object:
{"tasks":[{"agent":"observability|dependency","goal":"...","focus_services":["..."]}],"rationale":"..."}"""

    def __init__(self, ctx: Context):
        super().__init__(ctx)
        self.agents = {"observability": ObservabilityAgent(ctx), "dependency": DependencyAgent(ctx)}
        self.reasoner = ReasoningAgent(ctx)
        self.critic = CriticAgent(ctx)
        self.reporter = ReportingAgent(ctx)
        self._n = 0

    def new_task(self, agent: str, goal: str, focus: list[str], depends_on=None) -> Task:
        self._n += 1
        t = Task(id=f"{agent[:3].upper()}-{self._n}", agent=agent, goal=goal, focus_services=focus,
                 depends_on=depends_on or [], round=self.state.round)
        self.state.tasks[t.id] = t
        self.state.emit_task(t)
        return t

    def _validate_plan(self, d: dict) -> dict:
        tasks = [t for t in d.get("tasks", []) if t.get("agent") in self.agents]
        if not tasks:
            raise ValueError("plan needs at least one observability or dependency task")
        for t in tasks:
            t["focus_services"] = [s for s in t.get("focus_services") or [] if s in self.ctx.services][:5]
        return {"tasks": tasks[:4], "rationale": d.get("rationale", "")}

    async def plan(self) -> list[Task]:
        s = self.state
        rep = s.incident["reported_service"]
        try:
            d = await self.llm_json([{"role": "system", "content": self.PLAN_SYSTEM},
                                     {"role": "user", "content": f"Incident: {compact(s.incident)}\nServices: {self.ctx.services}"}],
                                    self._validate_plan, max_tokens=600)
            specs = d["tasks"]
            s.log(self.name, "plan", source="llm", rationale=d["rationale"][:300])
        except BudgetExceeded:
            raise
        except Exception as e:
            s.log(self.name, "plan_fallback", reason=str(e)[:200])
            specs = [{"agent": "observability", "goal": f"characterise symptoms of {rep} and the services it depends on",
                      "focus_services": [rep]},
                     {"agent": "dependency", "goal": "list deployments/config changes before onset, dependency graph, similar incidents",
                      "focus_services": [rep]}]
        # Guarantee both evidence domains are covered and the reported service is examined.
        if not any(t["agent"] == "dependency" for t in specs):
            specs.append({"agent": "dependency", "goal": "recent changes and dependency graph", "focus_services": [rep]})
        if not any(t["agent"] == "observability" for t in specs):
            specs.append({"agent": "observability", "goal": f"symptoms of {rep}", "focus_services": [rep]})
        for t in specs:
            if t["agent"] == "observability" and not t["focus_services"]:
                t["focus_services"] = [rep]
        return [self.new_task(t["agent"], t["goal"], t["focus_services"]) for t in specs]

    async def run_dag(self, tasks: list[Task], runner) -> None:
        """Run tasks respecting `depends_on`; independent tasks run concurrently.
        A failed dependency does not block dependents - they run on whatever evidence exists (recovery)."""
        pending = {t.id: t for t in tasks}
        while pending:
            finished = {tid for tid, t in self.state.tasks.items() if t.status in ("done", "recovered", "failed", "skipped")}
            ready = [t for t in pending.values() if all(d in finished for d in t.depends_on)]
            if not ready:
                raise RuntimeError(f"dependency cycle in tasks {list(pending)}")
            for t in ready:
                t.status, t.attempts = "running", t.attempts + 1
                self.state.emit_task(t)
            self.state.log(self.name, "dispatch", tasks=[t.id for t in ready], parallel=len(ready))
            results = await asyncio.gather(*(runner(t) for t in ready), return_exceptions=True)
            for t, r in zip(ready, results):
                pending.pop(t.id)
                if isinstance(r, BudgetExceeded):
                    raise r
                if isinstance(r, Exception):
                    t.status, t.note = "failed", f"{type(r).__name__}: {r}"[:200]
                    self.state.log(self.name, "task_failed", task=t.id, error=t.note)
                self.state.emit_task(t)

    async def _run_task(self, t: Task):
        if t.agent in self.agents:
            return await self.agents[t.agent].run(t)
        if t.agent == "reasoning":
            return await self.reasoner.run(t)
        if t.agent == "critic":
            return await self.critic.run(t, final_round=self.state.round >= self.ctx.settings.limits.max_rounds - 1)
        raise ValueError(t.agent)

    async def investigate(self) -> dict:
        s, lim = self.state, self.ctx.settings.limits
        outcome = "inconclusive"
        try:
            round_tasks = await self.plan()
            while True:
                r = self.new_task("reasoning", "rank competing root-cause hypotheses", [], [t.id for t in round_tasks])
                c = self.new_task("critic", "challenge leading hypothesis", [], [r.id])
                await self.run_dag(round_tasks + [r, c], self._run_task)
                crit = s.critiques[-1] if s.critiques and s.critiques[-1].round == s.round else None
                if crit is None:
                    s.termination_reason = "critic failed; reporting current hypotheses"
                    top = s.ranked()[0] if s.hypotheses else None
                    outcome = "conclusive" if top and top.confidence >= lim.inconclusive_threshold else "inconclusive"
                    break
                if crit.verdict == "accept":
                    outcome, s.termination_reason = "conclusive", f"critic accepted in round {s.round}"
                    break
                if crit.verdict == "inconclusive":
                    s.termination_reason = f"critic judged evidence insufficient in round {s.round}"
                    break
                if s.round + 1 >= lim.max_rounds:
                    s.termination_reason = "max rounds reached"
                    break
                if s.budget.remaining_fraction() < 0.15:
                    s.termination_reason = "budget nearly exhausted"
                    break
                s.round += 1
                round_tasks = [self.new_task(f["agent"], f["goal"], f["focus_services"]) for f in crit.follow_ups]
                s.log(self.name, "feedback_loop", round=s.round, new_tasks=[t.id for t in round_tasks])
        except BudgetExceeded as b:
            s.termination_reason = f"budget exceeded: {b}"
            top = s.ranked()[0] if s.hypotheses else None
            outcome = "conclusive" if top and top.confidence >= lim.inconclusive_threshold else "inconclusive"
        rep_task = self.new_task("reporting", "write final report", [])
        rep_task.status = "running"
        s.emit_task(rep_task)
        writeup = await self.reporter.run(rep_task, outcome)
        s.emit_task(rep_task)
        return build_report(s, outcome, writeup, system="multi-agent")


async def investigate(world: World, settings: Settings, llm: LLMClient, listener=None) -> dict:
    lim = settings.limits
    state = InvestigationState(world.public_incident(),
                               Budget(lim.max_tool_calls, lim.max_llm_calls, lim.max_tokens, lim.max_wall_seconds))
    if listener:
        state.listeners.append(listener)
    tb = ToolBox(world, chaos_rate=settings.chaos_rate, seed=settings.seed)
    ex = ToolExecutor(tb, state, lim.tool_timeout_s, lim.tool_retries)
    ctx = Context(state, ex, llm, settings, world.services)
    orch = Orchestrator(ctx)
    try:
        return await asyncio.wait_for(orch.investigate(), timeout=lim.max_wall_seconds + 30)
    except asyncio.TimeoutError:
        state.termination_reason = "hard wall-clock timeout"
        return build_report(state, "inconclusive", ReportingAgent(ctx).fallback("inconclusive"), system="multi-agent")
