"""Investigation tools over a simulated incident world.

Every tool has a declared input schema, returns structured JSON, and can fail:
  * scripted faults from the incident file (timeout / partial / error), and
  * random transient faults (`chaos_rate`) to exercise recovery paths.
`ToolExecutor` adds validation, per-call timeouts, bounded retries with backoff,
budget enforcement and records every call on the shared state.
"""
from __future__ import annotations

import asyncio
import json
import random
import re
import statistics
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .state import BudgetExceeded, InvestigationState, ToolCall

TOOL_SPECS: dict[str, dict] = {
    "query_logs": {
        "description": "Search service logs. Returns per-message counts (with first/last seen and an example record id) and a sample of matching records.",
        "params": {"service": {"type": "string", "required": True},
                   "level": {"type": "string", "enum": ["DEBUG", "INFO", "WARN", "ERROR"]},
                   "contains": {"type": "string"},
                   "start": {"type": "string", "desc": "ISO-8601 UTC, default = data window start"},
                   "end": {"type": "string"},
                   "limit": {"type": "integer", "default": 20}},
    },
    "query_metrics": {
        "description": "Metric summaries for a service: baseline (first hour of window) vs recent mean, peak, change ratio and first anomaly timestamp. Omit `metric` to get all metrics of the service.",
        "params": {"service": {"type": "string", "required": True}, "metric": {"type": "string"},
                   "start": {"type": "string"}, "end": {"type": "string"},
                   "include_points": {"type": "boolean", "default": False}},
    },
    "get_deployments": {
        "description": "Deployment history (optionally for one service) within a time range.",
        "params": {"service": {"type": "string"}, "start": {"type": "string"}, "end": {"type": "string"}},
    },
    "get_config_changes": {
        "description": "Configuration / feature-flag change history within a time range.",
        "params": {"service": {"type": "string"}, "start": {"type": "string"}, "end": {"type": "string"}},
    },
    "get_service_dependencies": {
        "description": "Service dependency graph: what a service calls (downstream) and what calls it (upstream). service='*' lists all services.",
        "params": {"service": {"type": "string", "required": True},
                   "direction": {"type": "string", "enum": ["downstream", "upstream", "both"], "default": "both"}},
    },
    "search_incident_history": {
        "description": "Keyword search over past incident post-mortems. Similar symptoms do NOT imply the same cause.",
        "params": {"query": {"type": "string", "required": True}, "limit": {"type": "integer", "default": 3}},
    },
}


class ToolFailure(Exception):
    def __init__(self, code: str, message: str, retryable: bool = True):
        super().__init__(message)
        self.code, self.retryable = code, retryable


def tool_catalog(names: list[str] | None = None) -> str:
    out = []
    for name, spec in TOOL_SPECS.items():
        if names and name not in names:
            continue
        params = ", ".join(f"{p}: {d['type']}{'' if d.get('required') else '?'}"
                           + (f" one of {d['enum']}" if "enum" in d else "") for p, d in spec["params"].items())
        out.append(f"- {name}({params}): {spec['description']}")
    return "\n".join(out)


def _parse_ts(value: str) -> datetime:
    value = value.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def collect_ids(obj: Any) -> list[str]:
    """Every dataset record id that appears in a tool result (what agents may cite)."""
    found: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("id", "example_id", "metric_id") and isinstance(v, str):
                found.append(v)
            else:
                found.extend(collect_ids(v))
    elif isinstance(obj, list):
        for v in obj:
            found.extend(collect_ids(v))
    return found


class World:
    def __init__(self, data: dict):
        self.data = data
        self.incident = data["incident"]
        self.window_start = _parse_ts(data["window"]["start"])
        self.window_end = _parse_ts(data["window"]["end"])
        self.onset = _parse_ts(self.incident["symptom_onset"])
        self.services = sorted(data["dependencies"])

    @classmethod
    def load(cls, path: str | Path) -> "World":
        return cls(json.loads(Path(path).read_text()))

    def public_incident(self) -> dict:
        """What the investigators are told (no ground truth lives in the world file anyway)."""
        return dict(self.incident)


class ToolBox:
    """Pure tool implementations + fault injection."""

    def __init__(self, world: World, chaos_rate: float = 0.0, seed: int = 0, hang_s: float = 2.0):
        self.w = world
        self.rng = random.Random(seed)
        self.chaos_rate = chaos_rate
        self.hang_s = hang_s
        self.fault_hits: dict[str, int] = {}

    # --- faults --------------------------------------------------------------
    def _scripted_fault(self, tool: str, args: dict) -> str | None:
        f = self.w.data.get("faults", {}).get(tool)
        if not f:
            return None
        svc = args.get("service") or "*"
        if "*" not in f["services"] and svc not in f["services"]:
            return None
        key = f"{tool}:{svc}"
        hits = self.fault_hits.get(key, 0)
        if hits >= f["times"]:
            return None
        self.fault_hits[key] = hits + 1
        return f["mode"]

    async def invoke(self, tool: str, args: dict) -> dict:
        mode = self._scripted_fault(tool, args)
        if mode is None and self.rng.random() < self.chaos_rate:
            mode = self.rng.choice(["timeout", "error"])
        if mode == "timeout":
            await asyncio.sleep(self.hang_s)  # executor's timeout fires first
        if mode == "error":
            raise ToolFailure("backend_error", f"{tool}: upstream datastore returned HTTP 503")
        await asyncio.sleep(0.005 + self.rng.random() * 0.01)  # simulated I/O latency
        result = getattr(self, tool)(**args)
        if mode == "partial":
            result = self._degrade(result)
        return result

    def _degrade(self, result: dict) -> dict:
        result = json.loads(json.dumps(result))
        result["incomplete"] = True
        result["warning"] = "partial results: backend shard unavailable; data may be missing"
        if "records" in result:
            result["records"] = result["records"][: max(1, len(result["records"]) // 4)]
            result["message_counts"] = result.get("message_counts", [])[:2]
        if "metrics" in result:
            for m in result["metrics"]:
                m["recent_mean"] = None
                m["first_anomaly_ts"] = None
                m["note"] = "recent datapoints missing"
        return result

    # --- helpers ---------------------------------------------------------------
    def _range(self, start: str | None, end: str | None) -> tuple[datetime, datetime]:
        try:
            s = _parse_ts(start) if start else self.w.window_start
            e = _parse_ts(end) if end else self.w.window_end
        except ValueError as exc:
            raise ToolFailure("invalid_argument", f"bad timestamp: {exc}", retryable=False)
        if e < s:
            raise ToolFailure("invalid_argument", "end before start", retryable=False)
        return s, e

    def _check_service(self, service: str, allow_star: bool = False):
        if allow_star and service == "*":
            return
        if service not in self.w.data["dependencies"]:
            raise ToolFailure("not_found", f"unknown service '{service}'. Known: {', '.join(self.w.services)}", retryable=False)

    # --- tools -----------------------------------------------------------------
    def query_logs(self, service: str, level: str | None = None, contains: str | None = None,
                   start: str | None = None, end: str | None = None, limit: int = 20) -> dict:
        self._check_service(service)
        s, e = self._range(start, end)
        limit = max(1, min(int(limit), 50))
        rows = []
        for r in self.w.data["logs"]:
            if r["service"] != service:
                continue
            if level and r["level"] != level:
                continue
            if contains and contains.lower() not in r["message"].lower():
                continue
            ts = _parse_ts(r["ts"])
            if s <= ts <= e:
                rows.append(r)
        counts: dict[str, dict] = {}
        for r in rows:
            c = counts.setdefault(r["message"], {"message": r["message"], "level": r["level"], "count": 0,
                                                 "first_seen": r["ts"], "last_seen": r["ts"], "example_id": r["id"]})
            c["count"] += 1
            c["last_seen"] = r["ts"]
        top = sorted(counts.values(), key=lambda c: (-c["count"], c["first_seen"]))[:8]
        # Sample: earliest records matter most for onset analysis; also include the latest few.
        sample = rows[: limit // 2] + rows[-(limit - limit // 2):] if len(rows) > limit else rows
        return {"service": service, "matched": len(rows), "truncated": len(rows) > limit,
                "message_counts": top, "records": sample}

    def query_metrics(self, service: str, metric: str | None = None, start: str | None = None,
                      end: str | None = None, include_points: bool = False) -> dict:
        self._check_service(service)
        s, e = self._range(start, end)
        series = self.w.data["metrics"][service]
        if metric and metric not in series:
            raise ToolFailure("not_found", f"unknown metric '{metric}' for {service}. Available: {', '.join(series)}", retryable=False)
        out = []
        for name in ([metric] if metric else list(series)):
            pts = [p for p in series[name]["points"] if s <= _parse_ts(p["ts"]) <= e]
            base_pts = [p["value"] for p in series[name]["points"]
                        if _parse_ts(p["ts"]) < self.w.window_start + timedelta(minutes=60)]
            base = statistics.mean(base_pts)
            sd = statistics.pstdev(base_pts) or 1e-6
            recent = [p["value"] for p in pts if _parse_ts(p["ts"]) >= self.w.onset]
            first_anom = None
            vals = [(p["ts"], p["value"]) for p in pts]
            for i in range(len(vals) - 1):
                a, b = vals[i][1], vals[i + 1][1]
                if all(abs(v - base) > max(4 * sd, 0.15 * abs(base)) for v in (a, b)):
                    first_anom = vals[i][0]
                    break
            rec = {"metric_id": series[name]["id"], "metric": name, "baseline_mean": round(base, 2),
                   "recent_mean": round(statistics.mean(recent), 2) if recent else None,
                   "max": max((v for _, v in vals), default=None), "min": min((v for _, v in vals), default=None),
                   "change_ratio": round(statistics.mean(recent) / base, 2) if recent and base else None,
                   "first_anomaly_ts": first_anom}
            if include_points:
                rec["points"] = [p for i, p in enumerate(pts) if i % 3 == 0]
            out.append(rec)
        return {"service": service, "metrics": out}

    def _events(self, kind: str, service: str | None, start: str | None, end: str | None) -> dict:
        if service:
            self._check_service(service)
        s, e = self._range(start, end)
        rows = [r for r in self.w.data[kind] if (not service or r["service"] == service) and s <= _parse_ts(r["ts"]) <= e]
        return {kind: rows, "count": len(rows), "range": {"start": _iso(s), "end": _iso(e)}}

    def get_deployments(self, service: str | None = None, start: str | None = None, end: str | None = None) -> dict:
        return self._events("deployments", service, start, end)

    def get_config_changes(self, service: str | None = None, start: str | None = None, end: str | None = None) -> dict:
        return self._events("config_changes", service, start, end)

    def get_service_dependencies(self, service: str, direction: str = "both") -> dict:
        deps = self.w.data["dependencies"]
        if service == "*":
            return {"services": self.w.services, "edges": deps}
        self._check_service(service)
        res: dict = {"service": service}
        if direction in ("downstream", "both"):
            res["downstream"] = deps[service]
        if direction in ("upstream", "both"):
            res["upstream"] = sorted(s for s, d in deps.items() if service in d)
        return res

    def search_incident_history(self, query: str, limit: int = 3) -> dict:
        terms = {t for t in re.findall(r"[a-z0-9\-]+", query.lower()) if len(t) > 2}
        scored = []
        for h in self.w.data["history"]:
            text = " ".join([h["title"], h["symptoms"], " ".join(h["services"])]).lower()
            score = sum(1 for t in terms if t in text)
            if score:
                scored.append((score, h))
        scored.sort(key=lambda x: -x[0])
        return {"query": query, "results": [dict(h, match_score=s) for s, h in scored[: max(1, min(int(limit), 5))]],
                "note": "historical similarity is a lead, not proof"}


def validate_args(tool: str, args: Any) -> dict:
    if tool not in TOOL_SPECS:
        raise ToolFailure("unknown_tool", f"unknown tool '{tool}'. Available: {', '.join(TOOL_SPECS)}", retryable=False)
    if not isinstance(args, dict):
        raise ToolFailure("invalid_argument", "args must be an object", retryable=False)
    spec = TOOL_SPECS[tool]["params"]
    clean = {}
    for k, v in args.items():
        if k not in spec:
            continue  # tolerate extra keys from the model, drop them
        d = spec[k]
        if v is None:
            continue
        if d["type"] == "integer":
            try:
                v = int(v)
            except (TypeError, ValueError):
                raise ToolFailure("invalid_argument", f"{k} must be an integer", retryable=False)
        elif d["type"] == "boolean":
            v = bool(v) if not isinstance(v, str) else v.lower() == "true"
        elif not isinstance(v, str):
            v = str(v)
        if "enum" in d and v not in d["enum"]:
            raise ToolFailure("invalid_argument", f"{k} must be one of {d['enum']}", retryable=False)
        clean[k] = v
    missing = [k for k, d in spec.items() if d.get("required") and k not in clean]
    if missing:
        raise ToolFailure("invalid_argument", f"missing required argument(s): {missing}", retryable=False)
    return clean


class ToolExecutor:
    def __init__(self, toolbox: ToolBox, state: InvestigationState, timeout_s: float = 0.3, retries: int = 2):
        self.tb = toolbox
        self.state = state
        self.timeout_s = timeout_s
        self.retries = retries

    async def run(self, agent: str, tool: str, args: dict | None) -> ToolCall:
        args = args or {}
        call_id = self.state.next_tool_id()
        t0 = time.monotonic()
        call = ToolCall(call_id, agent, tool, args, ok=False, attempts=0, latency_ms=0.0)
        self.state.tool_calls.append(call)  # reserve the id immediately (parallel calls)
        try:
            clean = validate_args(tool, args)
        except ToolFailure as f:
            call.error, call.latency_ms = f"{f.code}: {f}", 0.0
            self.state.log(agent, "tool_error", call=call_id, tool=tool, error=call.error)
            return call
        call.args = clean
        last = None
        for attempt in range(self.retries + 1):
            try:
                self.state.budget.check("tool")
            except BudgetExceeded as b:
                call.error = f"budget_exceeded: {b}"
                break
            self.state.budget.tool_calls += 1
            call.attempts = attempt + 1
            try:
                result = await asyncio.wait_for(self.tb.invoke(tool, clean), timeout=self.timeout_s)
                call.ok, call.result = True, result
                call.incomplete = bool(result.get("incomplete"))
                call.record_ids = collect_ids(result)
                call.error = None
                break
            except asyncio.TimeoutError:
                last = ToolFailure("timeout", f"{tool} timed out after {self.timeout_s}s")
            except ToolFailure as f:
                last = f
            call.error = f"{last.code}: {last}"
            if not last.retryable:
                break
            await asyncio.sleep(0.02 * 2 ** attempt)  # bounded exponential backoff
        call.latency_ms = round((time.monotonic() - t0) * 1000, 1)
        self.state.log(agent, "tool_call", call=call_id, tool=tool, args=clean, ok=call.ok, attempts=call.attempts,
                       error=call.error, incomplete=call.incomplete)
        return call

    async def run_many(self, agent: str, calls: list[tuple[str, dict]]) -> list[ToolCall]:
        return list(await asyncio.gather(*(self.run(agent, t, a) for t, a in calls)))


def observation(call: ToolCall, max_chars: int = 3500) -> dict:
    """Compact view of a tool call for an LLM prompt."""
    if not call.ok:
        return {"call_id": call.id, "tool": call.tool, "args": call.args, "ok": False, "error": call.error,
                "attempts": call.attempts}
    text = json.dumps(call.result, separators=(",", ":"))
    if len(text) > max_chars:
        res = dict(call.result)
        if "records" in res:
            res["records"] = res["records"][:6]
            res["note"] = "records trimmed for context; use message_counts"
        text = json.dumps(res, separators=(",", ":"))[:max_chars]
        return {"call_id": call.id, "tool": call.tool, "args": call.args, "ok": True, "result_truncated_json": text}
    return {"call_id": call.id, "tool": call.tool, "args": call.args, "ok": True, "result": call.result}
