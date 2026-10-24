"""Deterministic investigation analytics.

Used (a) as the recovery path whenever an LLM agent fails or returns unusable
output, (b) as the whole engine in `offline` mode, and (c) by the Critic as an
independent sanity check on LLM hypotheses.

Nothing here knows about individual test incidents: it scores candidates with
generic SRE heuristics - temporal precedence of changes, dependency topology
(root causes sit at the bottom of the blast radius), cross-service log
mentions and causal keywords.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .state import Evidence, InvestigationState, ToolCall
from .tools import _parse_ts

CAUSE_KEYWORDS = [
    (r"x509|certificate|tls handshake", "certificate_expiry", True),
    (r"oomkilled|outofmemory|out of memory|heap space|no space left|disk full", "resource_exhaustion", True),
    (r"upstream timeout calling \S+-ext|-ext returned 5\d\d", "dependency_outage", True),
    (r"rate limit|429|overloaded|max replicas|scale-up blocked", "traffic_spike", True),
    (r"lock wait|metadata lock|migration", "deployment_bug", True),
    (r"nullpointer|exception|panic|stack trace|deadlock", "deployment_bug", False),
]
RESOURCE_METRICS = ("memory_pct", "disk_used_pct")


@dataclass
class Signals:
    onset: datetime
    services: list[str] = field(default_factory=list)
    anomalies: dict[str, list[dict]] = field(default_factory=lambda: defaultdict(list))
    clusters: dict[str, list[dict]] = field(default_factory=lambda: defaultdict(list))
    changes: list[dict] = field(default_factory=list)
    downstream: dict[str, list[str]] = field(default_factory=dict)
    history: list[dict] = field(default_factory=list)
    unavailable: set = field(default_factory=set)  # (tool, service) with no successful data

    def neighbors(self, svc: str) -> set[str]:
        n = set(self.downstream.get(svc, []))
        n |= {s for s, d in self.downstream.items() if svc in d}
        return n

    def reachable_down(self, svc: str) -> set[str]:
        seen, stack = set(), list(self.downstream.get(svc, []))
        while stack:
            s = stack.pop()
            if s not in seen:
                seen.add(s)
                stack.extend(self.downstream.get(s, []))
        return seen

    def first_anomaly(self, svc: str) -> datetime | None:
        ts = [_parse_ts(a["first_anomaly_ts"]) for a in self.anomalies.get(svc, [])]
        return min(ts) if ts else None


def is_anomaly(m: dict) -> bool:
    r = m.get("change_ratio")
    return bool(m.get("first_anomaly_ts")) and r is not None and abs(r - 1) >= 0.3


def extract(state: InvestigationState) -> Signals:
    sig = Signals(onset=_parse_ts(state.incident["symptom_onset"]))
    seen_metric, seen_cluster, seen_change = set(), set(), set()
    ok_pairs = set()
    for c in state.tool_calls:
        svc = c.args.get("service")
        if not c.ok:
            if svc:
                sig.unavailable.add((c.tool, svc))
            continue
        ok_pairs.add((c.tool, svc))
        r = c.result
        if c.tool == "query_metrics":
            for m in r["metrics"]:
                if m["metric_id"] not in seen_metric and is_anomaly(m):
                    seen_metric.add(m["metric_id"])
                    sig.anomalies[svc].append(m)
        elif c.tool == "query_logs":
            for cl in r["message_counts"]:
                key = (svc, cl["message"])
                if key not in seen_cluster and cl["level"] in ("ERROR", "WARN") and cl["count"] >= 3:
                    seen_cluster.add(key)
                    sig.clusters[svc].append(cl)
        elif c.tool in ("get_deployments", "get_config_changes"):
            for row in r.get("deployments", []) + r.get("config_changes", []):
                if row["id"] not in seen_change:
                    seen_change.add(row["id"])
                    kind = "deployment" if row["id"].startswith("D-") else "config_change"
                    text = row.get("change_summary") or f"{row.get('key')}: {row.get('old_value')} -> {row.get('new_value')}"
                    sig.changes.append({**row, "kind": kind, "text": text})
        elif c.tool == "get_service_dependencies":
            if "edges" in r:
                sig.downstream.update(r["edges"])
            elif "downstream" in r:
                sig.downstream[r["service"]] = r["downstream"]
        elif c.tool == "search_incident_history":
            ids = {h["id"] for h in sig.history}
            sig.history.extend(h for h in r["results"] if h["id"] not in ids)
    sig.unavailable -= ok_pairs
    sig.services = sorted(set(sig.downstream) | {s for d in sig.downstream.values() for s in d}) or \
        sorted(set(sig.anomalies) | set(sig.clusters))
    return sig


@dataclass
class Candidate:
    service: str
    cause_type: str
    score: float
    support: list[str] = field(default_factory=list)       # record ids
    contradict: list[str] = field(default_factory=list)
    rationale: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    change: dict | None = None


def _mentions(sig: Signals) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for svc, cls in sig.clusters.items():
        for cl in cls:
            msg = cl["message"].lower()
            for other in sig.services:
                if other != svc and re.search(rf"(?<![\w-]){re.escape(other)}(?![\w-])", msg):
                    out[other].append({**cl, "from": svc})
    return out


def _keyword_cause(texts: list[str]) -> tuple[str | None, bool]:
    blob = " ".join(texts).lower()
    for pattern, cause, specific in CAUSE_KEYWORDS:
        if re.search(pattern, blob):
            return cause, specific
    return None, False


def rank_candidates(sig: Signals) -> list[Candidate]:
    mentions = _mentions(sig)
    implicated = {s for s in sig.services if sig.anomalies.get(s) and (sig.clusters.get(s) or mentions.get(s))}
    involved = set(sig.anomalies) | {s for s, c in sig.clusters.items() if any(x["level"] == "ERROR" for x in c)}

    # 1) Changes that precede a related anomaly closely in time "explain" what follows them.
    def change_fit(ch: dict) -> tuple[float, datetime | None]:
        ts = _parse_ts(ch["ts"])
        related = {ch["service"]} | sig.neighbors(ch["service"])
        key_text = f"{ch.get('key', '')} {ch.get('text', '')}".lower()
        related |= {s for s in sig.services if s in key_text}
        starts = [sig.first_anomaly(s) for s in related if sig.first_anomaly(s)]
        after = [t for t in starts if t >= ts - timedelta(minutes=5)]
        if not after:
            return 0.0, None
        gap = (min(after) - ts).total_seconds() / 60
        return math.exp(-max(0.0, gap) / 30), min(after)

    fits = {ch["id"]: change_fit(ch) for ch in sig.changes}
    strong_changes = [ch for ch in sig.changes if fits[ch["id"]][0] >= 0.5]

    # Anomalous services connected (through other anomalous services) to a well-fitting change are "explained".
    explained_by: dict[str, str] = {}
    for ch in strong_changes:
        key_text = f"{ch.get('key', '')} {ch.get('text', '')}".lower()
        targeted = {s for s in sig.services if s in key_text and s != ch["service"]}
        frontier = [ch["service"]]
        seen = set(frontier)
        while frontier:
            cur = frontier.pop()
            for n in sig.neighbors(cur) | (targeted if cur == ch["service"] else set()):
                if n not in seen and n in involved:
                    seen.add(n)
                    frontier.append(n)
                    t0 = sig.first_anomaly(n)
                    if t0 and t0 >= _parse_ts(ch["ts"]) - timedelta(minutes=5):
                        explained_by.setdefault(n, ch["service"])

    cands = involved | set(mentions) | {c["service"] for c in sig.changes}
    out: list[Candidate] = []
    for svc in sorted(cands):
        c = Candidate(svc, "unknown", 0.0)
        own_anoms = sig.anomalies.get(svc, [])
        own_err = [x for x in sig.clusters.get(svc, []) if x["level"] == "ERROR"]
        ment = mentions.get(svc, [])
        if own_anoms:
            c.score += 0.2
            c.support += [a["metric_id"] for a in own_anoms]
            c.rationale.append("own metrics anomalous: " + ", ".join(f"{a['metric']} x{a['change_ratio']}" for a in own_anoms))
        if own_err:
            c.score += 0.1
            c.support += [x["example_id"] for x in own_err[:2]]
            c.rationale.append(f"{sum(x['count'] for x in own_err)} own error logs")
        if ment:
            n = sum(x["count"] for x in ment)
            c.score += 0.2 * min(1.0, n / 10)
            c.support += [x["example_id"] for x in ment[:2]]
            c.rationale.append(f"named in {n} error/warn logs of {sorted({x['from'] for x in ment})}")
        # topology: a cause sits at the bottom of the blast radius
        down_impl = {d for d in sig.reachable_down(svc) if d in implicated and explained_by.get(d) != svc}
        if own_anoms or own_err or ment:
            if down_impl:
                c.score -= 0.1
                c.rationale.append(f"downstream services also implicated: {sorted(down_impl)} (may be a victim)")
            else:
                c.score += 0.15
                c.rationale.append("deepest implicated node in the dependency chain")
        # changes
        best = None
        for ch in (x for x in sig.changes if x["service"] == svc):
            fit, _ = fits[ch["id"]]
            if best is None or fit > fits[best["id"]][0]:
                best = ch
        if best is not None:
            fit, anom_ts = fits[best["id"]]
            if fit > 0.05:
                c.score += 0.5 * fit
                c.support.append(best["id"])
                c.change = best
                c.rationale.append(f"{best['kind']} {best['id']} at {best['ts']} precedes related anomaly by "
                                   f"{(anom_ts - _parse_ts(best['ts'])).total_seconds() / 60:.0f} min")
                key_text = f"{best.get('key', '')} {best.get('text', '')}".lower()
                if any(s in key_text and s != svc and s in involved for s in sig.services):
                    c.score += 0.15
                    c.rationale.append("change explicitly targets an affected service")
            else:
                c.contradict.append(best["id"])
                c.rationale.append(f"{best['kind']} {best['id']} is not followed by any related anomaly")
        if svc in explained_by and (best is None or fits[best["id"]][0] < 0.5):
            c.score -= 0.25
            c.rationale.append(f"symptoms explained by an earlier change in {explained_by[svc]}")
        # cause type
        texts = [x["message"] for x in sig.clusters.get(svc, [])] + [x["message"] for x in ment]
        kw, specific = _keyword_cause(texts)
        if specific:
            c.score += 0.2
            c.rationale.append(f"log keywords indicate {kw}")
        rate = next((a for a in own_anoms if a["metric"] == "request_rate_rps"), None)
        res = next((a for a in own_anoms if a["metric"] in RESOURCE_METRICS and a["change_ratio"] > 1.3), None)
        if c.change and fits[c.change["id"]][0] >= 0.5:
            c.cause_type = "config_change" if c.change["kind"] == "config_change" else "deployment_bug"
        elif kw == "resource_exhaustion" or res:
            c.cause_type = "resource_exhaustion"
            if c.change:
                c.assumptions.append(f"resource growth may have been introduced by {c.change['id']}")
        elif svc.endswith("-ext"):
            c.cause_type = "dependency_outage"
        elif kw:
            c.cause_type = kw
        elif rate and rate["change_ratio"] > 2:
            c.cause_type = "traffic_spike"
        elif c.change:
            c.cause_type = "config_change" if c.change["kind"] == "config_change" else "deployment_bug"
        if c.cause_type == "unknown":
            c.assumptions.append("no signal pins down the failure mechanism")
        # data gaps
        gaps = [t for (t, s) in sig.unavailable if s == svc]
        if gaps:
            c.assumptions.append(f"{', '.join(sorted(set(gaps)))} unavailable for {svc}; conclusion relies on other sources")
        hist = [h for h in sig.history if svc in h["services"]]
        if hist:
            c.rationale.append(f"historical incident(s) {[h['id'] for h in hist]} involved {svc} (lead only)")
        c.score = round(max(0.0, c.score), 3)
        c.support = list(dict.fromkeys(c.support))
        if c.score > 0:
            out.append(c)
    out.sort(key=lambda x: -x.score)
    return out


def confidences(cands: list[Candidate]) -> list[float]:
    total = sum(c.score for c in cands) or 1.0
    return [round(min(0.95, 0.55 * c.score / (total + 0.2) + 0.45 * min(1.0, c.score)), 2) for c in cands]


# ---------------------------------------------------------------------------
# Evidence extraction (fallback agents turn raw tool results into evidence)
# ---------------------------------------------------------------------------

def evidence_from_calls(state: InvestigationState, agent: str, calls: list[ToolCall], source: str = "fallback") -> list[Evidence]:
    made = []

    def add(**kw):
        made.append(state.add_evidence(Evidence(id="", agent=agent, source=source, **kw)))

    for c in calls:
        svc = c.args.get("service")
        if not c.ok:
            add(claim=f"{c.tool} for {svc or 'all services'} failed after {c.attempts} attempt(s): {c.error}",
                kind="fact", signal="tool_failure", service=svc, refs=[], tool_calls=[c.id])
            continue
        r = c.result
        warn = " (INCOMPLETE data)" if c.incomplete else ""
        if c.tool == "query_logs":
            for cl in r["message_counts"]:
                if cl["level"] in ("ERROR", "WARN") and cl["count"] >= 3:
                    add(claim=f"{svc} logged {cl['count']}x {cl['level']} '{cl['message']}' between {cl['first_seen']} and {cl['last_seen']}{warn}",
                        kind="fact", signal="error_logs", service=svc, refs=[cl["example_id"]], tool_calls=[c.id],
                        event_ts=cl["first_seen"], data=cl)
        elif c.tool == "query_metrics":
            for m in r["metrics"]:
                if is_anomaly(m):
                    add(claim=f"{svc} {m['metric']} moved from baseline {m['baseline_mean']} to {m['recent_mean']} "
                              f"(x{m['change_ratio']}), first anomalous at {m['first_anomaly_ts']}{warn}",
                        kind="fact", signal="metric_anomaly", service=svc, refs=[m["metric_id"]], tool_calls=[c.id],
                        event_ts=m["first_anomaly_ts"], data=m)
                elif m.get("recent_mean") is None:
                    add(claim=f"{svc} {m['metric']}: recent datapoints missing{warn}", kind="fact", signal="tool_failure",
                        service=svc, refs=[m["metric_id"]], tool_calls=[c.id], data=m)
        elif c.tool in ("get_deployments", "get_config_changes"):
            for row in r.get("deployments", []) + r.get("config_changes", []):
                if row["id"].startswith("D-"):
                    claim = f"deployment {row['id']}: {row['service']} {row['version']} at {row['ts']} ({row['change_summary']})"
                    sigl = "deployment"
                else:
                    claim = f"config change {row['id']}: {row['service']} {row['key']} {row['old_value']} -> {row['new_value']} at {row['ts']} by {row['author']}"
                    sigl = "config_change"
                add(claim=claim, kind="fact", signal=sigl, service=row["service"], refs=[row["id"]], tool_calls=[c.id],
                    event_ts=row["ts"], data=row)
        elif c.tool == "search_incident_history":
            for h in r["results"]:
                add(claim=f"past incident {h['id']} '{h['title']}' (similar symptoms) was caused by: {h['root_cause']} - similarity is a lead, not proof",
                    kind="inference", signal="history", service=(h["services"] or [None])[0], refs=[h["id"]],
                    tool_calls=[c.id], data=h)
    return made
