# Incident investigation report - INC-012 (single-agent)

**Outcome:** CONCLUSIVE - unknown in `frontend` (confidence 58%)

Most likely root cause: unknown in frontend (confidence 58%). unknown in frontend: own metrics anomalous: error_rate_pct x49.9; 56 own error logs; deepest implicated node in the dependency chain

## Ranked hypotheses
### 1. unknown in `frontend` - confidence 58%
unknown in frontend: own metrics anomalous: error_rate_pct x49.9; 56 own error logs; deepest implicated node in the dependency chain
- **Supporting:**
  - [fact] frontend error_rate_pct moved from baseline 0.4 to 20.13 (x49.9), first anomalous at 2026-03-29T07:00:00Z (refs: M-frontend-error_rate_pct)
  - [fact] frontend logged 30x ERROR 'GET /api/account/orders failed: 500' between 2026-03-29T07:00:24Z and 2026-03-29T07:54:21Z (INCOMPLETE data) (refs: L-0298)
  - [fact] frontend logged 26x ERROR 'POST /api/orders failed: 500' between 2026-03-29T07:02:05Z and 2026-03-29T07:55:18Z (INCOMPLETE data) (refs: L-0300)
- **Assumptions:** no signal pins down the failure mechanism

## Facts (directly observed)
- frontend logged 30x ERROR 'GET /api/account/orders failed: 500' between 2026-03-29T07:00:24Z and 2026-03-29T07:54:21Z (INCOMPLETE data)
- frontend logged 26x ERROR 'POST /api/orders failed: 500' between 2026-03-29T07:02:05Z and 2026-03-29T07:55:18Z (INCOMPLETE data)
- frontend error_rate_pct moved from baseline 0.4 to 20.13 (x49.9), first anomalous at 2026-03-29T07:00:00Z

## Inferences and assumptions (not directly observed)
- no signal pins down the failure mechanism

## Recommended actions
- **P1** Keep incident open; add tracing/profiling around frontend and collect complete metrics - evidence is insufficient for a root cause

## Open questions
- no signal pins down the failure mechanism

## Investigation trace
- rounds: 1, termination: LLM path failed (LLMUnavailable); heuristic single pass
- tool calls: 7 (0 failed, 1 retried), LLM calls: 0, tokens: 0, latency: 0.03s
- tasks: SINGLE-1(recovered)
