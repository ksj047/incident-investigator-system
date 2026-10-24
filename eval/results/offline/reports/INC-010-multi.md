# Incident investigation report - INC-010 (multi-agent)

**Outcome:** CONCLUSIVE - config_change in `api-gateway` (confidence 56%)

Most likely root cause: config change in api-gateway (confidence 56%). config change in api-gateway: config_change C-001 at 2026-03-25T11:48:00Z precedes related anomaly by 2 min; change explicitly targets an affected service

## Ranked hypotheses
### 1. config_change in `api-gateway` - confidence 56%
config change in api-gateway: config_change C-001 at 2026-03-25T11:48:00Z precedes related anomaly by 2 min; change explicitly targets an affected service
- **Supporting:**
  - [fact] config change C-001: api-gateway retry_policy.user-service {attempts: 1} -> {attempts: 5, backoff: none} at 2026-03-25T11:48:00Z by platform-team (refs: C-001)

### 2. traffic_spike in `user-service` - confidence 36%
traffic spike in user-service: own metrics anomalous: latency_p99_ms x11.84, error_rate_pct x35.1, cpu_pct x2.79, request_rate_rps x4.85; 22 own error logs; named in 34 error/warn logs of ['api-gateway']; deepest implicated node in the dependency chain
- **Supporting:**
  - [fact] user-service latency_p99_ms moved from baseline 180.45 to 2136.71 (x11.84), first anomalous at 2026-03-25T11:50:00Z (refs: M-user-service-latency_p99_ms)
  - [fact] user-service error_rate_pct moved from baseline 0.4 to 13.98 (x35.1), first anomalous at 2026-03-25T11:50:00Z (refs: M-user-service-error_rate_pct)
  - [fact] user-service cpu_pct moved from baseline 35.1 to 98.09 (x2.79), first anomalous at 2026-03-25T11:50:00Z (refs: M-user-service-cpu_pct)
  - [fact] user-service request_rate_rps moved from baseline 218.71 to 1059.87 (x4.85), first anomalous at 2026-03-25T11:50:00Z (refs: M-user-service-request_rate_rps)
  - [fact] user-service logged 15x ERROR 'thread pool saturated (200/200)' between 2026-03-25T11:54:52Z and 2026-03-25T12:53:04Z (refs: L-0252)
  - [fact] user-service logged 7x ERROR 'request queue full, rejecting request' between 2026-03-25T11:52:08Z and 2026-03-25T12:50:12Z (refs: L-0251)
  - [fact] api-gateway logged 19x WARN 'retry budget exceeded for user-service' between 2026-03-25T11:49:28Z and 2026-03-25T12:55:45Z (refs: L-0217)
  - [fact] api-gateway logged 15x WARN 'retrying request to user-service (attempt 4/5)' between 2026-03-25T11:51:22Z and 2026-03-25T12:51:58Z (refs: L-0218)
- **Contradicting:**
  - [fact] deployment D-001: user-service v2.9.4 at 2026-03-25T08:50:00Z (Add avatar URL to profile response) (refs: D-001)

## Facts (directly observed)
- deployment D-001: user-service v2.9.4 at 2026-03-25T08:50:00Z (Add avatar URL to profile response)
- config change C-001: api-gateway retry_policy.user-service {attempts: 1} -> {attempts: 5, backoff: none} at 2026-03-25T11:48:00Z by platform-team
- user-service logged 15x ERROR 'thread pool saturated (200/200)' between 2026-03-25T11:54:52Z and 2026-03-25T12:53:04Z
- user-service logged 7x ERROR 'request queue full, rejecting request' between 2026-03-25T11:52:08Z and 2026-03-25T12:50:12Z
- user-service latency_p99_ms moved from baseline 180.45 to 2136.71 (x11.84), first anomalous at 2026-03-25T11:50:00Z
- user-service error_rate_pct moved from baseline 0.4 to 13.98 (x35.1), first anomalous at 2026-03-25T11:50:00Z
- user-service cpu_pct moved from baseline 35.1 to 98.09 (x2.79), first anomalous at 2026-03-25T11:50:00Z
- user-service request_rate_rps moved from baseline 218.71 to 1059.87 (x4.85), first anomalous at 2026-03-25T11:50:00Z
- api-gateway logged 19x WARN 'retry budget exceeded for user-service' between 2026-03-25T11:49:28Z and 2026-03-25T12:55:45Z
- api-gateway logged 15x WARN 'retrying request to user-service (attempt 4/5)' between 2026-03-25T11:51:22Z and 2026-03-25T12:51:58Z

## Inferences and assumptions (not directly observed)
- none

## Recommended actions
- **P0** Revert the configuration change on api-gateway - the change immediately preceded the first anomaly
- **P1** Route config/flag changes for api-gateway through staged rollout with automatic rollback - config changes need the same safety as code

## Investigation trace
- rounds: 2, termination: critic accepted in round 1
- tool calls: 43 (0 failed, 3 retried), LLM calls: 0, tokens: 0, latency: 0.43s
- critic round 0: **investigate** - H1 rests on 1 directly observed fact(s); needs corroboration; downstream dependencies of api-gateway not yet examined: ['auth-service', 'orders-service', 'search-service', 'recommendation-service'] (is the suspect a victim?)
- critic round 1: **accept** - H1 rests on 1 directly observed fact(s); needs corroboration
- tasks: OBS-1(recovered), DEP-2(recovered), REA-3(recovered), CRI-4(recovered), OBS-5(recovered), OBS-6(recovered), REA-7(recovered), CRI-8(recovered), REP-9(recovered)
