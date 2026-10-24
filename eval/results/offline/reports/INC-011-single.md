# Incident investigation report - INC-011 (single-agent)

**Outcome:** CONCLUSIVE - config_change in `notification-service` (confidence 84%)

Most likely root cause: config change in notification-service (confidence 84%). config_change in notification-service: own metrics anomalous: latency_p99_ms x29.71, cpu_pct x0.4; 26 own error logs; deepest implicated node in the dependency chain

## Ranked hypotheses
### 1. config_change in `notification-service` - confidence 84%
config_change in notification-service: own metrics anomalous: latency_p99_ms x29.71, cpu_pct x0.4; 26 own error logs; deepest implicated node in the dependency chain
- **Supporting:**
  - [fact] notification-service latency_p99_ms moved from baseline 180.2 to 5353.26 (x29.71), first anomalous at 2026-03-27T19:40:00Z (refs: M-notification-service-latency_p99_ms)
  - [fact] notification-service cpu_pct moved from baseline 34.61 to 13.77 (x0.4), first anomalous at 2026-03-27T19:40:00Z (refs: M-notification-service-cpu_pct)
  - [fact] notification-service logged 14x ERROR 'batch_send_v2: batch flush stalled, queue depth 48211' between 2026-03-27T19:44:37Z and 2026-03-27T20:50:23Z (refs: L-0235)
  - [fact] notification-service logged 12x ERROR 'batch_send_v2 worker deadlock detected, restarting worker' between 2026-03-27T19:38:22Z and 2026-03-27T20:55:04Z (refs: L-0233)
  - [fact] config change C-001: notification-service feature_flags.batch_send_v2 False -> True at 2026-03-27T19:35:00Z by notif-team (refs: C-001)

## Facts (directly observed)
- notification-service logged 14x ERROR 'batch_send_v2: batch flush stalled, queue depth 48211' between 2026-03-27T19:44:37Z and 2026-03-27T20:50:23Z
- notification-service logged 12x ERROR 'batch_send_v2 worker deadlock detected, restarting worker' between 2026-03-27T19:38:22Z and 2026-03-27T20:55:04Z
- notification-service latency_p99_ms moved from baseline 180.2 to 5353.26 (x29.71), first anomalous at 2026-03-27T19:40:00Z
- notification-service cpu_pct moved from baseline 34.61 to 13.77 (x0.4), first anomalous at 2026-03-27T19:40:00Z
- config change C-001: notification-service feature_flags.batch_send_v2 False -> True at 2026-03-27T19:35:00Z by notif-team

## Inferences and assumptions (not directly observed)
- none

## Recommended actions
- **P0** Revert the configuration change on notification-service - the change immediately preceded the first anomaly
- **P1** Route config/flag changes for notification-service through staged rollout with automatic rollback - config changes need the same safety as code

## Investigation trace
- rounds: 1, termination: LLM path failed (LLMUnavailable); heuristic single pass
- tool calls: 7 (0 failed, 1 retried), LLM calls: 0, tokens: 0, latency: 0.03s
- tasks: SINGLE-1(recovered)
