# Incident investigation report - INC-010 (single-agent)

**Outcome:** CONCLUSIVE - config_change in `api-gateway` (confidence 61%)

Most likely root cause: config change in api-gateway (confidence 61%). config_change in api-gateway: config_change C-001 at 2026-03-25T11:48:00Z precedes related anomaly by 2 min; change explicitly targets an affected service

## Ranked hypotheses
### 1. config_change in `api-gateway` - confidence 61%
config_change in api-gateway: config_change C-001 at 2026-03-25T11:48:00Z precedes related anomaly by 2 min; change explicitly targets an affected service
- **Supporting:**
  - [fact] config change C-001: api-gateway retry_policy.user-service {attempts: 1} -> {attempts: 5, backoff: none} at 2026-03-25T11:48:00Z by platform-team (refs: C-001)

### 2. traffic_spike in `user-service` - confidence 20%
traffic_spike in user-service: own metrics anomalous: latency_p99_ms x11.84, error_rate_pct x35.1, cpu_pct x2.79, request_rate_rps x4.85; 22 own error logs; deepest implicated node in the dependency chain
- **Supporting:**
  - [fact] user-service latency_p99_ms moved from baseline 180.45 to 2136.71 (x11.84), first anomalous at 2026-03-25T11:50:00Z (refs: M-user-service-latency_p99_ms)
  - [fact] user-service error_rate_pct moved from baseline 0.4 to 13.98 (x35.1), first anomalous at 2026-03-25T11:50:00Z (refs: M-user-service-error_rate_pct)
  - [fact] user-service cpu_pct moved from baseline 35.1 to 98.09 (x2.79), first anomalous at 2026-03-25T11:50:00Z (refs: M-user-service-cpu_pct)
  - [fact] user-service request_rate_rps moved from baseline 218.71 to 1059.87 (x4.85), first anomalous at 2026-03-25T11:50:00Z (refs: M-user-service-request_rate_rps)
  - [fact] user-service logged 15x ERROR 'thread pool saturated (200/200)' between 2026-03-25T11:54:52Z and 2026-03-25T12:53:04Z (refs: L-0252)
  - [fact] user-service logged 7x ERROR 'request queue full, rejecting request' between 2026-03-25T11:52:08Z and 2026-03-25T12:50:12Z (refs: L-0251)
- **Contradicting:**
  - [fact] deployment D-001: user-service v2.9.4 at 2026-03-25T08:50:00Z (Add avatar URL to profile response) (refs: D-001)

## Facts (directly observed)
- user-service logged 15x ERROR 'thread pool saturated (200/200)' between 2026-03-25T11:54:52Z and 2026-03-25T12:53:04Z
- user-service logged 7x ERROR 'request queue full, rejecting request' between 2026-03-25T11:52:08Z and 2026-03-25T12:50:12Z
- user-service latency_p99_ms moved from baseline 180.45 to 2136.71 (x11.84), first anomalous at 2026-03-25T11:50:00Z
- user-service error_rate_pct moved from baseline 0.4 to 13.98 (x35.1), first anomalous at 2026-03-25T11:50:00Z
- user-service cpu_pct moved from baseline 35.1 to 98.09 (x2.79), first anomalous at 2026-03-25T11:50:00Z
- user-service request_rate_rps moved from baseline 218.71 to 1059.87 (x4.85), first anomalous at 2026-03-25T11:50:00Z
- deployment D-001: user-service v2.9.4 at 2026-03-25T08:50:00Z (Add avatar URL to profile response)
- config change C-001: api-gateway retry_policy.user-service {attempts: 1} -> {attempts: 5, backoff: none} at 2026-03-25T11:48:00Z by platform-team

## Inferences and assumptions (not directly observed)
- none

## Recommended actions
- **P0** Revert the configuration change on api-gateway - the change immediately preceded the first anomaly
- **P1** Route config/flag changes for api-gateway through staged rollout with automatic rollback - config changes need the same safety as code

## Investigation trace
- rounds: 1, termination: LLM path failed (LLMUnavailable); heuristic single pass
- tool calls: 7 (0 failed, 1 retried), LLM calls: 0, tokens: 0, latency: 0.03s
- tasks: SINGLE-1(recovered)
