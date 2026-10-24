# Incident investigation report - INC-004 (single-agent)

**Outcome:** CONCLUSIVE - resource_exhaustion in `recommendation-service` (confidence 75%)

Most likely root cause: resource exhaustion in recommendation-service (confidence 75%). resource_exhaustion in recommendation-service: own metrics anomalous: latency_p99_ms x3.01, error_rate_pct x23.03, memory_pct x1.83; 16 own error logs; deepest implicated node in the dependency chain

## Ranked hypotheses
### 1. resource_exhaustion in `recommendation-service` - confidence 75%
resource_exhaustion in recommendation-service: own metrics anomalous: latency_p99_ms x3.01, error_rate_pct x23.03, memory_pct x1.83; 16 own error logs; deepest implicated node in the dependency chain
- **Supporting:**
  - [fact] recommendation-service latency_p99_ms moved from baseline 180.94 to 545.16 (x3.01), first anomalous at 2026-03-08T15:20:00Z (refs: M-recommendation-service-latency_p99_ms)
  - [fact] recommendation-service error_rate_pct moved from baseline 0.39 to 8.98 (x23.03), first anomalous at 2026-03-08T15:20:00Z (refs: M-recommendation-service-error_rate_pct)
  - [fact] recommendation-service memory_pct moved from baseline 51.69 to 94.45 (x1.83), first anomalous at 2026-03-08T11:55:00Z (refs: M-recommendation-service-memory_pct)
  - [fact] recommendation-service logged 12x ERROR 'container killed: OOMKilled (memory limit 2Gi)' between 2026-03-08T15:20:55Z and 2026-03-08T16:50:51Z (refs: L-0214)
  - [fact] recommendation-service logged 4x ERROR 'java.lang.OutOfMemoryError: Java heap space' between 2026-03-08T15:32:07Z and 2026-03-08T16:47:24Z (refs: L-0216)
  - [fact] deployment D-001: recommendation-service v3.2.0 at 2026-03-08T10:50:00Z (Add in-process embedding cache) (refs: D-001)
- **Assumptions:** resource growth may have been introduced by D-001

## Facts (directly observed)
- recommendation-service logged 12x ERROR 'container killed: OOMKilled (memory limit 2Gi)' between 2026-03-08T15:20:55Z and 2026-03-08T16:50:51Z
- recommendation-service logged 4x ERROR 'java.lang.OutOfMemoryError: Java heap space' between 2026-03-08T15:32:07Z and 2026-03-08T16:47:24Z
- recommendation-service latency_p99_ms moved from baseline 180.94 to 545.16 (x3.01), first anomalous at 2026-03-08T15:20:00Z
- recommendation-service error_rate_pct moved from baseline 0.39 to 8.98 (x23.03), first anomalous at 2026-03-08T15:20:00Z
- recommendation-service memory_pct moved from baseline 51.69 to 94.45 (x1.83), first anomalous at 2026-03-08T11:55:00Z
- deployment D-001: recommendation-service v3.2.0 at 2026-03-08T10:50:00Z (Add in-process embedding cache)

## Inferences and assumptions (not directly observed)
- resource growth may have been introduced by D-001

## Recommended actions
- **P0** Free / add capacity on recommendation-service (restart, scale, expand storage) - resource is exhausted
- **P1** Alert on resource trend for recommendation-service well before saturation; fix the leak/growth source - this failed slowly and was visible hours ahead

## Open questions
- resource growth may have been introduced by D-001

## Investigation trace
- rounds: 1, termination: LLM path failed (LLMUnavailable); heuristic single pass
- tool calls: 7 (0 failed, 1 retried), LLM calls: 0, tokens: 0, latency: 0.03s
- tasks: SINGLE-1(recovered)
