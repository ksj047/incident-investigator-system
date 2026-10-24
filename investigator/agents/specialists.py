"""Observability and Dependency agents (tool-using specialists)."""
from __future__ import annotations

import re
from datetime import timedelta

from ..heuristics import evidence_from_calls, is_anomaly
from ..state import Evidence, Task
from ..tools import _iso, _parse_ts
from .base import ToolAgent


def mentioned_services(message: str, services, exclude: str | None = None) -> list[str]:
    """Services a log line points at: full names, or a name stem as a word (e.g. '/api/orders' -> orders-*)."""
    msg = message.lower()
    out = []
    for o in services:
        if o == exclude:
            continue
        stem = o.split("-")[0]
        if re.search(rf"(?<![\w-]){re.escape(o)}(?![\w-])", msg) or (len(stem) > 3 and re.search(rf"\b{re.escape(stem)}\b", msg)):
            out.append(o)
    return out


class ObservabilityAgent(ToolAgent):
    name = "observability"
    tools = ["query_logs", "query_metrics", "get_service_dependencies"]
    role = """You investigate logs and metrics. Find WHEN each affected service started misbehaving and HOW
(errors, latency, saturation, traffic). Check the focus services and follow the dependency chain downstream:
errors that name another service are leads to investigate. Compare onset times across services - the earliest
anomaly is usually closest to the cause. Query ERROR and WARN logs separately; use metric summaries
(baseline vs recent, first_anomaly_ts)."""

    async def fallback(self, task: Task) -> list[Evidence]:
        ex, s = self.ctx.executor, self.state
        services = list(dict.fromkeys(task.focus_services or [s.incident["reported_service"]]))
        graph = await ex.run(self.name, "get_service_dependencies", {"service": "*"})
        edges = graph.result["edges"] if graph.ok else {}
        done: set[str] = set()
        calls = [graph]
        depth = 0
        while services and depth < 3 and len(done) < 9:
            batch = [x for x in services if x not in done][:4]
            services = []
            plan = []
            for svc in batch:
                plan += [("query_logs", {"service": svc, "level": "ERROR"}),
                         ("query_logs", {"service": svc, "level": "WARN"}),
                         ("query_metrics", {"service": svc})]
            res = await ex.run_many(self.name, plan)
            # recovery: partial metric results are re-queried once
            again = [(c.tool, c.args) for c in res if c.ok and c.incomplete and c.tool == "query_metrics"]
            if again:
                res += await ex.run_many(self.name, again)
            calls += res
            done |= set(batch)
            # Data gaps: if a service cannot be observed, its dependencies cannot be ruled out -> widen the search.
            for svc in batch:
                mine = [c for c in res if c.args.get("service") == svc]
                if mine and all((not c.ok) or c.incomplete for c in mine if c.tool == "query_metrics") \
                        or any(not c.ok for c in mine if c.tool == "query_logs"):
                    services += edges.get(svc, [])
            # Expand: downstream dependencies of anomalous services + services named in error/warn logs.
            for c in res:
                if not c.ok:
                    continue
                svc = c.args["service"]
                if c.tool == "query_metrics" and any(is_anomaly(m) for m in c.result["metrics"]):
                    services += edges.get(svc, [])
                if c.tool == "query_logs":
                    for cl in c.result["message_counts"]:
                        services += mentioned_services(cl["message"], edges, exclude=svc)
            services = [x for x in dict.fromkeys(services) if x not in done]
            depth += 1
        return evidence_from_calls(s, self.name, calls)


class DependencyAgent(ToolAgent):
    name = "dependency"
    tools = ["get_deployments", "get_config_changes", "get_service_dependencies", "search_incident_history"]
    role = """You investigate CHANGES and STRUCTURE: deployments, configuration / feature-flag changes, the service
dependency graph and similar past incidents. List every change in the hours before symptom onset (and just after),
note exact timestamps relative to onset, and map which services depend on the changed ones. Past incidents are
leads only: say when history and current data disagree."""

    async def fallback(self, task: Task) -> list[Evidence]:
        ex, s = self.ctx.executor, self.state
        onset = _parse_ts(s.incident["symptom_onset"])
        rng = {"start": _iso(onset - timedelta(hours=6)), "end": _iso(onset + timedelta(minutes=30))}
        plan = [("get_service_dependencies", {"service": "*"}),
                ("get_deployments", dict(rng)), ("get_config_changes", dict(rng)),
                ("search_incident_history", {"query": f"{s.incident['title']} {s.incident['reported_service']}"})]
        if task.round > 0:  # follow-ups: per-service change history over a wider window
            for svc in task.focus_services[:3]:
                plan.append(("get_deployments", {"service": svc, "start": _iso(onset - timedelta(hours=24)), "end": rng["end"]}))
        calls = await ex.run_many(self.name, plan)
        # recovery: a failed change query is retried once more at the agent level
        retry = [(c.tool, c.args) for c in calls if not c.ok and c.tool in ("get_deployments", "get_config_changes")]
        if retry:
            calls += await ex.run_many(self.name, retry)
        return evidence_from_calls(s, self.name, calls)
