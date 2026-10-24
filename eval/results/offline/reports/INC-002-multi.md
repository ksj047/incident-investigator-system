# Incident investigation report - INC-002 (multi-agent)

**Outcome:** CONCLUSIVE - config_change in `orders-db` (confidence 82%)

Most likely root cause: config change in orders-db (confidence 82%). config change in orders-db: own metrics anomalous: connections_active x0.36; 35 own error logs; named in 35 error/warn logs of ['orders-service']; deepest implicated node in the dependency chain

## Ranked hypotheses
### 1. config_change in `orders-db` - confidence 82%
config change in orders-db: own metrics anomalous: connections_active x0.36; 35 own error logs; named in 35 error/warn logs of ['orders-service']; deepest implicated node in the dependency chain
- **Supporting:**
  - [fact] orders-db connections_active moved from baseline 140.6 to 50 (x0.36), first anomalous at 2026-03-03T09:45:00Z (refs: M-orders-db-connections_active)
  - [fact] orders-db logged 35x ERROR 'FATAL: sorry, too many clients already (max_connections=50)' between 2026-03-03T09:46:45Z and 2026-03-03T10:55:19Z (refs: L-0249)
  - [fact] orders-service logged 22x ERROR 'SQLTransientConnectionException: orders-db pool exhausted' between 2026-03-03T09:47:55Z and 2026-03-03T10:55:22Z (refs: L-0284)
  - [fact] orders-service logged 13x ERROR 'connection pool exhausted: timed out after 3000ms waiting for connection to orders-db' between 2026-03-03T09:54:07Z and 2026-03-03T10:51:54Z (refs: L-0287)
  - [fact] config change C-001: orders-db max_connections 500 -> 50 at 2026-03-03T09:44:00Z by dba-oncall (refs: C-001)

### 2. unknown in `frontend` - confidence 16%
unknown in frontend: own metrics anomalous: error_rate_pct x15.04; 15 own error logs; downstream services also implicated: ['orders-db', 'orders-service'] (may be a victim); deployment D-001 is not followed by any related anomaly
- **Supporting:**
  - [fact] frontend error_rate_pct moved from baseline 0.4 to 6.01 (x15.04), first anomalous at 2026-03-03T09:50:00Z (refs: M-frontend-error_rate_pct)
  - [fact] frontend logged 15x ERROR 'POST /api/orders failed: 504 Gateway Timeout' between 2026-03-03T09:58:11Z and 2026-03-03T10:53:22Z (refs: L-0319)
- **Contradicting:**
  - [fact] deployment D-001: frontend v9.8.0 at 2026-03-03T09:56:00Z (New promo banner component) (refs: D-001)
- **Assumptions:** no signal pins down the failure mechanism

### 3. deployment_bug in `orders-service` - confidence 12%
deployment bug in orders-service: own metrics anomalous: latency_p99_ms x16.2, error_rate_pct x30.02; 35 own error logs; named in 17 error/warn logs of ['api-gateway']; downstream services also implicated: ['orders-db'] (may be a victim)
- **Supporting:**
  - [fact] orders-service latency_p99_ms moved from baseline 179.68 to 2910.32 (x16.2), first anomalous at 2026-03-03T09:50:00Z (refs: M-orders-service-latency_p99_ms)
  - [fact] orders-service error_rate_pct moved from baseline 0.4 to 12.03 (x30.02), first anomalous at 2026-03-03T09:50:00Z (refs: M-orders-service-error_rate_pct)
  - [fact] orders-service logged 22x ERROR 'SQLTransientConnectionException: orders-db pool exhausted' between 2026-03-03T09:47:55Z and 2026-03-03T10:55:22Z (refs: L-0284)
  - [fact] orders-service logged 13x ERROR 'connection pool exhausted: timed out after 3000ms waiting for connection to orders-db' between 2026-03-03T09:54:07Z and 2026-03-03T10:51:54Z (refs: L-0287)
  - [fact] api-gateway logged 17x WARN 'upstream orders-service slow: 3021ms (route POST /api/orders)' between 2026-03-03T09:49:22Z and 2026-03-03T10:52:21Z (refs: L-0334)

## Facts (directly observed)
- deployment D-001: frontend v9.8.0 at 2026-03-03T09:56:00Z (New promo banner component)
- config change C-001: orders-db max_connections 500 -> 50 at 2026-03-03T09:44:00Z by dba-oncall
- frontend logged 15x ERROR 'POST /api/orders failed: 504 Gateway Timeout' between 2026-03-03T09:58:11Z and 2026-03-03T10:53:22Z
- frontend error_rate_pct moved from baseline 0.4 to 6.01 (x15.04), first anomalous at 2026-03-03T09:50:00Z
- orders-service logged 22x ERROR 'SQLTransientConnectionException: orders-db pool exhausted' between 2026-03-03T09:47:55Z and 2026-03-03T10:55:22Z
- orders-service logged 13x ERROR 'connection pool exhausted: timed out after 3000ms waiting for connection to orders-db' between 2026-03-03T09:54:07Z and 2026-03-03T10:51:54Z
- orders-service latency_p99_ms moved from baseline 179.68 to 2910.32 (x16.2), first anomalous at 2026-03-03T09:50:00Z
- orders-service error_rate_pct moved from baseline 0.4 to 12.03 (x30.02), first anomalous at 2026-03-03T09:50:00Z
- orders-db logged 35x ERROR 'FATAL: sorry, too many clients already (max_connections=50)' between 2026-03-03T09:46:45Z and 2026-03-03T10:55:19Z
- orders-db connections_active moved from baseline 140.6 to 50 (x0.36), first anomalous at 2026-03-03T09:45:00Z
- api-gateway logged 17x WARN 'upstream orders-service slow: 3021ms (route POST /api/orders)' between 2026-03-03T09:49:22Z and 2026-03-03T10:52:21Z

## Inferences and assumptions (not directly observed)
- no signal pins down the failure mechanism

## Recommended actions
- **P0** Revert the configuration change on orders-db - the change immediately preceded the first anomaly
- **P1** Route config/flag changes for orders-db through staged rollout with automatic rollback - config changes need the same safety as code

## Open questions
- no signal pins down the failure mechanism

## Investigation trace
- rounds: 1, termination: critic accepted in round 0
- tool calls: 29 (0 failed, 3 retried), LLM calls: 0, tokens: 0, latency: 0.38s
- critic round 0: **accept** - 
- tasks: OBS-1(recovered), DEP-2(recovered), REA-3(recovered), CRI-4(recovered), REP-5(recovered)
