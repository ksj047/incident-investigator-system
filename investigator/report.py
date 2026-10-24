"""Final report assembly (JSON + Markdown)."""
from __future__ import annotations

from .state import InvestigationState


def build_report(state: InvestigationState, outcome: str, writeup: dict, system: str) -> dict:
    ev = state.evidence_by_id()
    hyps = state.ranked()
    top = hyps[0] if hyps else None
    known = state.known_record_ids()

    def cite(ids):
        return [{"id": e.id, "kind": e.kind, "claim": e.claim, "refs": e.refs, "agent": e.agent,
                 "grounded": bool(e.refs) and all(r in known for r in e.refs)} for e in (ev[i] for i in ids if i in ev)]

    cited = {i for h in hyps for i in h.supporting + h.contradicting}
    return {
        "incident_id": state.incident["id"],
        "system": system,
        "outcome": outcome,
        "root_cause": ({"service": top.suspect_service, "cause_type": top.cause_type, "confidence": top.confidence}
                       if outcome == "conclusive" and top else None),
        "summary": writeup.get("summary", ""),
        "hypotheses": [{"rank": i + 1, "id": h.id, "statement": h.statement, "suspect_service": h.suspect_service,
                        "cause_type": h.cause_type, "confidence": h.confidence,
                        "supporting": cite(h.supporting), "contradicting": cite(h.contradicting),
                        "assumptions": h.assumptions} for i, h in enumerate(hyps)],
        "facts": [e.claim for e in state.evidence if e.kind == "fact" and e.id in cited],
        "inferences": [e.claim for e in state.evidence if e.kind == "inference" and e.id in cited],
        "assumptions": list(dict.fromkeys([e.claim for e in state.evidence if e.kind == "assumption" and e.id in cited]
                                          + [a for h in hyps[:2] for a in h.assumptions])),
        "actions": writeup.get("actions", []),
        "open_questions": writeup.get("open_questions", []),
        "investigation": {
            "rounds": state.round + 1,
            "termination_reason": state.termination_reason,
            "critiques": [{"round": c.round, "verdict": c.verdict, "issues": c.issues} for c in state.critiques],
            "tasks": [{"id": t.id, "agent": t.agent, "status": t.status, "round": t.round, "note": t.note}
                      for t in state.tasks.values()],
            "tool_calls": state.budget.tool_calls,
            "failed_tool_calls": sum(1 for c in state.tool_calls if not c.ok),
            "retried_tool_calls": sum(1 for c in state.tool_calls if c.attempts > 1),
            "llm_calls": state.budget.llm_calls,
            "prompt_tokens": state.budget.prompt_tokens,
            "completion_tokens": state.budget.completion_tokens,
            "latency_s": round(state.budget.elapsed(), 2),
            "grounding": state.grounding,
        },
    }


def to_markdown(r: dict) -> str:
    inv = r["investigation"]
    lines = [f"# Incident investigation report - {r['incident_id']} ({r['system']})", ""]
    if r["root_cause"]:
        rc = r["root_cause"]
        lines.append(f"**Outcome:** CONCLUSIVE - {rc['cause_type']} in `{rc['service']}` (confidence {rc['confidence']:.0%})")
    else:
        lines.append("**Outcome:** INCONCLUSIVE - evidence insufficient for a confident root cause")
    lines += ["", r["summary"], "", "## Ranked hypotheses"]
    for h in r["hypotheses"]:
        where = f"in `{h['suspect_service']}`" if h["suspect_service"] else "(no specific component)"
        lines.append(f"### {h['rank']}. {h['cause_type']} {where} - confidence {h['confidence']:.0%}")
        lines.append(h["statement"])
        for label, key in (("Supporting", "supporting"), ("Contradicting", "contradicting")):
            if h[key]:
                lines.append(f"- **{label}:**")
                lines += [f"  - [{e['kind']}] {e['claim']} (refs: {', '.join(e['refs']) or 'none'})" for e in h[key]]
        if h["assumptions"]:
            lines.append("- **Assumptions:** " + "; ".join(h["assumptions"]))
        lines.append("")
    lines.append("## Facts (directly observed)")
    lines += [f"- {f}" for f in r["facts"]] or ["- none"]
    lines.append("\n## Inferences and assumptions (not directly observed)")
    lines += [f"- {a}" for a in r["inferences"] + r["assumptions"]] or ["- none"]
    lines.append("\n## Recommended actions")
    lines += [f"- **{a.get('priority', 'P1')}** {a['action']} - {a.get('rationale', '')}" for a in r["actions"]]
    if r["open_questions"]:
        lines.append("\n## Open questions")
        lines += [f"- {q}" for q in r["open_questions"]]
    lines += ["", "## Investigation trace",
              f"- rounds: {inv['rounds']}, termination: {inv['termination_reason']}",
              f"- tool calls: {inv['tool_calls']} ({inv['failed_tool_calls']} failed, {inv['retried_tool_calls']} retried), LLM calls: {inv['llm_calls']}, "
              f"tokens: {inv['prompt_tokens'] + inv['completion_tokens']}, latency: {inv['latency_s']}s"]
    for c in inv["critiques"]:
        lines.append(f"- critic round {c['round']}: **{c['verdict']}** - " + "; ".join(c["issues"][:4]))
    lines.append("- tasks: " + ", ".join(f"{t['id']}({t['status']})" for t in inv["tasks"]))
    return "\n".join(lines) + "\n"
