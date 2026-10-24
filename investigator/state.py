"""Shared investigation state (the agents' blackboard) plus budgets and tracing."""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

CAUSE_TYPES = ["deployment_bug", "config_change", "dependency_outage", "resource_exhaustion",
               "traffic_spike", "certificate_expiry", "unknown"]
EVIDENCE_KINDS = ["fact", "inference", "assumption"]
SIGNALS = ["error_logs", "metric_anomaly", "deployment", "config_change", "dependency", "history", "tool_failure", "other"]


class BudgetExceeded(Exception):
    pass


@dataclass
class Budget:
    max_tool_calls: int
    max_llm_calls: int
    max_tokens: int
    max_wall_seconds: float
    started: float = field(default_factory=time.monotonic)
    tool_calls: int = 0
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def check(self, kind: str) -> None:
        if self.elapsed() > self.max_wall_seconds:
            raise BudgetExceeded("wall-clock limit reached")
        if kind == "tool" and self.tool_calls >= self.max_tool_calls:
            raise BudgetExceeded("tool-call limit reached")
        if kind == "llm" and (self.llm_calls >= self.max_llm_calls or self.tokens >= self.max_tokens):
            raise BudgetExceeded("LLM call/token limit reached")

    def remaining_fraction(self) -> float:
        return min(1 - self.tool_calls / self.max_tool_calls, 1 - self.llm_calls / self.max_llm_calls,
                   1 - self.tokens / self.max_tokens, 1 - self.elapsed() / self.max_wall_seconds)


@dataclass
class ToolCall:
    id: str
    agent: str
    tool: str
    args: dict
    ok: bool
    attempts: int
    latency_ms: float
    error: str | None = None
    incomplete: bool = False
    result: Any = None
    record_ids: list[str] = field(default_factory=list)


@dataclass
class Evidence:
    id: str
    agent: str
    claim: str
    kind: str               # fact | inference | assumption
    signal: str
    service: str | None
    refs: list[str]         # dataset record ids (L-0001, D-001, C-001, M-svc-metric, H-001)
    tool_calls: list[str]
    event_ts: str | None = None
    source: str = "llm"     # llm | fallback
    round: int = 0
    data: dict = field(default_factory=dict)


@dataclass
class Hypothesis:
    id: str
    statement: str
    suspect_service: str | None
    cause_type: str
    confidence: float
    supporting: list[str] = field(default_factory=list)      # evidence ids
    contradicting: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    status: str = "open"    # open | accepted | rejected


@dataclass
class Task:
    id: str
    agent: str
    goal: str
    focus_services: list[str]
    depends_on: list[str] = field(default_factory=list)
    status: str = "pending"  # pending | running | done | recovered | failed | skipped
    attempts: int = 0
    round: int = 0
    note: str = ""


@dataclass
class Critique:
    round: int
    verdict: str             # accept | investigate | inconclusive
    issues: list[str]
    follow_ups: list[dict]
    source: str


class InvestigationState:
    def __init__(self, incident: dict, budget: Budget):
        self.incident = incident
        self.budget = budget
        self.tool_calls: list[ToolCall] = []
        self.evidence: list[Evidence] = []
        self.hypotheses: list[Hypothesis] = []
        self.tasks: dict[str, Task] = {}
        self.critiques: list[Critique] = []
        self.trace: list[dict] = []
        self.round = 0
        self.termination_reason = ""
        self.grounding = {"refs_cited": 0, "refs_valid": 0, "facts_downgraded": 0}
        self.listeners: list = []  # callables receiving live events (used by the web server)

    # --- tracing -----------------------------------------------------------
    def emit(self, kind: str, **payload) -> None:
        if not self.listeners:
            return
        event = {"kind": kind, "t": round(self.budget.elapsed(), 3), "round": self.round, **payload}
        for fn in self.listeners:
            fn(event)

    def log(self, actor: str, event: str, **data) -> None:
        entry = {"t": round(self.budget.elapsed(), 3), "actor": actor, "event": event, **data}
        self.trace.append(entry)
        self.emit("trace", entry=entry)

    # --- ids ---------------------------------------------------------------
    def next_tool_id(self) -> str:
        return f"T{len(self.tool_calls) + 1:03d}"

    def add_evidence(self, ev: Evidence) -> Evidence:
        # De-duplicate: same claim on same refs from the same signal is one piece of evidence.
        for e in self.evidence:
            if e.signal == ev.signal and e.service == ev.service and set(e.refs) == set(ev.refs) and e.refs:
                return e
        ev.id = f"E{len(self.evidence) + 1:02d}"
        ev.round = self.round
        self.evidence.append(ev)
        self.emit("evidence", evidence=asdict(ev))
        return ev

    def known_record_ids(self, agent: str | None = None) -> set[str]:
        ids: set[str] = set()
        for c in self.tool_calls:
            if c.ok and (agent is None or c.agent == agent):
                ids.update(c.record_ids)
        return ids

    def evidence_by_id(self) -> dict[str, Evidence]:
        return {e.id: e for e in self.evidence}

    def emit_hypotheses(self) -> None:
        self.emit("hypotheses", hypotheses=[asdict(h) for h in self.ranked()])

    def emit_task(self, t: Task) -> None:
        self.emit("task", task=asdict(t))

    def ranked(self) -> list[Hypothesis]:
        return sorted(self.hypotheses, key=lambda h: -h.confidence)

    def snapshot(self) -> dict:
        return {
            "incident": self.incident,
            "evidence": [asdict(e) for e in self.evidence],
            "hypotheses": [asdict(h) for h in self.ranked()],
            "tasks": [asdict(t) for t in self.tasks.values()],
            "critiques": [asdict(c) for c in self.critiques],
            "tool_calls": [{k: v for k, v in asdict(c).items() if k != "result"} for c in self.tool_calls],
            "budget": {"tool_calls": self.budget.tool_calls, "llm_calls": self.budget.llm_calls,
                       "prompt_tokens": self.budget.prompt_tokens, "completion_tokens": self.budget.completion_tokens,
                       "elapsed_s": round(self.budget.elapsed(), 2)},
            "grounding": self.grounding,
            "termination_reason": self.termination_reason,
            "trace": self.trace,
        }
