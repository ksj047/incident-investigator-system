"""Generate the synthetic incident dataset.

Each incident is a self-contained "world": logs, metrics, deployments, config
changes, a service dependency graph, historical incident reports and a fault
profile for the tools. Ground truth is written to a *separate* directory that
the investigation system never reads (only the evaluator does).

Run:  python scripts/generate_dataset.py
The output is deterministic (seeded), so the committed dataset can be regenerated.
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_INC = ROOT / "data" / "incidents"
OUT_GT = ROOT / "data" / "ground_truth"

DEPENDENCIES = {
    "frontend": ["api-gateway"],
    "api-gateway": ["auth-service", "orders-service", "search-service", "user-service", "recommendation-service"],
    "auth-service": ["redis-cache"],
    "user-service": ["orders-db", "redis-cache"],
    "orders-service": ["orders-db", "payment-service", "inventory-service", "notification-service"],
    "payment-service": ["payment-gateway-ext", "orders-db"],
    "inventory-service": ["product-db", "redis-cache"],
    "search-service": ["product-db", "redis-cache"],
    "recommendation-service": ["redis-cache", "user-service"],
    "notification-service": ["email-provider-ext"],
    "orders-db": [],
    "product-db": [],
    "redis-cache": [],
    "payment-gateway-ext": [],
    "email-provider-ext": [],
}

APP_METRICS = {"latency_p99_ms": 180.0, "error_rate_pct": 0.4, "cpu_pct": 35.0, "memory_pct": 52.0, "request_rate_rps": 220.0}
DB_METRICS = {"query_latency_ms": 12.0, "connections_active": 140.0, "cpu_pct": 30.0, "disk_used_pct": 61.0}
CACHE_METRICS = {"hit_rate_pct": 94.0, "evictions_per_min": 20.0, "memory_pct": 58.0, "cpu_pct": 18.0}
EXT_METRICS = {"latency_p99_ms": 300.0, "error_rate_pct": 0.2}


def metrics_for(service: str) -> dict[str, float]:
    if service.endswith("-db"):
        return dict(DB_METRICS)
    if service == "redis-cache":
        return dict(CACHE_METRICS)
    if service.endswith("-ext"):
        return dict(EXT_METRICS)
    return dict(APP_METRICS)


def iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


class World:
    """Builder for one incident world."""

    def __init__(self, inc_id: str, onset: datetime, seed: int):
        self.id = inc_id
        self.onset = onset
        self.start = onset - timedelta(hours=6)
        self.end = onset + timedelta(hours=1)
        self.rng = random.Random(seed)
        self.logs: list[dict] = []
        self.deployments: list[dict] = []
        self.config_changes: list[dict] = []
        self.history: list[dict] = []
        self.effects: list[tuple] = []  # (service, metric, start, kind, magnitude)
        self.faults: dict = {}
        self.incident: dict = {}
        self._log_n = 0

    # ---- helpers -------------------------------------------------------
    def at(self, minutes: float) -> datetime:
        return self.onset + timedelta(minutes=minutes)

    def log(self, minutes: float, service: str, level: str, message: str) -> str:
        self._log_n += 1
        lid = f"L-{self._log_n:04d}"
        self.logs.append({"id": lid, "ts": iso(self.at(minutes)), "service": service, "level": level, "message": message})
        return lid

    def burst(self, start_min: float, end_min: float, every: float, service: str, level: str, messages: list[str]) -> list[str]:
        ids, m = [], start_min
        while m <= end_min:
            ids.append(self.log(m + self.rng.uniform(0, every * 0.8), service, level, self.rng.choice(messages)))
            m += every
        return ids

    def deploy(self, minutes: float, service: str, version: str, summary: str, author: str = "ci-bot") -> str:
        did = f"D-{len(self.deployments) + 1:03d}"
        self.deployments.append({"id": did, "ts": iso(self.at(minutes)), "service": service, "version": version,
                                 "author": author, "change_summary": summary, "status": "succeeded"})
        return did

    def config(self, minutes: float, service: str, key: str, old, new, author: str, ticket: str = "") -> str:
        cid = f"C-{len(self.config_changes) + 1:03d}"
        self.config_changes.append({"id": cid, "ts": iso(self.at(minutes)), "service": service, "key": key,
                                    "old_value": old, "new_value": new, "author": author, "ticket": ticket})
        return cid

    def past(self, days_ago: int, title: str, services: list[str], symptoms: str, root_cause: str, resolution: str) -> str:
        hid = f"H-{len(self.history) + 1:03d}"
        self.history.append({"id": hid, "date": iso(self.onset - timedelta(days=days_ago)), "title": title,
                             "services": services, "symptoms": symptoms, "root_cause": root_cause, "resolution": resolution})
        return hid

    def effect(self, service: str, metric: str, start_min: float, kind: str, magnitude: float):
        """kind: step (multiply), ramp (linear growth to magnitude x by onset+60), set (absolute value), cap."""
        self.effects.append((service, metric, start_min, kind, magnitude))

    # ---- background -----------------------------------------------------
    def background(self):
        services = [s for s in DEPENDENCIES if not s.endswith("-ext")]
        minutes = -360
        while minutes <= 60:
            for s in services:
                if self.rng.random() < 0.35:
                    self.log(minutes + self.rng.uniform(0, 9), s, "INFO", self.rng.choice([
                        "request batch served ok", "health check passed", "gc pause 12ms",
                        "cache warmup complete", "metrics flushed", "connection pool stats ok"]))
                if self.rng.random() < 0.03:
                    self.log(minutes + self.rng.uniform(0, 9), s, "WARN", self.rng.choice([
                        "slow request detected (>1s)", "retrying idempotent call (attempt 2)",
                        "deprecated api version used by client"]))
                if self.rng.random() < 0.01:
                    self.log(minutes + self.rng.uniform(0, 9), s, "ERROR", self.rng.choice([
                        "client disconnected before response", "request validation failed: missing field"]))
            minutes += 10
        # Routine history every world shares (noise for the history search).
        self.past(41, "Search latency after index rebuild", ["search-service", "product-db"],
                  "search p99 latency elevated", "nightly index rebuild overlapped with peak traffic", "moved rebuild window")
        self.past(97, "Email delivery delays", ["notification-service", "email-provider-ext"],
                  "notification emails delayed by 30 minutes", "email provider throttling", "raised provider quota")

    def build_metrics(self) -> dict:
        out: dict = {}
        steps = int((self.end - self.start).total_seconds() // 300) + 1
        for svc in DEPENDENCIES:
            out[svc] = {}
            for metric, base in metrics_for(svc).items():
                pts = []
                for i in range(steps):
                    t = self.start + timedelta(minutes=5 * i)
                    rel = (t - self.onset).total_seconds() / 60
                    v = base * (1 + self.rng.gauss(0, 0.04))
                    for (s, m, st, kind, mag) in self.effects:
                        if s != svc or m != metric or rel < st:
                            continue
                        if kind == "step":
                            v = v * mag
                        elif kind == "ramp":
                            frac = min(1.0, (rel - st) / max(1.0, 60 - st))
                            v = v * (1 + (mag - 1) * frac)
                        elif kind == "set":
                            v = mag * (1 + self.rng.gauss(0, 0.01))
                        elif kind == "cap":
                            v = min(v, mag)
                    if metric.endswith("_pct"):
                        v = max(0.0, min(100.0, v))
                    pts.append({"ts": iso(t), "value": round(v, 2)})
                out[svc][metric] = {"id": f"M-{svc}-{metric}", "points": pts}
        return out

    def dump(self, gt: dict):
        self.logs.sort(key=lambda r: r["ts"])
        world = {
            "incident": self.incident,
            "window": {"start": iso(self.start), "end": iso(self.end)},
            "dependencies": DEPENDENCIES,
            "logs": self.logs,
            "metrics": self.build_metrics(),
            "deployments": sorted(self.deployments, key=lambda d: d["ts"]),
            "config_changes": sorted(self.config_changes, key=lambda d: d["ts"]),
            "history": self.history,
            "faults": self.faults,
        }
        (OUT_INC / f"{self.id}.json").write_text(json.dumps(world, separators=(",", ":")))
        gt = {"incident_id": self.id, **gt}
        (OUT_GT / f"{self.id}.json").write_text(json.dumps(gt, indent=2))


def new(inc_id: str, day: int, hour: int, title: str, reported_service: str, symptoms: str, severity="SEV2", seed=0) -> World:
    onset = datetime(2026, 3, day, hour, 0, tzinfo=timezone.utc)
    w = World(inc_id, onset, seed or day * 100 + hour)
    w.incident = {"id": inc_id, "title": title, "severity": severity, "reported_service": reported_service,
                  "symptom_onset": iso(onset), "reported_at": iso(onset + timedelta(minutes=12)), "description": symptoms}
    w.background()
    return w


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

def inc001():
    w = new("INC-001", 2, 14, "Checkout requests failing with HTTP 500", "orders-service",
            "Customers report checkout failures. orders-service 5xx rate jumped from <1% to ~18% around 14:00 UTC.")
    d = w.deploy(-9, "payment-service", "v2.14.0", "Refactor PaymentMethodResolver; add wallet support")
    w.deploy(-300, "search-service", "v5.2.1", "Tune ranking weights")
    errs = w.burst(-7, 55, 2, "payment-service", "ERROR", [
        "NullPointerException in PaymentMethodResolver.resolve(PaymentMethodResolver.java:88)",
        "unhandled exception processing charge request: NullPointerException"])
    up = w.burst(-6, 55, 3, "orders-service", "ERROR", ["call to payment-service failed: HTTP 500 Internal Server Error"])
    w.effect("payment-service", "error_rate_pct", -8, "set", 22)
    w.effect("orders-service", "error_rate_pct", -6, "set", 18)
    w.past(150, "Checkout errors after payment deploy", ["payment-service"], "checkout 5xx", "bad release of payment-service", "rollback")
    w.dump({"root_cause_service": "payment-service", "cause_type": "deployment_bug", "accepted_cause_types": ["deployment_bug"],
            "expected_outcome": "conclusive", "key_evidence": [d, errs[0], "M-payment-service-error_rate_pct"],
            "traps": "none - baseline sanity case"})


def inc002():
    w = new("INC-002", 3, 10, "Order placement timeouts", "frontend",
            "Frontend shows spinner then 'Something went wrong' when placing orders. A frontend release went out minutes before.")
    red = w.deploy(-4, "frontend", "v9.8.0", "New promo banner component")
    c = w.config(-16, "orders-db", "max_connections", 500, 50, "dba-oncall", "OPS-4471 reduce memory footprint")
    db = w.burst(-14, 55, 2, "orders-db", "ERROR", ["FATAL: sorry, too many clients already (max_connections=50)"])
    app = w.burst(-13, 55, 2, "orders-service", "ERROR", [
        "connection pool exhausted: timed out after 3000ms waiting for connection to orders-db",
        "SQLTransientConnectionException: orders-db pool exhausted"])
    w.burst(-3, 55, 4, "frontend", "ERROR", ["POST /api/orders failed: 504 Gateway Timeout"])
    w.burst(-12, 55, 4, "api-gateway", "WARN", ["upstream orders-service slow: 3021ms (route POST /api/orders)"])
    w.effect("orders-db", "connections_active", -16, "cap", 50)
    w.effect("orders-service", "latency_p99_ms", -14, "step", 16)
    w.effect("orders-service", "error_rate_pct", -14, "set", 12)
    w.effect("frontend", "error_rate_pct", -12, "set", 6)
    w.dump({"root_cause_service": "orders-db", "cause_type": "config_change", "accepted_cause_types": ["config_change"],
            "expected_outcome": "conclusive", "key_evidence": [c, db[0], app[0], "M-orders-db-connections_active"],
            "traps": f"frontend deploy {red} right before report is a red herring"})


def inc003():
    w = new("INC-003", 5, 19, "Payments slow and timing out", "payment-service",
            "Payment authorization taking >5s; ~30% of payments time out. No payment-service deploy today.")
    w.config(-30, "notification-service", "email_template_version", "v12", "v13", "growth-team")
    errs = w.burst(-5, 55, 2, "payment-service", "ERROR", [
        "upstream timeout calling payment-gateway-ext after 5000ms",
        "payment-gateway-ext returned 503 Service Unavailable"])
    w.burst(-4, 55, 4, "orders-service", "WARN", ["payment authorization slow (>5s), customer retried"])
    w.effect("payment-gateway-ext", "latency_p99_ms", -6, "step", 18)
    w.effect("payment-gateway-ext", "error_rate_pct", -6, "set", 31)
    w.effect("payment-service", "latency_p99_ms", -5, "step", 25)
    w.effect("payment-service", "error_rate_pct", -5, "set", 29)
    h = w.past(63, "Payment gateway partial outage", ["payment-service", "payment-gateway-ext"],
               "payment timeouts, gateway 503s", "third-party gateway regional outage", "failover to secondary gateway region")
    w.faults = {"query_metrics": {"mode": "timeout", "times": 1, "services": ["payment-service"]}}
    w.dump({"root_cause_service": "payment-gateway-ext", "cause_type": "dependency_outage", "accepted_cause_types": ["dependency_outage"],
            "expected_outcome": "conclusive", "key_evidence": [errs[0], "M-payment-gateway-ext-error_rate_pct", h],
            "traps": "unrelated notification config change; first metrics call for payment-service times out"})


def inc004():
    w = new("INC-004", 8, 16, "Recommendations widget failing intermittently", "recommendation-service",
            "Homepage recommendations intermittently empty. Pods restarting. search-service deployed 10 minutes ago.")
    d = w.deploy(-310, "recommendation-service", "v3.2.0", "Add in-process embedding cache")
    red = w.deploy(-10, "search-service", "v5.3.0", "Upgrade HTTP client library")
    oom = w.burst(-40, 55, 6, "recommendation-service", "ERROR", [
        "container killed: OOMKilled (memory limit 2Gi)", "java.lang.OutOfMemoryError: Java heap space"])
    w.burst(-120, -41, 15, "recommendation-service", "WARN", ["heap usage above 85%, gc overhead high"])
    w.effect("recommendation-service", "memory_pct", -300, "ramp", 1.9)
    w.effect("recommendation-service", "error_rate_pct", -40, "set", 9)
    w.effect("recommendation-service", "latency_p99_ms", -40, "step", 3)
    w.dump({"root_cause_service": "recommendation-service", "cause_type": "resource_exhaustion",
            "accepted_cause_types": ["resource_exhaustion", "deployment_bug"],
            "expected_outcome": "conclusive", "key_evidence": [oom[0], "M-recommendation-service-memory_pct", d],
            "traps": f"recent search-service deploy {red} is a red herring; the real change is 5h old (slow leak)"})


def inc005():
    w = new("INC-005", 11, 18, "Site-wide 503 errors", "api-gateway",
            "Large fraction of requests return 503. Started right at 18:00 UTC.", severity="SEV1")
    w.deploy(-40, "auth-service", "v4.0.3", "Log format tweak")
    camp = w.log(-2, "frontend", "INFO", "campaign SPRING-FLASH-SALE push notification sent to 2.1M users")
    gw = w.burst(0, 55, 2, "api-gateway", "ERROR", [
        "upstream overloaded: returning 503 (queue depth 4096)", "rate limiter rejected request: 429 too many requests"])
    asg = w.burst(1, 55, 10, "api-gateway", "WARN", ["autoscaler: scale-up blocked, max replicas (40) reached"])
    w.effect("api-gateway", "request_rate_rps", 0, "step", 4.5)
    w.effect("frontend", "request_rate_rps", -1, "step", 4.2)
    w.effect("api-gateway", "cpu_pct", 0, "set", 97)
    w.effect("api-gateway", "error_rate_pct", 0, "set", 21)
    w.effect("api-gateway", "latency_p99_ms", 0, "step", 8)
    w.dump({"root_cause_service": "api-gateway", "cause_type": "traffic_spike", "accepted_cause_types": ["traffic_spike"],
            "expected_outcome": "conclusive", "key_evidence": [camp, gw[0], asg[0], "M-api-gateway-request_rate_rps"],
            "traps": "auth-service deploy 40m before is harmless"})


def inc006():
    w = new("INC-006", 14, 0, "Users unable to log in", "auth-service",
            "Login fails for all users since midnight UTC.", severity="SEV1")
    tls = w.burst(0, 55, 1.5, "api-gateway", "ERROR", [
        "TLS handshake with auth-service failed: x509: certificate has expired or is not yet valid",
        "upstream auth-service connect error: certificate expired (notAfter=2026-03-14T00:00:00Z)"])
    w.burst(0, 55, 5, "auth-service", "WARN", ["inbound TLS handshake failure from api-gateway"])
    w.effect("auth-service", "request_rate_rps", 0, "step", 0.05)
    w.effect("api-gateway", "error_rate_pct", 0, "set", 35)
    w.effect("redis-cache", "evictions_per_min", -20, "step", 1.6)
    trap = w.past(20, "Login failures for all users", ["auth-service", "redis-cache"],
                  "login fails for all users, sessions dropped", "redis-cache evicted session keys after maxmemory reached",
                  "increase redis maxmemory")
    w.dump({"root_cause_service": "auth-service", "cause_type": "certificate_expiry", "accepted_cause_types": ["certificate_expiry"],
            "expected_outcome": "conclusive", "key_evidence": [tls[0], "M-auth-service-request_rate_rps"],
            "traps": f"historical incident {trap} with near-identical symptoms blames redis; redis evictions mildly elevated"})


def inc007():
    w = new("INC-007", 17, 13, "Product search very slow", "search-service",
            "Search p99 latency > 4s. Product pages also slow.")
    c = w.config(-21, "redis-cache", "default_ttl_seconds", 3600, 5, "perf-team", "PERF-912 freshness experiment")
    w.effect("redis-cache", "hit_rate_pct", -20, "set", 21)
    w.effect("product-db", "cpu_pct", -19, "set", 96)
    w.effect("product-db", "query_latency_ms", -19, "step", 14)
    w.effect("search-service", "latency_p99_ms", -18, "step", 22)
    w.effect("inventory-service", "latency_p99_ms", -18, "step", 6)
    w.burst(-18, 55, 3, "product-db", "WARN", ["slow query log: 412 queries > 1s in last minute"])
    w.burst(-17, 55, 3, "search-service", "ERROR", ["product lookup timed out after 2000ms"])
    # The logs tool is broken for the most relevant services; metrics are partially truncated.
    w.faults = {"query_logs": {"mode": "timeout", "times": 99, "services": ["search-service", "redis-cache", "product-db"]},
                "query_metrics": {"mode": "partial", "times": 2, "services": ["search-service"]}}
    w.dump({"root_cause_service": "redis-cache", "cause_type": "config_change", "accepted_cause_types": ["config_change"],
            "expected_outcome": "conclusive", "key_evidence": [c, "M-redis-cache-hit_rate_pct", "M-product-db-cpu_pct"],
            "traps": "log queries for the key services always time out; must reason from metrics + config history"})


def inc008():
    w = new("INC-008", 20, 9, "Search and stock checks erroring", "search-service",
            "search-service CPU at 90%+, product search errors. Stock availability checks failing too.")
    d = w.deploy(-8, "inventory-service", "v7.1.0", "Add column warehouse_zone to products table (online migration)")
    lock = w.burst(-7, 55, 2, "product-db", "ERROR", [
        "lock wait timeout exceeded on table products (holder: inventory-service migration)",
        "ALTER TABLE products ADD COLUMN warehouse_zone ... waiting for metadata lock"])
    w.burst(-6, 55, 2, "inventory-service", "ERROR", ["stock check failed: product-db query timeout"])
    w.burst(-6, 55, 2, "search-service", "WARN", ["product-db query slow, retrying (attempt 3)"])
    w.effect("search-service", "cpu_pct", -6, "set", 92)
    w.effect("search-service", "latency_p99_ms", -6, "step", 9)
    w.effect("product-db", "query_latency_ms", -7, "step", 40)
    w.effect("inventory-service", "error_rate_pct", -6, "set", 25)
    w.faults = {"get_deployments": {"mode": "error", "times": 1, "services": ["*"]}}
    w.dump({"root_cause_service": "inventory-service", "cause_type": "deployment_bug", "accepted_cause_types": ["deployment_bug"],
            "expected_outcome": "conclusive", "key_evidence": [d, lock[0], "M-product-db-query_latency_ms"],
            "traps": "search-service shows the loudest symptom (CPU) but is a victim; deployments tool fails on first call"})


def inc009():
    w = new("INC-009", 23, 15, "Intermittent slowness on profile page", "user-service",
            "A few customers report the profile page is sometimes slow. Not reproducible by support.", severity="SEV3")
    w.burst(-30, 55, 12, "user-service", "WARN", ["slow request detected (>1s) GET /profile"])
    w.effect("user-service", "latency_p99_ms", -30, "step", 1.4)
    w.faults = {"query_metrics": {"mode": "partial", "times": 99, "services": ["user-service", "orders-db"]}}
    w.dump({"root_cause_service": None, "cause_type": "unknown", "accepted_cause_types": ["unknown"],
            "expected_outcome": "inconclusive", "key_evidence": [],
            "traps": "no change events, weak signal, incomplete metrics: the honest answer is inconclusive"})


def inc010():
    w = new("INC-010", 25, 12, "user-service overloaded", "user-service",
            "user-service CPU saturated and latency high. user-service had a deploy this morning.")
    w.deploy(-190, "user-service", "v2.9.4", "Add avatar URL to profile response")
    c = w.config(-12, "api-gateway", "retry_policy.user-service", "{attempts: 1}", "{attempts: 5, backoff: none}", "platform-team", "PLAT-221")
    w.burst(-11, 55, 2, "api-gateway", "WARN", ["retrying request to user-service (attempt 4/5)", "retry budget exceeded for user-service"])
    w.burst(-10, 55, 3, "user-service", "ERROR", ["request queue full, rejecting request", "thread pool saturated (200/200)"])
    w.effect("user-service", "request_rate_rps", -12, "step", 4.8)
    w.effect("api-gateway", "request_rate_rps", -12, "step", 1.02)
    w.effect("user-service", "cpu_pct", -11, "set", 98)
    w.effect("user-service", "latency_p99_ms", -11, "step", 12)
    w.effect("user-service", "error_rate_pct", -10, "set", 14)
    w.dump({"root_cause_service": "api-gateway", "cause_type": "config_change", "accepted_cause_types": ["config_change"],
            "expected_outcome": "conclusive", "key_evidence": [c, "M-user-service-request_rate_rps"],
            "traps": "user-service is the victim; its own deploy is 3h old; gateway inbound traffic is flat (retry storm amplification)"})


def inc011():
    w = new("INC-011", 27, 20, "Order confirmation emails delayed", "notification-service",
            "Order confirmation emails arriving 40+ minutes late. orders-service logging publish timeouts.", severity="SEV3")
    c = w.config(-25, "notification-service", "feature_flags.batch_send_v2", False, True, "notif-team", "NOTIF-88 rollout 100%")
    q = w.burst(-22, 55, 3, "notification-service", "ERROR", [
        "batch_send_v2: batch flush stalled, queue depth 48211", "batch_send_v2 worker deadlock detected, restarting worker"])
    w.burst(-20, 55, 4, "orders-service", "WARN", ["notification publish timeout after 2000ms"])
    w.effect("notification-service", "latency_p99_ms", -22, "step", 30)
    w.effect("notification-service", "cpu_pct", -22, "step", 0.4)
    w.effect("redis-cache", "evictions_per_min", -60, "step", 2.2)
    trap = w.past(12, "Notification delays", ["notification-service", "redis-cache"],
                  "order emails delayed, publish timeouts", "redis-cache evictions dropped dedup keys causing retries", "tune redis maxmemory policy")
    w.dump({"root_cause_service": "notification-service", "cause_type": "config_change", "accepted_cause_types": ["config_change"],
            "expected_outcome": "conclusive", "key_evidence": [c, q[0]],
            "traps": f"historical incident {trap} blames redis; redis evictions really are elevated (but started 35m earlier and unrelated)"})


def inc012():
    w = new("INC-012", 29, 7, "Widespread errors across the storefront", "frontend",
            "Frontend error rate spiking; multiple services erroring at once. orders-service deployed earlier.", severity="SEV1")
    w.deploy(-125, "orders-service", "v12.4.0", "Refactor order summary DTO")
    w.effect("orders-db", "disk_used_pct", -300, "ramp", 1.64)
    w.effect("orders-db", "disk_used_pct", -2, "set", 100)
    disk = w.burst(-2, 55, 2, "orders-db", "ERROR", ["could not extend file: No space left on device", "PANIC: could not write to WAL: No space left on device"])
    w.burst(-1, 55, 2, "orders-service", "ERROR", ["insert into orders failed: orders-db unavailable"])
    w.burst(-1, 55, 3, "payment-service", "ERROR", ["could not persist transaction record: orders-db unavailable"])
    w.burst(0, 55, 1, "frontend", "ERROR", ["POST /api/orders failed: 500", "GET /api/account/orders failed: 500"])
    w.burst(0, 55, 3, "api-gateway", "ERROR", ["upstream orders-service returned 500 (route POST /api/orders)"])
    w.burst(0, 55, 3, "user-service", "ERROR", ["order history query failed: orders-db unavailable"])
    for s in ["orders-service", "payment-service", "user-service", "frontend"]:
        w.effect(s, "error_rate_pct", 0, "set", 20)
    w.faults = {"query_logs": {"mode": "partial", "times": 3, "services": ["frontend", "orders-service"]}}
    w.dump({"root_cause_service": "orders-db", "cause_type": "resource_exhaustion", "accepted_cause_types": ["resource_exhaustion"],
            "expected_outcome": "conclusive", "key_evidence": [disk[0], "M-orders-db-disk_used_pct"],
            "traps": "frontend is loudest; orders-service deploy 2h earlier is a red herring; log results truncated"})


def main():
    OUT_INC.mkdir(parents=True, exist_ok=True)
    OUT_GT.mkdir(parents=True, exist_ok=True)
    for fn in [inc001, inc002, inc003, inc004, inc005, inc006, inc007, inc008, inc009, inc010, inc011, inc012]:
        fn()
    print(f"wrote {len(list(OUT_INC.glob('*.json')))} incidents to {OUT_INC}")


if __name__ == "__main__":
    main()
