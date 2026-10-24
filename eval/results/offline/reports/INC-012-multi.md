# Incident investigation report - INC-012 (multi-agent)

**Outcome:** CONCLUSIVE - resource_exhaustion in `orders-db` (confidence 64%)

Most likely root cause: resource exhaustion in orders-db (confidence 64%). resource exhaustion in orders-db: own metrics anomalous: disk_used_pct x1.62; 29 own error logs; named in 48 error/warn logs of ['orders-service', 'payment-service']; deepest implicated node in the dependency chain

## Ranked hypotheses
### 1. resource_exhaustion in `orders-db` - confidence 64%
resource exhaustion in orders-db: own metrics anomalous: disk_used_pct x1.62; 29 own error logs; named in 48 error/warn logs of ['orders-service', 'payment-service']; deepest implicated node in the dependency chain
- **Supporting:**
  - [fact] orders-db disk_used_pct moved from baseline 61.34 to 99.65 (x1.62), first anomalous at 2026-03-29T03:30:00Z (refs: M-orders-db-disk_used_pct)
  - [fact] orders-db logged 15x ERROR 'could not extend file: No space left on device' between 2026-03-29T07:01:29Z and 2026-03-29T07:52:14Z (refs: L-0222)
  - [fact] orders-db logged 14x ERROR 'PANIC: could not write to WAL: No space left on device' between 2026-03-29T06:59:20Z and 2026-03-29T07:54:29Z (refs: L-0221)
  - [fact] orders-service logged 29x ERROR 'insert into orders failed: orders-db unavailable' between 2026-03-29T06:59:22Z and 2026-03-29T07:55:50Z (INCOMPLETE data) (refs: L-0250)
  - [fact] payment-service logged 19x ERROR 'could not persist transaction record: orders-db unavailable' between 2026-03-29T07:01:12Z and 2026-03-29T07:54:19Z (refs: L-0279)

### 2. unknown in `orders-service` - confidence 30%
unknown in orders-service: own metrics anomalous: error_rate_pct x49.22; 29 own error logs; named in 19 error/warn logs of ['api-gateway']; downstream services also implicated: ['orders-db', 'payment-service'] (may be a victim)
- **Supporting:**
  - [fact] orders-service error_rate_pct moved from baseline 0.41 to 20.02 (x49.22), first anomalous at 2026-03-29T07:00:00Z (refs: M-orders-service-error_rate_pct)
  - [fact] orders-service logged 29x ERROR 'insert into orders failed: orders-db unavailable' between 2026-03-29T06:59:22Z and 2026-03-29T07:55:50Z (INCOMPLETE data) (refs: L-0250)
  - [fact] api-gateway logged 19x ERROR 'upstream orders-service returned 500 (route POST /api/orders)' between 2026-03-29T07:00:54Z and 2026-03-29T07:54:53Z (refs: L-0354)
- **Contradicting:**
  - [fact] deployment D-001: orders-service v12.4.0 at 2026-03-29T04:55:00Z (Refactor order summary DTO) (refs: D-001)
- **Assumptions:** no signal pins down the failure mechanism

### 3. unknown in `frontend` - confidence 15%
unknown in frontend: own metrics anomalous: error_rate_pct x49.9; 56 own error logs; downstream services also implicated: ['orders-db', 'orders-service', 'payment-service'] (may be a victim)
- **Supporting:**
  - [fact] frontend error_rate_pct moved from baseline 0.4 to 20.13 (x49.9), first anomalous at 2026-03-29T07:00:00Z (refs: M-frontend-error_rate_pct)
  - [fact] frontend logged 30x ERROR 'GET /api/account/orders failed: 500' between 2026-03-29T07:00:24Z and 2026-03-29T07:54:21Z (INCOMPLETE data) (refs: L-0298)
  - [fact] frontend logged 26x ERROR 'POST /api/orders failed: 500' between 2026-03-29T07:02:05Z and 2026-03-29T07:55:18Z (INCOMPLETE data) (refs: L-0300)
- **Assumptions:** no signal pins down the failure mechanism

### 4. unknown in `payment-service` - confidence 15%
unknown in payment-service: own metrics anomalous: error_rate_pct x49.76; 19 own error logs; downstream services also implicated: ['orders-db'] (may be a victim)
- **Supporting:**
  - [fact] payment-service error_rate_pct moved from baseline 0.4 to 20.03 (x49.76), first anomalous at 2026-03-29T07:00:00Z (refs: M-payment-service-error_rate_pct)
  - [fact] payment-service logged 19x ERROR 'could not persist transaction record: orders-db unavailable' between 2026-03-29T07:01:12Z and 2026-03-29T07:54:19Z (refs: L-0279)
- **Assumptions:** no signal pins down the failure mechanism

## Facts (directly observed)
- deployment D-001: orders-service v12.4.0 at 2026-03-29T04:55:00Z (Refactor order summary DTO)
- frontend logged 30x ERROR 'GET /api/account/orders failed: 500' between 2026-03-29T07:00:24Z and 2026-03-29T07:54:21Z (INCOMPLETE data)
- frontend logged 26x ERROR 'POST /api/orders failed: 500' between 2026-03-29T07:02:05Z and 2026-03-29T07:55:18Z (INCOMPLETE data)
- frontend error_rate_pct moved from baseline 0.4 to 20.13 (x49.9), first anomalous at 2026-03-29T07:00:00Z
- orders-service logged 29x ERROR 'insert into orders failed: orders-db unavailable' between 2026-03-29T06:59:22Z and 2026-03-29T07:55:50Z (INCOMPLETE data)
- orders-service error_rate_pct moved from baseline 0.41 to 20.02 (x49.22), first anomalous at 2026-03-29T07:00:00Z
- orders-db logged 15x ERROR 'could not extend file: No space left on device' between 2026-03-29T07:01:29Z and 2026-03-29T07:52:14Z
- orders-db logged 14x ERROR 'PANIC: could not write to WAL: No space left on device' between 2026-03-29T06:59:20Z and 2026-03-29T07:54:29Z
- orders-db disk_used_pct moved from baseline 61.34 to 99.65 (x1.62), first anomalous at 2026-03-29T03:30:00Z
- api-gateway logged 19x ERROR 'upstream orders-service returned 500 (route POST /api/orders)' between 2026-03-29T07:00:54Z and 2026-03-29T07:54:53Z
- payment-service logged 19x ERROR 'could not persist transaction record: orders-db unavailable' between 2026-03-29T07:01:12Z and 2026-03-29T07:54:19Z
- payment-service error_rate_pct moved from baseline 0.4 to 20.03 (x49.76), first anomalous at 2026-03-29T07:00:00Z

## Inferences and assumptions (not directly observed)
- no signal pins down the failure mechanism

## Recommended actions
- **P0** Free / add capacity on orders-db (restart, scale, expand storage) - resource is exhausted
- **P1** Alert on resource trend for orders-db well before saturation; fix the leak/growth source - this failed slowly and was visible hours ahead

## Open questions
- no signal pins down the failure mechanism

## Investigation trace
- rounds: 1, termination: critic accepted in round 0
- tool calls: 29 (0 failed, 3 retried), LLM calls: 0, tokens: 0, latency: 0.37s
- critic round 0: **accept** - 
- tasks: OBS-1(recovered), DEP-2(recovered), REA-3(recovered), CRI-4(recovered), REP-5(recovered)
