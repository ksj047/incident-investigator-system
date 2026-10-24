# Incident investigation report - INC-005 (multi-agent)

**Outcome:** CONCLUSIVE - traffic_spike in `api-gateway` (confidence 66%)

Most likely root cause: traffic spike in api-gateway (confidence 66%). traffic spike in api-gateway: own metrics anomalous: latency_p99_ms x7.97, error_rate_pct x52.92, cpu_pct x2.81, request_rate_rps x4.46; 28 own error logs; deepest implicated node in the dependency chain; log keywords indicate traffic_spike

## Ranked hypotheses
### 1. traffic_spike in `api-gateway` - confidence 66%
traffic spike in api-gateway: own metrics anomalous: latency_p99_ms x7.97, error_rate_pct x52.92, cpu_pct x2.81, request_rate_rps x4.46; 28 own error logs; deepest implicated node in the dependency chain; log keywords indicate traffic_spike
- **Supporting:**
  - [fact] api-gateway latency_p99_ms moved from baseline 181.31 to 1444.78 (x7.97), first anomalous at 2026-03-11T18:00:00Z (refs: M-api-gateway-latency_p99_ms)
  - [fact] api-gateway error_rate_pct moved from baseline 0.4 to 20.95 (x52.92), first anomalous at 2026-03-11T18:00:00Z (refs: M-api-gateway-error_rate_pct)
  - [fact] api-gateway cpu_pct moved from baseline 34.44 to 96.85 (x2.81), first anomalous at 2026-03-11T18:00:00Z (refs: M-api-gateway-cpu_pct)
  - [fact] api-gateway request_rate_rps moved from baseline 221.78 to 989.35 (x4.46), first anomalous at 2026-03-11T18:00:00Z (refs: M-api-gateway-request_rate_rps)
  - [fact] api-gateway logged 15x ERROR 'rate limiter rejected request: 429 too many requests' between 2026-03-11T18:00:34Z and 2026-03-11T18:54:19Z (refs: L-0230)
  - [fact] api-gateway logged 13x ERROR 'upstream overloaded: returning 503 (queue depth 4096)' between 2026-03-11T18:07:02Z and 2026-03-11T18:52:59Z (refs: L-0233)

### 2. deployment_bug in `auth-service` - confidence 13%
deployment bug in auth-service: deployment D-001 at 2026-03-11T17:20:00Z precedes related anomaly by 40 min
- **Supporting:**
  - [fact] deployment D-001: auth-service v4.0.3 at 2026-03-11T17:20:00Z (Log format tweak) (refs: D-001)

## Facts (directly observed)
- deployment D-001: auth-service v4.0.3 at 2026-03-11T17:20:00Z (Log format tweak)
- api-gateway logged 15x ERROR 'rate limiter rejected request: 429 too many requests' between 2026-03-11T18:00:34Z and 2026-03-11T18:54:19Z
- api-gateway logged 13x ERROR 'upstream overloaded: returning 503 (queue depth 4096)' between 2026-03-11T18:07:02Z and 2026-03-11T18:52:59Z
- api-gateway latency_p99_ms moved from baseline 181.31 to 1444.78 (x7.97), first anomalous at 2026-03-11T18:00:00Z
- api-gateway error_rate_pct moved from baseline 0.4 to 20.95 (x52.92), first anomalous at 2026-03-11T18:00:00Z
- api-gateway cpu_pct moved from baseline 34.44 to 96.85 (x2.81), first anomalous at 2026-03-11T18:00:00Z
- api-gateway request_rate_rps moved from baseline 221.78 to 989.35 (x4.46), first anomalous at 2026-03-11T18:00:00Z

## Inferences and assumptions (not directly observed)
- none

## Recommended actions
- **P0** Raise api-gateway max replicas / shed non-critical load - demand exceeds provisioned capacity
- **P1** Pre-scale for campaigns; coordinate marketing pushes with capacity planning - spike was predictable

## Investigation trace
- rounds: 2, termination: critic accepted in round 1
- tool calls: 27 (0 failed, 3 retried), LLM calls: 0, tokens: 0, latency: 0.4s
- critic round 0: **investigate** - downstream dependencies of api-gateway not yet examined: ['recommendation-service'] (is the suspect a victim?)
- critic round 1: **accept** - 
- tasks: OBS-1(recovered), DEP-2(recovered), REA-3(recovered), CRI-4(recovered), OBS-5(recovered), REA-6(recovered), CRI-7(recovered), REP-8(recovered)
