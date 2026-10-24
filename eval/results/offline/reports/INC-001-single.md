# Incident investigation report - INC-001 (single-agent)

**Outcome:** CONCLUSIVE - deployment_bug in `payment-service` (confidence 72%)

Most likely root cause: deployment bug in payment-service (confidence 72%). deployment_bug in payment-service: named in 21 error/warn logs of ['orders-service']; deepest implicated node in the dependency chain; deployment D-001 at 2026-03-02T13:51:00Z precedes related anomaly by 4 min

## Ranked hypotheses
### 1. deployment_bug in `payment-service` - confidence 72%
deployment_bug in payment-service: named in 21 error/warn logs of ['orders-service']; deepest implicated node in the dependency chain; deployment D-001 at 2026-03-02T13:51:00Z precedes related anomaly by 4 min
- **Supporting:**
  - [fact] orders-service logged 21x ERROR 'call to payment-service failed: HTTP 500 Internal Server Error' between 2026-03-02T13:54:35Z and 2026-03-02T14:54:22Z (refs: L-0233)
  - [fact] deployment D-001: payment-service v2.14.0 at 2026-03-02T13:51:00Z (Refactor PaymentMethodResolver; add wallet support) (refs: D-001)

### 2. unknown in `orders-service` - confidence 18%
unknown in orders-service: own metrics anomalous: error_rate_pct x45.63; 21 own error logs; deepest implicated node in the dependency chain
- **Supporting:**
  - [fact] orders-service error_rate_pct moved from baseline 0.39 to 17.95 (x45.63), first anomalous at 2026-03-02T13:55:00Z (refs: M-orders-service-error_rate_pct)
  - [fact] orders-service logged 21x ERROR 'call to payment-service failed: HTTP 500 Internal Server Error' between 2026-03-02T13:54:35Z and 2026-03-02T14:54:22Z (refs: L-0233)
- **Assumptions:** no signal pins down the failure mechanism

## Facts (directly observed)
- orders-service logged 21x ERROR 'call to payment-service failed: HTTP 500 Internal Server Error' between 2026-03-02T13:54:35Z and 2026-03-02T14:54:22Z
- orders-service error_rate_pct moved from baseline 0.39 to 17.95 (x45.63), first anomalous at 2026-03-02T13:55:00Z
- deployment D-001: payment-service v2.14.0 at 2026-03-02T13:51:00Z (Refactor PaymentMethodResolver; add wallet support)

## Inferences and assumptions (not directly observed)
- no signal pins down the failure mechanism

## Recommended actions
- **P0** Roll back payment-service to the previous version - restores service fastest; deploy is the prime suspect
- **P1** Add a regression test and canary analysis gate for payment-service - catch this class of defect before full rollout

## Open questions
- no signal pins down the failure mechanism

## Investigation trace
- rounds: 1, termination: LLM path failed (LLMUnavailable); heuristic single pass
- tool calls: 7 (0 failed, 1 retried), LLM calls: 0, tokens: 0, latency: 0.03s
- tasks: SINGLE-1(recovered)
