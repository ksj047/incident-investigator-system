"""Evaluate the multi-agent system against the single-agent baseline.

  python eval/run_eval.py                          # backend from env (offline if no key)
  python eval/run_eval.py --backend openrouter --model deepseek/deepseek-v4-flash
  python eval/run_eval.py --incidents INC-002 INC-007 --systems multi

Writes eval/results/<label>/{results.json, summary.md, reports/*.md}.
Ground truth is only read here, never by the investigators.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from investigator.agents.orchestrator import investigate  # noqa: E402
from investigator.baseline import investigate_single  # noqa: E402
from investigator.config import ROOT, Settings  # noqa: E402
from investigator.llm import make_client  # noqa: E402
from investigator.report import to_markdown  # noqa: E402
from investigator.tools import World  # noqa: E402

SYSTEMS = {"multi": investigate, "single": investigate_single}


def score(report: dict, gt: dict) -> dict:
    expected_inconclusive = gt["expected_outcome"] == "inconclusive"
    rc = report["root_cause"]
    if expected_inconclusive:
        correct = report["outcome"] == "inconclusive"
        service_ok = cause_ok = correct
    else:
        service_ok = bool(rc) and rc["service"] == gt["root_cause_service"]
        cause_ok = bool(rc) and rc["cause_type"] in gt["accepted_cause_types"]
        correct = service_ok and cause_ok
    # Is the true cause anywhere in the ranked list? (top-3 recall)
    in_top3 = expected_inconclusive and correct or any(
        h["suspect_service"] == gt["root_cause_service"] and h["cause_type"] in gt["accepted_cause_types"]
        for h in report["hypotheses"][:3])
    cited = [e for h in report["hypotheses"] for e in h["supporting"] + h["contradicting"]]
    grounded = [e for e in cited if e["grounded"]]
    refs = {r for e in cited for r in e["refs"]}
    key = set(gt["key_evidence"])
    top_conf = report["hypotheses"][0]["confidence"] if report["hypotheses"] else 0.0
    inv = report["investigation"]
    return {
        "correct": correct, "service_correct": service_ok, "cause_type_correct": cause_ok, "true_cause_in_top3": bool(in_top3),
        "outcome": report["outcome"],
        "predicted": f"{rc['cause_type']}@{rc['service']}" if rc else "inconclusive",
        "expected": "inconclusive" if expected_inconclusive else f"{gt['cause_type']}@{gt['root_cause_service']}",
        "top_confidence": top_conf,
        "confident_wrong": (not correct) and report["outcome"] == "conclusive" and top_conf >= 0.6,
        "evidence_cited": len(cited),
        "evidence_grounded_rate": round(len(grounded) / len(cited), 3) if cited else None,
        "key_evidence_recall": round(len(key & refs) / len(key), 3) if key else None,
        "tool_calls": inv["tool_calls"], "failed_tool_calls": inv["failed_tool_calls"], "retried_tool_calls": inv["retried_tool_calls"],
        "llm_calls": inv["llm_calls"], "tokens": inv["prompt_tokens"] + inv["completion_tokens"],
        "latency_s": inv["latency_s"], "rounds": inv["rounds"],
        "recovered_tasks": sum(1 for t in inv["tasks"] if t["status"] == "recovered"),
    }


def aggregate(rows: list[dict]) -> dict:
    def mean(key):
        vals = [r[key] for r in rows if r[key] is not None]
        return round(statistics.mean(vals), 3) if vals else None
    return {"n": len(rows), "accuracy": mean("correct"), "service_accuracy": mean("service_correct"),
            "cause_type_accuracy": mean("cause_type_correct"), "top3_recall": mean("true_cause_in_top3"),
            "confident_wrong": sum(r["confident_wrong"] for r in rows),
            "evidence_grounded_rate": mean("evidence_grounded_rate"), "key_evidence_recall": mean("key_evidence_recall"),
            "avg_tool_calls": mean("tool_calls"), "avg_llm_calls": mean("llm_calls"), "avg_tokens": mean("tokens"),
            "avg_latency_s": mean("latency_s"), "p50_latency_s": round(statistics.median(r["latency_s"] for r in rows), 2)}


async def run(args) -> None:
    settings = Settings()
    if args.backend:
        settings.backend = args.backend
    if args.model:
        settings.model = args.model
    llm = make_client(settings)
    label = args.label or (settings.backend if settings.backend == "offline" else settings.model.replace("/", "_"))
    out = ROOT / "eval" / "results" / label
    (out / "reports").mkdir(parents=True, exist_ok=True)
    ids = args.incidents or sorted(p.stem for p in (ROOT / "data" / "incidents").glob("*.json"))
    rows = []
    for inc in ids:
        world = World.load(ROOT / "data" / "incidents" / f"{inc}.json")
        gt = json.loads((ROOT / "data" / "ground_truth" / f"{inc}.json").read_text())
        for sysname in args.systems:
            t0 = time.monotonic()
            report = await SYSTEMS[sysname](world, settings, llm)
            sc = score(report, gt)
            rows.append({"incident": inc, "system": sysname, **sc})
            (out / "reports" / f"{inc}-{sysname}.md").write_text(to_markdown(report))
            (out / "reports" / f"{inc}-{sysname}.json").write_text(json.dumps(report, indent=1))
            print(f"{inc} {sysname:6s} {'OK ' if sc['correct'] else 'BAD'} pred={sc['predicted']:<40} exp={sc['expected']:<40} "
                  f"tools={sc['tool_calls']:>3} llm={sc['llm_calls']:>3} tok={sc['tokens']:>7} {time.monotonic() - t0:5.1f}s", flush=True)
    summary = {s: aggregate([r for r in rows if r["system"] == s]) for s in args.systems}
    meta = {"backend": settings.backend, "model": settings.model if settings.backend != "offline" else None,
            "chaos_rate": settings.chaos_rate, "seed": settings.seed}
    (out / "results.json").write_text(json.dumps({"meta": meta, "summary": summary, "rows": rows}, indent=1))
    (out / "summary.md").write_text(render_summary(meta, summary, rows))
    print(render_summary(meta, summary, rows))


def render_summary(meta, summary, rows) -> str:
    keys = ["accuracy", "service_accuracy", "cause_type_accuracy", "top3_recall", "confident_wrong", "evidence_grounded_rate",
            "key_evidence_recall", "avg_tool_calls", "avg_llm_calls", "avg_tokens", "avg_latency_s", "p50_latency_s"]
    systems = list(summary)
    lines = [f"# Evaluation results ({meta['backend']}{' / ' + meta['model'] if meta['model'] else ''})", "",
             "| metric | " + " | ".join(systems) + " |", "|---|" + "---|" * len(systems)]
    for k in keys:
        lines.append(f"| {k} | " + " | ".join(str(summary[s][k]) for s in systems) + " |")
    lines += ["", "## Per incident", "", "| incident | system | correct | predicted | expected | conf | grounded | key-ev recall | tools | llm | tokens | latency s |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['incident']} | {r['system']} | {'yes' if r['correct'] else 'NO'} | {r['predicted']} | {r['expected']} | "
                     f"{r['top_confidence']} | {r['evidence_grounded_rate']} | {r['key_evidence_recall']} | {r['tool_calls']} | "
                     f"{r['llm_calls']} | {r['tokens']} | {r['latency_s']} |")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=["openrouter", "offline"])
    ap.add_argument("--model")
    ap.add_argument("--label")
    ap.add_argument("--incidents", nargs="*")
    ap.add_argument("--systems", nargs="*", default=["multi", "single"], choices=list(SYSTEMS))
    asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
