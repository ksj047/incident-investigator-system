# Incident investigation report - INC-005 (single-agent)

**Outcome:** CONCLUSIVE - traffic_spike in `api-gateway` (confidence 66%)

Most likely root cause: traffic spike in api-gateway (confidence 66%). traffic_spike in api-gateway: own metrics anomalous: latency_p99_ms x7.97, error_rate_pct x52.92, cpu_pct x2.81, request_rate_rps x4.46; 28 own error logs; deepest implicated node in the dependency chain

## Ranked hypotheses
### 1. traffic_spike in `api-gateway` - confidence 66%
traffic_spike in api-gateway: own metrics anomalous: latency_p99_ms x7.97, error_rate_pct x52.92, cpu_pct x2.81, request_rate_rps x4.46; 28 own error logs; deepest implicated node in the dependency chain
- **Supporting:**
  - [fact] api-gateway latency_p99_ms moved from baseline 181.31 to 1444.78 (x7.97), first anomalous at 2026-03-11T18:00:00Z (refs: M-api-gateway-latency_p99_ms)
  - [fact] api-gateway error_rate_pct moved from baseline 0.4 to 20.95 (x52.92), first anomalous at 2026-03-11T18:00:00Z (refs: M-api-gateway-error_rate_pct)
  - [fact] api-gateway cpu_pct moved from baseline 34.44 to 96.85 (x2.81), first anomalous at 2026-03-11T18:00:00Z (refs: M-api-gateway-cpu_pct)
  - [fact] api-gateway request_rate_rps moved from baseline 221.78 to 989.35 (x4.46), first anomalous at 2026-03-11T18:00:00Z (refs: M-api-gateway-request_rate_rps)
  - [fact] api-gateway logged 15x ERROR 'rate limiter rejected request: 429 too many requests' between 2026-03-11T18:00:34Z and 2026-03-11T18:54:19Z (refs: L-0230)
  - [fact] api-gateway logged 13x ERROR 'upstream overloaded: returning 503 (queue depth 4096)' between 2026-03-11T18:07:02Z and 2026-03-11T18:52:59Z (refs: L-0233)

### 2. deployment_bug in `auth-service` - confidence 13%
deployment_bug in auth-service: deployment D-001 at 2026-03-11T17:20:00Z precedes related anomaly by 40 min
- **Supporting:**
  - [fact] deployment D-001: auth-service v4.0.3 at 2026-03-11T17:20:00Z (Log format tweak) (refs: D-001)

## Facts (directly observed)
- api-gateway logged 15x ERROR 'rate limiter rejected request: 429 too many requests' between 2026-03-11T18:00:34Z and 2026-03-11T18:54:19Z
- api-gateway logged 13x ERROR 'upstream overloaded: returning 503 (queue depth 4096)' between 2026-03-11T18:07:02Z and 2026-03-11T18:52:59Z
- api-gateway latency_p99_ms moved from baseline 181.31 to 1444.78 (x7.97), first anomalous at 2026-03-11T18:00:00Z
- api-gateway error_rate_pct moved from baseline 0.4 to 20.95 (x52.92), first anomalous at 2026-03-11T18:00:00Z
- api-gateway cpu_pct moved from baseline 34.44 to 96.85 (x2.81), first anomalous at 2026-03-11T18:00:00Z
- api-gateway request_rate_rps moved from baseline 221.78 to 989.35 (x4.46), first anomalous at 2026-03-11T18:00:00Z
- deployment D-001: auth-service v4.0.3 at 2026-03-11T17:20:00Z (Log format tweak)

## Inferences and assumptions (not directly observed)
- none

## Recommended actions
- **P0** Raise api-gateway max replicas / shed non-critical load - demand exceeds provisioned capacity
- **P1** Pre-scale for campaigns; coordinate marketing pushes with capacity planning - spike was predictable

## Investigation trace
- rounds: 1, termination: LLM path failed (LLMUnavailable); heuristic single pass
- tool calls: 7 (0 failed, 1 retried), LLM calls: 0, tokens: 0, latency: 0.03s
- tasks: SINGLE-1(recovered)
