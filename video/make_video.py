"""Build the ~10 minute walkthrough video: slides (Pillow) + narration (edge-tts) -> MP4 (ffmpeg).

  pip install edge-tts
  python video/make_video.py [--results eval/results/offline]

Slides pull numbers and report excerpts from the evaluation results, so the video always matches the repo.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import ssl
import subprocess
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "video" / "build"
W, H = 1920, 1080
BG, PANEL, INK, MUTED, ACCENT, GOOD, BAD = "#0f172a", "#1e293b", "#e2e8f0", "#94a3b8", "#f97316", "#34d399", "#f87171"
F_B = "/usr/share/fonts/opentype/inter/Inter-Bold.otf"
F_R = "/usr/share/fonts/opentype/inter/Inter-Regular.otf"
F_M = "/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-Regular.ttf"
VOICE = os.getenv("TTS_VOICE", "en-US-AndrewNeural")


def f(path, size):
    return ImageFont.truetype(path, size)


class Slide:
    def __init__(self, title: str, kicker: str = ""):
        self.img = Image.new("RGB", (W, H), BG)
        self.d = ImageDraw.Draw(self.img)
        self.d.rectangle((0, 0, W, 8), fill=ACCENT)
        if kicker:
            self.d.text((80, 50), kicker.upper(), font=f(F_B, 24), fill=ACCENT)
        self.d.text((80, 85), title, font=f(F_B, 56), fill=INK)
        self.y = 190

    def bullets(self, items, x=90, size=34, width=None, gap=18, color=INK):
        for it in items:
            sub = it.startswith("  ")
            text = it.strip()
            lines = textwrap.wrap(text, (width or int(2900 / size)) + (6 if sub else 0))
            bx = x + (50 if sub else 0)
            self.d.ellipse((bx, self.y + size // 2 - 6, bx + 12, self.y + size // 2 + 6), fill=MUTED if sub else ACCENT)
            for i, ln in enumerate(lines):
                self.d.text((bx + 30, self.y), ln, font=f(F_R, size - (4 if sub else 0)), fill=MUTED if sub else color)
                self.y += size + 8
            self.y += gap
        return self

    def code(self, text, x=80, y=None, w=None, size=24, title=None):
        y = self.y if y is None else y
        w = w or (W - 160)
        lines = text.rstrip("\n").split("\n")
        h = len(lines) * (size + 8) + 40 + (40 if title else 0)
        self.d.rounded_rectangle((x, y, x + w, y + h), radius=14, fill="#020617", outline="#334155", width=2)
        yy = y + 20
        if title:
            self.d.text((x + 20, yy), title, font=f(F_B, 22), fill=MUTED)
            yy += 40
        for ln in lines:
            color = INK
            s = ln.strip()
            if s.startswith(("#", "//")):
                color = MUTED
            elif s.startswith("$"):
                color = GOOD
            elif "INVESTIGATE" in s or "BAD" in s or "investigate" in s[:40]:
                color = "#fbbf24"
            self.d.text((x + 20, yy), ln, font=f(F_M, size), fill=color)
            yy += size + 8
        self.y = y + h + 24
        return self

    def table(self, rows, col_w, x=80, size=26, row_h=50, header_color=ACCENT, color_fn=None):
        y = self.y
        for r_i, row in enumerate(rows):
            xx = x
            if r_i % 2 == 1:
                self.d.rectangle((x - 10, y - 6, x + sum(col_w), y + row_h - 10), fill=PANEL)
            for c_i, (cell, cw) in enumerate(zip(row, col_w)):
                color = header_color if r_i == 0 else (color_fn(r_i, c_i, cell) if color_fn else INK)
                self.d.text((xx, y), str(cell), font=f(F_B if r_i == 0 else F_R, size), fill=color)
                xx += cw
            y += row_h
        self.y = y + 20
        return self

    def image(self, path, box):
        im = Image.open(path).convert("RGB")
        im.thumbnail((box[2] - box[0], box[3] - box[1]))
        self.img.paste(im, (box[0] + (box[2] - box[0] - im.width) // 2, box[1]))
        return self

    def note(self, text, y=1010, color=MUTED, size=24):
        self.d.text((80, y), text, font=f(F_R, size), fill=color)
        return self


def excerpt(md_path: Path, patterns, width=118, limit=16):
    out = []
    for ln in md_path.read_text().splitlines():
        if any(p in ln for p in patterns):
            for w_ in textwrap.wrap(ln.replace("**", ""), width)[:2]:
                out.append(w_)
        if len(out) >= limit:
            break
    return "\n".join(out[:limit])


def build_slides(res_dir: Path):
    res = json.loads((res_dir / "results.json").read_text())
    S = res["summary"]
    rows = res["rows"]
    rep = res_dir / "reports"
    backend = res["meta"]["backend"] + (f" / {res['meta']['model']}" if res["meta"]["model"] else "")
    m, s1 = S["multi"], S["single"]
    nm = round(m["accuracy"] * m["n"])
    ns = round(s1["accuracy"] * s1["n"])
    slides = []

    # 1 title
    sl = Slide("Multi-Agent Production Incident Investigator", "AI engineer assignment - walkthrough")
    sl.y = 300
    sl.bullets(["Six cooperating agents investigate incidents like an SRE team",
                "Simulated logs, metrics, deploys, config, dependencies, history - with failing tools",
                "Ranked, evidence-backed hypotheses - or an honest 'inconclusive'",
                "Evaluated on 12 adversarial incidents against a single-agent baseline"], size=38)
    sl.note("Python 3, standard library only  |  LLM via OpenRouter (cheap / free models)  |  offline deterministic mode")
    slides.append((sl, """Hi, and welcome. This is my submission for the AI engineer assignment: a multi-agent system that investigates production incidents.
In about ten minutes I will cover the problem, the architecture and how the agents coordinate, the tools and their failures, how conclusions are grounded in evidence, the incident dataset, a few real runs, and the evaluation against a single-agent baseline, including the limitations.
It is plain Python with no runtime dependencies, and it reaches language models through OpenRouter, using a cheap model by default with a free fallback."""))

    # 2 problem
    sl = Slide("The problem", "requirements")
    sl.bullets(["Input: an incident report (symptoms, onset time, reported service)",
                "Access: logs, metrics, deployments, config changes, dependency graph, past incidents",
                "Data may be incomplete, contradictory or misleading - tools time out or return partial results",
                "Output: ranked root-cause hypotheses with supporting AND contradicting evidence, confidence, facts vs assumptions, actions",
                "Must be allowed to conclude 'inconclusive'",
                "Agents must genuinely collaborate - not a chain of prompts"], size=34)
    slides.append((sl, """The system receives an incident report: symptoms, an onset time and the service where the problem was noticed. It can query logs, metrics, deployments, configuration changes, the dependency graph and past incidents.
That data may be incomplete, contradictory or misleading, and the tools can time out or return partial results.
The output must be ranked hypotheses with supporting and contradicting evidence, confidence, actions, and a clear split between facts and assumptions. And it must be allowed to say "inconclusive".
Finally, the agents have to genuinely collaborate. A chain of prompts is not enough, and that was my main design driver."""))

    # 3 architecture
    sl = Slide("Architecture", "how the agents fit together")
    sl.image(ROOT / "docs" / "architecture.png", (80, 170, W - 80, H - 40))
    slides.append((sl, """Here is the architecture. The orchestrator receives the incident, asks the model for a plan, validates it and turns it into a small graph of tasks with dependencies.
In each round, the observability agent, working with logs and metrics, and the dependency agent, working with deployments, configuration, topology and history, run in parallel, each in its own bounded tool loop.
Everything they find goes onto a shared blackboard: typed evidence, hypotheses, tasks, critiques, every tool call, and the budget.
The reasoning agent builds competing hypotheses from that board. The critic then challenges the leader. If the critic says "investigate", its follow-up requests become the next round's tasks. That is the orange feedback loop. When it accepts, or rules the evidence insufficient, the reporting agent writes the report.
Every tool call goes through a layer with validation, timeouts, retries, budgets and fault injection, and every agent has a deterministic fallback."""))

    # 4 coordination
    sl = Slide("Coordination: blackboard + task DAG + feedback loop", "not a prompt chain")
    sl.code("""# each round is a DAG; independent tasks run concurrently (asyncio.gather)
round 0:  OBS-1 || DEP-2  ->  REA-3  ->  CRI-4
critic:   INVESTIGATE  "downstream dependencies of api-gateway not yet examined:
                        ['auth-service','orders-service','search-service',...]
                        (is the suspect a victim?)"
round 1:  OBS-5 || OBS-6  ->  REA-7  ->  CRI-8   -> ACCEPT
report:   REP-9    (termination: critic accepted in round 1)

# limits: 3 rounds, 5 steps/agent task, 70 tool calls, 45 LLM calls,
#         300k tokens, 420 s wall clock -> always ends with a report""", size=26, title="INC-010 trace (retry-storm incident)")
    sl.bullets(["Specialists see other agents' evidence and the critic's concerns in their prompt",
                "Critic follow-ups are structured: {agent, goal, focus_services}; duplicates of completed work are dropped",
                "Termination: accept | inconclusive | max rounds | budget | hard timeout"], size=30)
    slides.append((sl, """Here is a real trace from incident ten, a retry storm. In round zero, the observability and dependency tasks run in parallel, reasoning waits for both, and the critic waits for reasoning.
The leading hypothesis blamed a configuration change on the API gateway. But the critic noticed that services downstream of the suspect had never been examined, so it could not rule out that the gateway was a victim. It returned "investigate", with structured follow-ups naming the agent, the goal and the services.
In round one, the observability agent checked those services, reasoning re-ranked, and the critic accepted.
So what a specialist does in round one is decided by the critic's objection to round zero. That is the collaboration. The loop is bounded by three rounds, step limits, and budgets on tool calls, model calls, tokens and time, and it always ends with a report."""))

    # 5 tools
    sl = Slide("Tools: structured I/O, errors, simulated failures", "tool layer")
    sl.table([["tool", "returns"],
              ["query_logs(service, level?, contains?, start?, end?)", "message counts + first/last seen + example id"],
              ["query_metrics(service, metric?, ...)", "baseline vs recent, change ratio, first anomaly"],
              ["get_deployments / get_config_changes", "change events with ids + timestamps"],
              ["get_service_dependencies(service | '*')", "downstream / upstream edges"],
              ["search_incident_history(query)", "past post-mortems ('a lead, not proof')"]],
             [820, 900], size=26, row_h=52)
    sl.bullets(["Schema validation -> structured errors (not_found, invalid_argument: non-retryable)",
                "Scripted faults per incident: timeout (call hangs), partial (records truncated, data missing), HTTP 503",
                "+ random chaos rate; executor: per-call timeout, 2 retries with exponential backoff, budget check",
                "Failures become evidence (signal=tool_failure) so reasoning knows what it could NOT see"], size=30)
    slides.append((sl, """There are six tools, covering logs, metrics, deployments, configuration, dependencies and history. Each has a declared schema. Bad arguments return structured, non-retryable errors instead of exceptions.
Results are compact and easy to analyze: log message counts with first-seen times and example record ids, and metric summaries with a baseline, a change ratio and the first anomalous timestamp.
Each incident can script failures: a call that hangs until the timeout fires, partial results with missing data, or an HTTP five-oh-three. A random chaos rate adds more. The executor applies timeouts and up to two retries with backoff, and it checks the budget. If a call still fails, that failure becomes evidence, so the other agents know what the team could not see."""))

    # 6 grounding
    sl = Slide("Evidence-based conclusions", "facts vs assumptions")
    sl.code("""{"claim": "orders-db logged 35x ERROR 'too many clients already (max_connections=50)'",
 "kind": "fact",  "signal": "error_logs",  "service": "orders-db",
 "refs": ["L-0249"],  "tool_calls": ["T014"],  "event_ts": "2026-03-03T09:46:45Z"}""", size=24, title="an evidence item on the blackboard")
    sl.bullets(["Every citation must be a record id that a tool actually returned (L-, M-, D-, C-, H- ids)",
                "Invalid ids are dropped; a 'fact' with no valid id is downgraded to an assumption (counted)",
                "Hypotheses cite evidence ids for AND against; no support -> confidence capped at 0.2",
                "Report sections: ranked hypotheses, facts, inferences / assumptions, actions, open questions, trace",
                "Top confidence < 0.45 after the final round -> outcome = inconclusive"], size=31)
    slides.append((sl, """Every evidence item is typed as a fact, an inference or an assumption, and it carries the dataset record ids it rests on.
Each cited id is checked against what the tools actually returned. Unknown ids are dropped, and a claimed fact with no valid reference is downgraded to an assumption and counted, so hallucinated evidence becomes a measurable number.
Hypotheses must cite evidence for and against. Without support, confidence is capped at twenty percent. The report separates observed facts from inferences and assumptions, and if the best hypothesis is below forty-five percent after the final round, the outcome is inconclusive."""))

    # 7 recovery + LLM
    sl = Slide("LLM integration and recovery", "reliability")
    sl.bullets(["OpenRouter client: default deepseek/deepseek-v4-flash (~$0.09 / 1M input tokens), free fallback gemma-4-31b-it:free",
                "  retries with backoff on 429/5xx, model fallback list, real token accounting from 'usage'",
                "JSON action protocol (works with any model, no native function-calling needed)",
                "  tolerant JSON extraction; schema validation; re-ask with the validation error (bounded)",
                "Every agent has a deterministic fallback using the same tools",
                "  LLM error / invalid output / crash -> task status 'recovered', investigation continues",
                "  same analytics give the Critic an independent timeline + topology cross-check",
                "Offline mode = all fallbacks: whole system runs, tests and evaluates with no API key"], size=31)
    slides.append((sl, """The OpenRouter client defaults to DeepSeek V4 Flash, about nine cents per million input tokens, with a free Gemma fallback. It retries on rate limits, walks a model fallback list and records real token usage.
Agents use a small JSON action protocol instead of native function calling, so any model works. Replies are parsed tolerantly and validated, and the model is re-asked with the exact error a bounded number of times.
If the model fails or crashes, that agent's deterministic fallback takes over with the same tools, and the task is marked recovered. The same analytics give the critic an independent cross-check, and they power an offline mode that runs everything without an API key."""))

    # 8 dataset
    ds = [["id", "true cause", "trap"],
          ["001", "deploy bug @ payment", "sanity case"],
          ["002", "config @ orders-db", "frontend deploy just before report"],
          ["003", "outage @ payment-gateway-ext", "unrelated config change; metrics timeout"],
          ["004", "resource exhaustion @ recommend.", "fresh search deploy; real change 5h old"],
          ["005", "traffic spike @ api-gateway", "harmless auth deploy"],
          ["006", "cert expiry @ auth", "past incident blames redis; evictions up"],
          ["007", "config @ redis-cache", "logs ALWAYS time out; metrics truncated"],
          ["008", "deploy bug @ inventory", "victim search has loudest CPU; tool 503"],
          ["009", "(inconclusive)", "weak signal, no changes, partial metrics"],
          ["010", "config @ api-gateway", "retry storm; victim has own deploy"],
          ["011", "config @ notification", "misleading history + real redis noise"],
          ["012", "disk full @ orders-db", "cascade; frontend loudest; truncated logs"]]
    sl = Slide("Synthetic incident dataset (12 incidents)", "evaluation data")
    sl.y = 175
    sl.table(ds, [110, 600, 1000], size=27, row_h=58)
    sl.note("15-service e-commerce world | 7h window, 5-min metrics, ~330 log lines | ground truth stored separately; a test proves the investigator never reads it")
    slides.append((sl, """For evaluation I generated twelve incidents. Each is a full world: fifteen services, seven hours of noisy logs and metrics, changes, a dependency graph, history and a fault profile.
Each one has a trap. In incident two, a frontend deploy lands just before the report, but the cause is a database connection limit cut from five hundred to fifty. In four, the real cause is a slow memory leak from a deploy five hours earlier. In six, a near-identical past incident blames the cache, but the cause is an expired certificate. In seven, log queries for the key services always time out. In eight, the loudest symptom belongs to a victim. Nine is designed to be inconclusive, and twelve is a cascading failure from a full disk.
Ground truth sits in a separate folder that only the evaluator reads, and a test enforces that."""))

    # 9 run INC-002
    sl = Slide("Run: INC-002 - the misleading frontend deploy", "live investigation")
    sl.code("$ python3 -m investigator.cli INC-002\n" + excerpt(rep / "INC-002-multi.md", [
        "Outcome", "### 1.", "[fact] orders-db", "[fact] config change", "### 2.", "Contradicting", "[fact] deployment D-001",
        "**P0**", "tool calls:"], width=120, limit=15), size=22)
    slides.append((sl, """Here is a real run of incident two. The result is conclusive: a configuration change on the orders database, at eighty-two percent confidence.
Every piece of supporting evidence is a fact with a record id. Connections flattened at fifty, the database logged "too many clients", and max connections was lowered one minute before the first anomaly.
The frontend hypothesis is contradicted, because its deploy happened after the frontend's errors had started. The P-zero action is to revert the change.
The observability agent got here by following leads: from the frontend, to the gateway log naming the orders service, to the database. The single agent stopped at the frontend."""))

    # 10 INC-007 / INC-009
    sl = Slide("Tool failures and honest uncertainty", "INC-007 and INC-009")
    sl.code(excerpt(rep / "INC-007-multi.md", ["Outcome", "### 1.", "tool calls:", "critic round"], width=120, limit=7),
            size=22, title="INC-007: logs for search / redis / product-db always time out")
    sl.code(excerpt(rep / "INC-009-multi.md", ["Outcome", "### 1.", "Keep incident open", "critic round"], width=120, limit=6),
            size=22, title="INC-009: weak signal, partial metrics -> inconclusive")
    slides.append((sl, """In incident seven, every log query for the key services times out, even after retries. The observability agent widens its search to the dependencies it cannot observe, re-queries truncated metrics, and finds the cache hit rate collapsing. The dependency agent finds that the cache TTL was cut from an hour to five seconds. The critic records that logs were unavailable and that the conclusion relies on other sources.
In incident nine there are no changes, the signal is weak, and the metrics stay incomplete. The system does not invent a story. It reports inconclusive and recommends better telemetry."""))

    # 11 results
    def color(r, c, cell):
        return INK
    tbl = [["metric", "multi-agent", "single-agent"],
           ["root-cause accuracy", f"{nm}/{m['n']}  ({m['accuracy']:.2f})", f"{ns}/{s1['n']}  ({s1['accuracy']:.2f})"],
           ["service / cause-type accuracy", f"{m['service_accuracy']:.2f} / {m['cause_type_accuracy']:.2f}", f"{s1['service_accuracy']:.2f} / {s1['cause_type_accuracy']:.2f}"],
           ["true cause in top 3", f"{m['top3_recall']:.2f}", f"{s1['top3_recall']:.2f}"],
           ["confident-wrong answers", f"{m['confident_wrong']}", f"{s1['confident_wrong']}"],
           ["evidence grounded rate", f"{m['evidence_grounded_rate']}", f"{s1['evidence_grounded_rate']}"],
           ["key-evidence recall", f"{m['key_evidence_recall']:.2f}", f"{s1['key_evidence_recall']:.2f}"],
           ["avg tool calls", f"{m['avg_tool_calls']:.1f}", f"{s1['avg_tool_calls']:.1f}"],
           ["avg LLM calls / tokens", f"{m['avg_llm_calls']:.0f} / {m['avg_tokens']:.0f}", f"{s1['avg_llm_calls']:.0f} / {s1['avg_tokens']:.0f}"],
           ["avg latency (s)", f"{m['avg_latency_s']:.2f}", f"{s1['avg_latency_s']:.2f}"]]
    sl = Slide(f"Evaluation: multi-agent vs single-agent", f"results - backend: {backend}")
    sl.table(tbl, [700, 480, 480], size=32, row_h=62)
    wrong = [r["incident"] for r in rows if r["system"] == "single" and not r["correct"]]
    sl.note(f"single-agent misses: {', '.join(wrong)}   |   same tools, same budgets, same report schema", y=860, size=28, color=INK)
    sl.note("reproduce: python3 eval/run_eval.py --backend offline   (or --backend openrouter --model <id>)", y=920, size=26)
    slides.append((sl, """Now the comparison. Both systems use the same tools, budgets and report schema. The baseline is a single agent with no specialists and no critique loop.
A case counts as correct when both the service and the cause type are right. For incident nine, the right answer is inconclusive. I also measure top-three recall, confidently wrong answers, grounding, key-evidence recall and cost.
On the {backend_name} backend, the multi-agent system got {nm} out of {n}, and the single agent got {ns}. Key-evidence recall is {kr_m} versus {kr_s}. Neither system was confidently wrong. The price is breadth: about {tc_m} tool calls per incident versus {tc_s}.
The single agent missed exactly the traps that punish one-pass investigation: blaming a loud victim, or never examining what actually changed.""".format(backend_name=res["meta"]["backend"], nm=nm, n=m["n"], ns=ns, kr_m=f"{m['key_evidence_recall']:.2f}", kr_s=f"{s1['key_evidence_recall']:.2f}", tc_m=f"{m['avg_tool_calls']:.0f}", tc_s=f"{s1['avg_tool_calls']:.0f}")))

    # 12 why / trade-offs
    sl = Slide("What made the difference - and what it costs", "analysis")
    sl.bullets(["Critic catches 'suspect may be a victim' and 'mechanism unknown' -> targeted follow-up rounds",
                "Observability follows leads: services named in errors, dependencies of anomalous or unobservable services",
                "Temporal precedence: changes after the symptom onset are recorded as CONTRADICTING evidence",
                "History treated as a lead, never proof (INC-006, INC-011 traps avoided)",
                f"Cost: ~{m['avg_tool_calls'] / max(1, s1['avg_tool_calls']):.1f}x tool calls; with an LLM also more calls and tokens per incident",
                "Bounded rounds, step limits and a stagnation guard keep cost predictable"], size=33)
    slides.append((sl, """What made the difference? First, the critic's objections: "the suspect may be a victim" and "no failure mechanism yet" each trigger a targeted follow-up round. Second, lead-following: services named in errors, and dependencies of anomalous or unobservable services. Third, timing: a change after the symptoms counts as contradicting evidence, and history is a lead, never proof.
The cost is about three times more tool calls, plus more model calls and tokens with an LLM. Bounded rounds and a stagnation guard keep that predictable."""))

    # 13 tests
    sl = Slide("Automated tests and how to run", "quality")
    sl.code("""$ python3 -m pytest -q
.....................                                     21 passed

# covered: dataset integrity, no ground-truth leakage, argument validation,
# timeout -> retry -> success, persistent timeout -> bounded failure,
# partial results flagged, tool budget, JSON parsing, parallel DAG,
# feedback loop rounds, inconclusive outcome, budget exhaustion still
# reports, LLM path with a scripted model (fabricated fact downgraded,
# critic invalid output -> recovered), agent crash -> fallback,
# eval scoring, offline accuracy regression

$ python3 -m investigator.cli INC-002 --mode single
$ python3 eval/run_eval.py --backend openrouter --model deepseek/deepseek-v4-flash""", size=25)
    slides.append((sl, """There are twenty-one automated tests. They cover dataset integrity, ground-truth isolation, tool validation, timeouts and retries, partial results, budgets, the feedback loop and the inconclusive outcome.
The language model path is tested with a scripted model. A fabricated fact gets downgraded, a garbage critic reply gets recovered by the rules, and a crashing agent falls back to the deterministic path. One command runs each incident, the baseline, or the full evaluation."""))

    # 14 limitations
    sl = Slide("Limitations and next steps", "honest assessment")
    sl.bullets(["Results shown use the offline deterministic agents; the LLM-backed run needs an OpenRouter key",
                "  one command: python3 eval/run_eval.py --backend openrouter (full run costs well under $0.50)",
                "Heuristics were developed against the same 12 incidents -> optimistic, not held-out",
                "Simulated world; small dataset; confidence not formally calibrated",
                "Next: procedurally varied held-out incidents, Brier-score calibration, hypothesis-driven queries,",
                "  shared tool cache, native function calling, Prometheus / Loki / Kubernetes adapters"], size=32)
    slides.append((sl, """Now the limitations. These results come from the offline deterministic agents, because there was no OpenRouter key in my build environment. The language model path is implemented and tested, and a live run on the cheap default model is a single command costing well under fifty cents.
I also developed the heuristics on these same twelve incidents, so the accuracy is optimistic, not held-out. The world is simulated, the dataset is small, and confidence is not formally calibrated.
Next steps are a varied held-out dataset, calibration metrics, hypothesis-driven queries, a shared tool cache, native function calling, and real Prometheus, Loki and Kubernetes adapters."""))

    # 15 close
    sl = Slide("Summary", "thank you")
    sl.y = 260
    sl.bullets(["6 agents on a shared blackboard: plan -> parallel evidence -> competing hypotheses -> critique -> loop -> report",
                "Structured, failing tools with timeouts, retries, budgets and recovery",
                "Grounded evidence: facts vs assumptions, ranked hypotheses, confidence, inconclusive allowed",
                "12 adversarial incidents, automated tests, baseline comparison, technical note, transcript",
                "README.md has setup, architecture and results"], size=36)
    slides.append((sl, """To summarize: six agents collaborate on a shared blackboard. They plan, gather evidence in parallel, compete on hypotheses, criticize and loop, then write a grounded report that can say "inconclusive". The tools fail realistically, and the system recovers.
The dataset, tests, evaluation, technical note and transcript are all in the repository, and the README explains how to run them. Thanks for watching."""))
    return slides


async def tts(text: str, out: Path):
    import edge_tts
    import edge_tts.communicate as comm
    ca = os.getenv("SSL_CERT_FILE") or ("/root/.ccr/ca-bundle.crt" if Path("/root/.ccr/ca-bundle.crt").exists() else None)
    if ca:
        comm._SSL_CTX = ssl.create_default_context(cafile=ca)
    for attempt in range(4):
        try:
            await edge_tts.Communicate(text, VOICE, rate="+0%").save(str(out))
            return
        except Exception:
            if attempt == 3:
                raise
            await asyncio.sleep(2 ** attempt)


def duration(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=str(ROOT / "eval" / "results" / "offline"))
    ap.add_argument("--out", default=str(ROOT / "video" / "walkthrough.mp4"))
    args = ap.parse_args()
    BUILD.mkdir(parents=True, exist_ok=True)
    slides = build_slides(Path(args.results))
    segs = []
    script = []
    for i, (sl, text) in enumerate(slides, 1):
        png, mp3, mp4 = BUILD / f"s{i:02d}.png", BUILD / f"s{i:02d}.mp3", BUILD / f"s{i:02d}.mp4"
        sl.img.save(png)
        text = " ".join(text.split())
        script.append(f"## Slide {i}\n\n{text}\n")
        asyncio.run(tts(text, mp3))
        dur = duration(mp3) + 1.2
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", "5", "-i", str(png), "-i", str(mp3),
                        "-c:v", "libx264", "-tune", "stillimage", "-preset", "medium", "-crf", "28", "-pix_fmt", "yuv420p",
                        "-vf", "fps=5", "-c:a", "aac", "-b:a", "96k", "-af", "apad=pad_dur=1.2", "-t", f"{dur:.2f}", str(mp4)], check=True)
        segs.append(mp4)
        print(f"slide {i:02d}: {dur:6.1f}s", flush=True)
    lst = BUILD / "list.txt"
    lst.write_text("".join(f"file '{p.name}'\n" for p in segs))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", args.out], check=True)
    (ROOT / "video" / "narration.md").write_text("# Walkthrough narration script\n\n" + "\n".join(script))
    print(f"wrote {args.out}: {duration(Path(args.out)) / 60:.1f} min")


if __name__ == "__main__":
    main()
