"""Reasoning, Critic and Reporting agents."""
from __future__ import annotations

from datetime import timedelta

from ..heuristics import confidences, evidence_from_calls, extract, rank_candidates
from ..llm import LLMError
from ..state import CAUSE_TYPES, BudgetExceeded, Critique, Hypothesis
from ..tools import _parse_ts
from .base import BaseAgent, compact, evidence_table


def _dep_summary(ctx) -> str:
    sig = extract(ctx.state)
    return "; ".join(f"{s}->{','.join(d)}" for s, d in sorted(sig.downstream.items()) if d) or "unknown"


class ReasoningAgent(BaseAgent):
    name = "reasoning"

    SYSTEM = f"""You are the Reasoning agent of an incident investigation team. You do not call tools; you reason over
the shared evidence gathered by the Observability and Dependency agents.
Develop 1-4 COMPETING root-cause hypotheses and compare them.

Method:
- A cause must precede its effects: a change after symptom onset cannot be the cause.
- Distinguish causes from victims: services that only fail because something they depend on failed are victims.
  The cause is usually the deepest implicated component or the component whose change immediately preceded the first anomaly.
- Loud symptoms are not causes. Recent deploys are not automatically guilty. Similar past incidents are leads, not proof.
- If the evidence does not discriminate, give low confidences (the team may conclude "inconclusive").
- Confidence is your calibrated probability the hypothesis is the true root cause (all hypotheses together <= 1).

Reply with ONE JSON object:
{{"hypotheses":[{{"statement":"...","suspect_service":"<service or null>","cause_type":"{'|'.join(CAUSE_TYPES)}",
  "confidence":0.0-1.0,"supporting":["E01",...],"contradicting":["E07",...],"assumptions":["..."],
  "discriminating_check":"<what evidence would confirm/refute it>"}}],
 "missing_evidence":["..."]}}
Cite evidence ids (E01...) from the table only."""

    def _validate(self, d: dict) -> dict:
        hyps = d.get("hypotheses")
        if not isinstance(hyps, list) or not hyps:
            raise ValueError("hypotheses must be a non-empty list")
        ev_ids = {e.id for e in self.state.evidence}
        out = []
        for h in hyps[:4]:
            ct = h.get("cause_type")
            if ct not in CAUSE_TYPES:
                raise ValueError(f"cause_type must be one of {CAUSE_TYPES}")
            svc = h.get("suspect_service")
            if svc in ("null", "", "none", None):
                svc = None
            elif svc not in self.ctx.services:
                raise ValueError(f"unknown suspect_service {svc!r}; choose from {self.ctx.services} or null")
            conf = float(h.get("confidence", 0))
            sup = [e for e in h.get("supporting", []) if e in ev_ids]
            con = [e for e in h.get("contradicting", []) if e in ev_ids]
            if not sup:
                conf = min(conf, 0.2)  # ungrounded hypotheses cannot be confident
            out.append({**h, "suspect_service": svc, "confidence": max(0.0, min(1.0, conf)), "supporting": sup, "contradicting": con})
        total = sum(h["confidence"] for h in out)
        if total > 1.0:
            for h in out:
                h["confidence"] = round(h["confidence"] / total, 2)
        return {"hypotheses": out, "missing_evidence": d.get("missing_evidence", [])}

    async def run(self, task) -> list[Hypothesis]:
        s = self.state
        prev = [f"{h.id} {h.statement} conf={h.confidence}" for h in s.ranked()[:4]]
        crit = [{"round": c.round, "verdict": c.verdict, "issues": c.issues} for c in s.critiques[-2:]]
        user = f"""Incident: {compact(s.incident)}
Dependency graph (caller->callees): {_dep_summary(self.ctx)}

Evidence (id | kind | signal | service | event_ts | claim | refs):
{evidence_table(s, 70)}

Previous hypotheses: {prev or 'none'}
Critic feedback to address: {compact(crit, 2500) if crit else 'none'}"""
        try:
            d = await self.llm_json([{"role": "system", "content": self.SYSTEM}, {"role": "user", "content": user}],
                                    self._validate, max_tokens=1800)
            hyps = [Hypothesis(id=f"H{i + 1}", statement=h["statement"], suspect_service=h["suspect_service"],
                               cause_type=h["cause_type"], confidence=round(h["confidence"], 2),
                               supporting=h["supporting"], contradicting=h["contradicting"],
                               assumptions=[str(a) for a in h.get("assumptions", [])][:5])
                    for i, h in enumerate(d["hypotheses"])]
            task.status = "done"
            source = "llm"
        except BudgetExceeded:
            raise
        except Exception as e:  # recovery path
            s.log(self.name, "agent_fallback", reason=str(e)[:200])
            hyps = self.fallback()
            task.status, task.note, source = "recovered", f"LLM path failed ({type(e).__name__})", "fallback"
        hyps.sort(key=lambda h: -h.confidence)
        for i, h in enumerate(hyps):
            h.id = f"H{i + 1}"
        s.hypotheses = hyps
        s.emit_hypotheses()
        s.log(self.name, "hypotheses", source=source,
              ranked=[(h.id, h.suspect_service, h.cause_type, h.confidence) for h in hyps])
        return hyps

    def fallback(self) -> list[Hypothesis]:
        s = self.state
        evidence_from_calls(s, self.name, [c for c in s.tool_calls])  # make sure every observation is on the board
        cands = rank_candidates(extract(s))[:4]
        confs = confidences(cands)
        by_ref: dict[str, str] = {}
        for e in s.evidence:
            for r in e.refs:
                by_ref.setdefault(r, e.id)
        hyps = []
        for c, conf in zip(cands, confs):
            hyps.append(Hypothesis(
                id="", statement=f"{c.cause_type.replace('_', ' ')} in {c.service}: " + "; ".join(c.rationale[:4]),
                suspect_service=c.service, cause_type=c.cause_type, confidence=conf,
                supporting=list(dict.fromkeys(by_ref[r] for r in c.support if r in by_ref)),
                contradicting=list(dict.fromkeys(by_ref[r] for r in c.contradict if r in by_ref)),
                assumptions=c.assumptions))
        if not hyps:
            weak = [e.id for e in s.evidence if e.service == s.incident["reported_service"]][:4]
            hyps.append(Hypothesis(id="", statement="No candidate root cause stands out: no change events precede the symptoms "
                                   "and no metric anomaly or error cluster implicates a component.",
                                   suspect_service=None, cause_type="unknown", confidence=0.1, supporting=weak,
                                   assumptions=["symptom may be client-side, intermittent, or outside the observed data"]))
        return hyps


class CriticAgent(BaseAgent):
    name = "critic"

    SYSTEM = """You are the Critic agent of an incident investigation team. Your job is to challenge the leading
hypotheses before anything is reported. Look for: missing evidence, timelines that do not work (effect before cause),
victims mistaken for causes, reliance on past incidents or loud symptoms, unexplained contradicting evidence,
untested alternatives, and data gaps caused by tool failures.

Reply with ONE JSON object:
{"verdict":"accept|investigate|inconclusive",
 "issues":["..."],
 "follow_ups":[{"agent":"observability|dependency","goal":"<specific check>","focus_services":["..."]}],
 "confidence_adjustments":{"H1":0.0-1.0}}
Use "investigate" only when a specific follow-up could change the conclusion. Use "inconclusive" when the evidence
cannot support any hypothesis and more digging is unlikely to help."""

    def deterministic_checks(self) -> tuple[list[str], list[dict]]:
        s = self.state
        issues, follow = [], []
        hyps = s.ranked()
        evid = s.evidence_by_id()
        onset = _parse_ts(s.incident["symptom_onset"])
        sig = extract(s)
        observed = {c.args.get("service") for c in s.tool_calls if c.ok and c.tool in ("query_logs", "query_metrics")}
        if not hyps:
            return ["no hypotheses produced"], [{"agent": "observability", "goal": "broaden search to all implicated services",
                                                  "focus_services": [s.incident["reported_service"]]}]
        top = hyps[0]
        facts = [evid[e] for e in top.supporting if e in evid and evid[e].kind == "fact"]
        if len(facts) < 2:
            issues.append(f"{top.id} rests on {len(facts)} directly observed fact(s); needs corroboration")
            if top.suspect_service:
                follow.append({"agent": "observability", "goal": f"corroborate {top.id}: logs+metrics of {top.suspect_service}",
                               "focus_services": [top.suspect_service]})
        for e in (evid[x] for x in top.supporting if x in evid):
            if e.signal in ("deployment", "config_change") and e.event_ts and _parse_ts(e.event_ts) > onset + timedelta(minutes=2):
                issues.append(f"{top.id} cites change {e.refs} that happened AFTER symptom onset - cannot be the cause")
        if facts and all(e.signal == "history" for e in (evid[x] for x in top.supporting if x in evid)):
            issues.append(f"{top.id} is supported only by historical similarity")
        if len(hyps) > 1 and top.confidence - hyps[1].confidence < 0.1:
            issues.append(f"{top.id} and {hyps[1].id} are not discriminated (confidence gap {top.confidence - hyps[1].confidence:.2f})")
            svcs = [h.suspect_service for h in hyps[:2] if h.suspect_service]
            follow.append({"agent": "observability", "goal": "find evidence that discriminates the top two hypotheses", "focus_services": svcs})
            follow.append({"agent": "dependency", "goal": "check change history of the top two suspects", "focus_services": svcs})
        if top.cause_type == "unknown":
            issues.append(f"{top.id} names no failure mechanism")
            changed = sorted({c["service"] for c in sig.changes} - observed)[:3]
            if changed:
                issues.append(f"changes on {changed} not yet correlated with their metrics/logs")
                follow.append({"agent": "observability", "goal": f"check whether recently changed services {changed} show anomalies",
                               "focus_services": changed})
            rep = s.incident["reported_service"]
            unseen = [d for d in sorted(sig.reachable_down(rep)) if d not in observed][:4]
            if unseen:
                follow.append({"agent": "observability", "goal": f"examine unexplored dependencies of {rep}", "focus_services": unseen})
        if top.suspect_service:
            # Direct callees, plus callees of callees that are themselves anomalous (the blast-radius frontier).
            near = list(sig.downstream.get(top.suspect_service, []))
            near += [x for d in near if sig.anomalies.get(d) for x in sig.downstream.get(d, [])]
            down = [d for d in dict.fromkeys(near) if d not in observed][:4]
            if down and (top.confidence < 0.8 or top.cause_type == "unknown"):
                issues.append(f"downstream dependencies of {top.suspect_service} not yet examined: {down} (is the suspect a victim?)")
                follow.append({"agent": "observability", "goal": f"check whether {down} misbehaved before {top.suspect_service}",
                               "focus_services": down})
            gaps = sorted({t for (t, sv) in sig.unavailable if sv == top.suspect_service})
            if gaps:
                issues.append(f"data for {top.suspect_service} unavailable from {gaps}; rely on alternative sources")
        # independent cross-check against the deterministic analysis
        cands = rank_candidates(sig)
        if cands and top.suspect_service and cands[0].service != top.suspect_service and cands[0].score >= 0.6:
            issues.append(f"independent timeline/topology analysis favours {cands[0].service} ({cands[0].cause_type}): "
                          + "; ".join(cands[0].rationale[:3]))
            follow.append({"agent": "observability", "goal": f"test alternative: {cands[0].service}",
                           "focus_services": [cands[0].service]})
        return issues, follow

    def _validate(self, d: dict) -> dict:
        if d.get("verdict") not in ("accept", "investigate", "inconclusive"):
            raise ValueError("verdict must be accept|investigate|inconclusive")
        fus = []
        for f in d.get("follow_ups") or []:
            if f.get("agent") in ("observability", "dependency"):
                fus.append({"agent": f["agent"], "goal": str(f.get("goal", ""))[:300],
                            "focus_services": [x for x in (f.get("focus_services") or []) if x in self.ctx.services][:4]})
        d["follow_ups"] = fus
        d["issues"] = [str(i)[:300] for i in d.get("issues") or []][:8]
        adj = d.get("confidence_adjustments") or {}
        d["confidence_adjustments"] = {k: max(0.0, min(1.0, float(v))) for k, v in adj.items()} if isinstance(adj, dict) else {}
        return d

    async def run(self, task, final_round: bool) -> Critique:
        s = self.state
        issues, follow = self.deterministic_checks()
        verdict, source = None, "rules"
        try:
            hyps = [{"id": h.id, "statement": h.statement, "service": h.suspect_service, "cause": h.cause_type,
                     "confidence": h.confidence, "supporting": h.supporting, "contradicting": h.contradicting,
                     "assumptions": h.assumptions} for h in s.ranked()]
            user = f"""Incident: {compact(s.incident)}
Round {s.round} of at most {self.ctx.settings.limits.max_rounds}{' (FINAL round: choose accept or inconclusive)' if final_round else ''}.
Hypotheses: {compact(hyps, 4000)}
Evidence:
{evidence_table(s, 70)}
Automated consistency checks raised: {issues or 'nothing'}"""
            d = await self.llm_json([{"role": "system", "content": self.SYSTEM}, {"role": "user", "content": user}],
                                    self._validate, max_tokens=1000)
            verdict, source = d["verdict"], "llm+rules"
            issues = list(dict.fromkeys(d["issues"] + issues))
            follow = d["follow_ups"] + follow
            for h in s.hypotheses:
                if h.id in d["confidence_adjustments"]:
                    h.confidence = round(d["confidence_adjustments"][h.id], 2)
            task.status = "done"
        except BudgetExceeded:
            raise
        except Exception as e:
            s.log(self.name, "agent_fallback", reason=str(e)[:200])
            task.status, task.note = "recovered", f"LLM path failed ({type(e).__name__}); rule-based critique only"
        follow = self._dedupe(follow)
        top = s.ranked()[0] if s.hypotheses else None
        thr = self.ctx.settings.limits.inconclusive_threshold
        if final_round or not follow:
            verdict = "accept" if top and top.confidence >= thr and verdict != "inconclusive" else "inconclusive"
        elif verdict is None:
            verdict = "investigate"
        elif verdict == "accept" and any("AFTER symptom onset" in i or "not discriminated" in i or "favours" in i for i in issues):
            verdict = "investigate"  # rule-detected blocking issue overrides an LLM accept
        crit = Critique(round=s.round, verdict=verdict, issues=issues, follow_ups=follow if verdict == "investigate" else [], source=source)
        s.critiques.append(crit)
        s.emit("critique", critique={"round": crit.round, "verdict": crit.verdict, "issues": crit.issues,
                                     "follow_ups": crit.follow_ups, "source": crit.source})
        s.log(self.name, "critique", verdict=verdict, issues=issues[:5], follow_ups=len(crit.follow_ups))
        return crit

    def _dedupe(self, follow: list[dict]) -> list[dict]:
        """Drop follow-ups that would only repeat completed work (stagnation guard)."""
        s = self.state
        done = {(t.agent, tuple(sorted(t.focus_services))) for t in s.tasks.values() if t.status in ("done", "recovered")}
        observed = {c.args.get("service") for c in s.tool_calls if c.ok and c.tool in ("query_logs", "query_metrics")}
        out, seen = [], set()
        for f in follow:
            key = (f["agent"], tuple(sorted(f["focus_services"])))
            if key in seen or key in done:
                continue
            if f["agent"] == "observability" and f["focus_services"] and all(x in observed for x in f["focus_services"]) \
                    and not any(sv in f["focus_services"] for (_, sv) in extract(s).unavailable):
                continue
            seen.add(key)
            out.append(f)
        return out[:3]


ACTION_TEMPLATES = {
    "deployment_bug": [("P0", "Roll back {svc} to the previous version", "restores service fastest; deploy is the prime suspect"),
                       ("P1", "Add a regression test and canary analysis gate for {svc}", "catch this class of defect before full rollout")],
    "config_change": [("P0", "Revert the configuration change on {svc}", "the change immediately preceded the first anomaly"),
                      ("P1", "Route config/flag changes for {svc} through staged rollout with automatic rollback", "config changes need the same safety as code")],
    "dependency_outage": [("P0", "Fail over / degrade gracefully away from {svc}", "the dependency is failing; reduce customer impact"),
                          ("P1", "Add circuit breaker, tighter timeouts and a secondary provider for {svc}", "contain future dependency outages")],
    "resource_exhaustion": [("P0", "Free / add capacity on {svc} (restart, scale, expand storage)", "resource is exhausted"),
                            ("P1", "Alert on resource trend for {svc} well before saturation; fix the leak/growth source", "this failed slowly and was visible hours ahead")],
    "traffic_spike": [("P0", "Raise {svc} max replicas / shed non-critical load", "demand exceeds provisioned capacity"),
                      ("P1", "Pre-scale for campaigns; coordinate marketing pushes with capacity planning", "spike was predictable")],
    "certificate_expiry": [("P0", "Rotate the expired certificate on {svc}", "TLS handshakes are failing on expiry"),
                           ("P1", "Automate certificate renewal and alert 30 days before expiry", "prevent recurrence")],
    "unknown": [("P1", "Keep incident open; add tracing/profiling around {svc} and collect complete metrics", "evidence is insufficient for a root cause")],
}


class ReportingAgent(BaseAgent):
    name = "reporting"

    SYSTEM = """You are the Reporting agent. Write the final incident investigation summary and remediation plan from the
team's ranked hypotheses and evidence. Do not invent evidence. If the outcome is inconclusive, say so plainly and
recommend how to gather the missing evidence.
Reply with ONE JSON object:
{"summary":"<4-6 sentences for an incident channel>",
 "actions":[{"priority":"P0|P1|P2","action":"...","rationale":"...","hypothesis":"H1"}],
 "open_questions":["..."]}"""

    def _validate(self, d: dict) -> dict:
        if not isinstance(d.get("summary"), str) or not isinstance(d.get("actions"), list) or not d["actions"]:
            raise ValueError("summary (string) and non-empty actions list required")
        d["actions"] = [a for a in d["actions"] if isinstance(a, dict) and a.get("action")][:8]
        return d

    async def run(self, task, outcome: str) -> dict:
        s = self.state
        hyps = s.ranked()
        try:
            user = f"""Incident: {compact(s.incident)}
Outcome: {outcome}
Ranked hypotheses: {compact([{'id': h.id, 'statement': h.statement, 'service': h.suspect_service, 'cause': h.cause_type, 'confidence': h.confidence, 'supporting': h.supporting, 'contradicting': h.contradicting, 'assumptions': h.assumptions} for h in hyps], 4000)}
Evidence:
{evidence_table(s, 50)}
Critic issues: {[i for c in s.critiques for i in c.issues][-6:]}"""
            d = await self.llm_json([{"role": "system", "content": self.SYSTEM}, {"role": "user", "content": user}],
                                    self._validate, max_tokens=1200)
            task.status = "done"
            return d
        except (BudgetExceeded, LLMError, Exception) as e:
            s.log(self.name, "agent_fallback", reason=str(e)[:200])
            task.status, task.note = "recovered", "template report"
            return self.fallback(outcome)

    def fallback(self, outcome: str) -> dict:
        hyps = self.state.ranked()
        top = hyps[0] if hyps else None
        key = top.cause_type if top and outcome == "conclusive" else "unknown"
        svc = (top.suspect_service if top else None) or self.state.incident["reported_service"]
        actions = [{"priority": p, "action": a.format(svc=svc), "rationale": r, "hypothesis": top.id if top else None}
                   for p, a, r in ACTION_TEMPLATES[key]]
        if outcome == "conclusive" and top:
            summary = (f"Most likely root cause: {top.cause_type.replace('_', ' ')} in {svc} "
                       f"(confidence {top.confidence:.0%}). {top.statement}")
        else:
            summary = ("Investigation inconclusive: the available evidence does not support any root cause with "
                       f"sufficient confidence. Leading lead: {top.statement if top else 'none'}.")
        return {"summary": summary, "actions": actions, "open_questions": [a for h in hyps[:2] for a in h.assumptions][:4]}
