"""HTTP backend for the incident investigator (standard library only).

  python3 -m server.app [--port 8000]      then open http://localhost:8000

Endpoints
  GET /api/health                       service status, LLM backend availability
  GET /api/incidents                    incident list (public fields only - never ground truth)
  GET /api/incidents/<id>               one incident + service dependency graph + data volumes
  GET /api/investigate?incident=&mode=multi|single&backend=offline|openrouter&pace_ms=
                                        Server-Sent Events: live task / tool / evidence / hypothesis /
                                        critique events, then the final report
  GET /api/runs                         recent runs (in memory)
  GET /api/runs/<run_id>                full report of a run
  GET /api/runs/<run_id>/score          score a finished run against ground truth (evaluation only)
  GET /api/eval                         available evaluation result sets
  GET /api/eval/<label>                 evaluation results (multi vs single)
  GET /api/logs                         Server-Sent Events: live backend log
  GET /                                 the web frontend (web/)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import mimetypes
import queue
import sys
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eval.run_eval import score  # noqa: E402
from investigator.agents.orchestrator import investigate  # noqa: E402
from investigator.baseline import investigate_single  # noqa: E402
from investigator.config import Settings  # noqa: E402
from investigator.llm import LLMError, make_client  # noqa: E402
from investigator.report import to_markdown  # noqa: E402
from investigator.tools import World  # noqa: E402

WEB = ROOT / "web"
INCIDENTS = ROOT / "data" / "incidents"
GROUND_TRUTH = ROOT / "data" / "ground_truth"
RESULTS = ROOT / "eval" / "results"


# ---------------------------------------------------------------------------
# Backend log: ring buffer + live subscribers (streamed to the UI's console)
# ---------------------------------------------------------------------------
class LogHub:
    def __init__(self, size: int = 400):
        self.buf: deque = deque(maxlen=size)
        self.subs: list[queue.Queue] = []
        self.lock = threading.Lock()

    def write(self, level: str, source: str, msg: str) -> None:
        line = {"ts": datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3], "level": level, "source": source, "msg": msg}
        print(f"{line['ts']} {level:<5} {source:<12} {msg}", flush=True)
        with self.lock:
            self.buf.append(line)
            for q in self.subs:
                q.put(line)

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self.lock:
            for line in self.buf:
                q.put(line)
            self.subs.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self.lock:
            if q in self.subs:
                self.subs.remove(q)


LOG = LogHub()
RUNS: dict[str, dict] = {}
_world_cache: dict[str, World] = {}


def load_world(inc_id: str) -> World:
    if inc_id not in _world_cache:
        path = INCIDENTS / f"{inc_id}.json"
        if not path.exists() or "/" in inc_id or ".." in inc_id:
            raise KeyError(inc_id)
        _world_cache[inc_id] = World.load(path)
    return _world_cache[inc_id]


def incident_ids() -> list[str]:
    return sorted(p.stem for p in INCIDENTS.glob("*.json"))


def backend_status() -> dict:
    s = Settings()
    return {"offline": True, "openrouter": bool(s.api_key), "default": s.backend, "model": s.model,
            "fallback_models": s.fallback_models}


def summarize_trace(entry: dict) -> str | None:
    """One backend log line per interesting agent event."""
    ev, actor = entry.get("event"), entry.get("actor")
    if ev == "tool_call":
        status = "ok" if entry.get("ok") else f"FAILED ({entry.get('error')})"
        extra = f" attempts={entry['attempts']}" if entry.get("attempts", 1) > 1 else ""
        extra += " INCOMPLETE" if entry.get("incomplete") else ""
        args = ",".join(f"{k}={v}" for k, v in (entry.get("args") or {}).items() if k in ("service", "level", "metric", "query"))
        return f"{entry['call']} {actor} -> {entry['tool']}({args}) {status}{extra}"
    if ev == "dispatch":
        return f"orchestrator dispatch {entry['tasks']} (parallel={entry['parallel']})"
    if ev == "llm_call":
        return f"{actor} LLM {entry.get('model')} tokens={entry.get('prompt_tokens', 0) + entry.get('completion_tokens', 0)}"
    if ev in ("agent_fallback", "plan_fallback"):
        return f"{actor} recovery: deterministic fallback ({entry.get('reason', '')[:90]})"
    if ev == "critique":
        return f"critic verdict={entry.get('verdict')} follow_ups={entry.get('follow_ups')}"
    if ev == "feedback_loop":
        return f"orchestrator feedback loop -> round {entry.get('round')} tasks={entry.get('new_tasks')}"
    if ev == "hypotheses":
        top = (entry.get("ranked") or [[None, None, None, 0]])[0]
        return f"reasoning ranked {len(entry.get('ranked') or [])} hypotheses; top={top[2]}@{top[1]} conf={top[3]}"
    if ev == "task_failed":
        return f"task {entry.get('task')} failed: {entry.get('error')}"
    return None


# ---------------------------------------------------------------------------
# Investigation runner (background thread -> queue -> SSE)
# ---------------------------------------------------------------------------
def start_run(inc_id: str, mode: str, backend: str) -> tuple[str, queue.Queue]:
    world = load_world(inc_id)
    run_id = uuid.uuid4().hex[:8]
    q: queue.Queue = queue.Queue()
    settings = Settings()
    settings.backend = backend
    RUNS[run_id] = {"run_id": run_id, "incident": inc_id, "mode": mode, "backend": backend, "status": "running",
                    "started": time.time(), "report": None}
    LOG.write("INFO", "api", f"run {run_id}: {mode}-agent investigation of {inc_id} (backend={backend})")

    def listener(event: dict) -> None:
        q.put(event)

    def work() -> None:
        try:
            llm = make_client(settings)
            fn = investigate if mode == "multi" else investigate_single
            report = asyncio.run(fn(world, settings, llm, listener=listener))
            RUNS[run_id].update(status="done", report=report, finished=time.time())
            q.put({"kind": "report", "run_id": run_id, "report": report, "markdown": to_markdown(report)})
        except (LLMError, Exception) as e:  # surface any failure to the client instead of hanging
            RUNS[run_id].update(status="error", error=str(e))
            LOG.write("ERROR", f"run {run_id}", f"{type(e).__name__}: {e}")
            q.put({"kind": "error", "message": f"{type(e).__name__}: {e}"})
        finally:
            q.put(None)

    threading.Thread(target=work, daemon=True).start()
    return run_id, q


PACED = {"task", "evidence", "hypotheses", "critique"}


class Handler(BaseHTTPRequestHandler):
    server_version = "IncidentInvestigator/1.0"

    def log_message(self, fmt, *args):  # route http.server access logs into the hub
        if not self.path.startswith("/static"):
            LOG.write("INFO", "http", f"{self.command} {self.path.split('?')[0]} {args[1] if len(args) > 1 else ''}")

    # --- helpers -------------------------------------------------------------
    def send_json(self, obj, status: int = 200) -> None:
        body = json.dumps(obj, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path) -> None:
        if not path.is_file():
            return self.send_json({"error": "not found"}, 404)
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def sse_start(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def sse(self, obj) -> None:
        self.wfile.write(f"data: {json.dumps(obj, default=str)}\n\n".encode())
        self.wfile.flush()

    # --- routing -------------------------------------------------------------
    def do_GET(self):  # noqa: C901
        url = urlparse(self.path)
        parts = [p for p in url.path.split("/") if p]
        qs = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            if not parts:
                return self.send_file(WEB / "index.html")
            if parts[0] == "static":
                target = (WEB / "/".join(parts[1:])).resolve()
                if WEB.resolve() not in target.parents:
                    return self.send_json({"error": "forbidden"}, 403)
                return self.send_file(target)
            if parts[0] != "api":
                return self.send_json({"error": "not found"}, 404)
            route = parts[1] if len(parts) > 1 else ""
            if route == "health":
                return self.send_json({"status": "ok", "incidents": len(incident_ids()), "backends": backend_status(),
                                       "runs": len(RUNS)})
            if route == "incidents" and len(parts) == 2:
                out = []
                for i in incident_ids():
                    inc = load_world(i).incident
                    out.append({k: inc[k] for k in ("id", "title", "severity", "reported_service", "symptom_onset")})
                return self.send_json(out)
            if route == "incidents" and len(parts) == 3:
                w = load_world(parts[2])
                d = w.data
                return self.send_json({"incident": w.public_incident(), "dependencies": d["dependencies"],
                                       "window": d["window"],
                                       "volumes": {"logs": len(d["logs"]), "deployments": len(d["deployments"]),
                                                   "config_changes": len(d["config_changes"]), "history": len(d["history"]),
                                                   "metric_series": sum(len(v) for v in d["metrics"].values())}})
            if route == "investigate":
                return self.investigate(qs)
            if route == "runs" and len(parts) == 2:
                return self.send_json([{k: v for k, v in r.items() if k != "report"} for r in RUNS.values()][-30:])
            if route == "runs" and len(parts) >= 3:
                run = RUNS.get(parts[2])
                if not run:
                    return self.send_json({"error": "unknown run"}, 404)
                if len(parts) == 4 and parts[3] == "score":
                    if not run.get("report"):
                        return self.send_json({"error": "run not finished"}, 409)
                    gt = json.loads((GROUND_TRUTH / f"{run['incident']}.json").read_text())
                    LOG.write("INFO", "eval", f"scoring run {run['run_id']} ({run['incident']}) against ground truth")
                    return self.send_json({"score": score(run["report"], gt), "ground_truth": gt})
                return self.send_json(run)
            if route == "eval" and len(parts) == 2:
                return self.send_json(sorted(p.parent.name for p in RESULTS.glob("*/results.json")))
            if route == "eval" and len(parts) == 3:
                path = RESULTS / parts[2] / "results.json"
                if parts[2].startswith(".") or not path.exists():
                    return self.send_json({"error": "unknown result set"}, 404)
                return self.send_json(json.loads(path.read_text()))
            if route == "logs":
                return self.stream_logs()
            return self.send_json({"error": "not found"}, 404)
        except KeyError as e:
            return self.send_json({"error": f"unknown id {e}"}, 404)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def investigate(self, qs: dict) -> None:
        inc = qs.get("incident", "")
        mode = qs.get("mode", "multi")
        backend = qs.get("backend", "offline")
        pace = max(0, min(2000, int(qs.get("pace_ms", "0") or 0))) / 1000
        if mode not in ("multi", "single") or backend not in ("offline", "openrouter"):
            return self.send_json({"error": "bad mode/backend"}, 400)
        if backend == "openrouter" and not backend_status()["openrouter"]:
            return self.send_json({"error": "OPENROUTER_API_KEY is not configured on the server"}, 400)
        load_world(inc)  # 404 early on unknown incidents
        run_id, q = start_run(inc, mode, backend)
        self.sse_start()
        self.sse({"kind": "start", "run_id": run_id, "incident": inc, "mode": mode, "backend": backend})
        try:
            while True:
                ev = q.get()
                if ev is None:
                    break
                self.sse(ev)
                self.log_event(run_id, ev)
                # Offline runs finish in well under a second; pacing replays them at a watchable speed.
                if pace and ev["kind"] in PACED or (pace and ev["kind"] == "trace" and ev["entry"]["event"] in ("tool_call", "dispatch")):
                    time.sleep(pace if ev["kind"] in PACED else pace / 3)
            self.sse({"kind": "end", "run_id": run_id})
        except (BrokenPipeError, ConnectionResetError):
            LOG.write("WARN", "api", f"client disconnected from run {run_id}")

    @staticmethod
    def log_event(run_id: str, ev: dict) -> None:
        """Backend log line per streamed event (so the console stays in step with what the client sees)."""
        if ev["kind"] == "trace":
            line = summarize_trace(ev["entry"])
            if line:
                LOG.write("WARN" if "FAILED" in line or "recovery" in line else "INFO", f"run {run_id}", line)
        elif ev["kind"] == "report":
            r = ev["report"]
            rc = r["root_cause"]
            LOG.write("INFO", f"run {run_id}", f"finished: {r['outcome']} "
                      f"{(rc['cause_type'] + '@' + rc['service']) if rc else ''} in {r['investigation']['latency_s']}s compute, "
                      f"{r['investigation']['tool_calls']} tool calls, {r['investigation']['llm_calls']} LLM calls")

    def stream_logs(self) -> None:
        q = LOG.subscribe()
        self.sse_start()
        try:
            while True:
                try:
                    line = q.get(timeout=15)
                    self.sse(line)
                except queue.Empty:
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            LOG.unsubscribe(q)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    httpd.daemon_threads = True
    b = backend_status()
    LOG.write("INFO", "server", f"listening on http://{args.host}:{args.port}  incidents={len(incident_ids())}  "
              f"backends: offline=yes openrouter={'yes (' + b['model'] + ')' if b['openrouter'] else 'no key'}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        LOG.write("INFO", "server", "shutting down")


if __name__ == "__main__":
    main()
