# Incident investigation report - INC-008 (multi-agent)

**Outcome:** CONCLUSIVE - deployment_bug in `inventory-service` (confidence 79%)

Most likely root cause: deployment bug in inventory-service (confidence 79%). deployment bug in inventory-service: own metrics anomalous: error_rate_pct x62.76; 31 own error logs; named in 17 error/warn logs of ['product-db']; deepest implicated node in the dependency chain

## Ranked hypotheses
### 1. deployment_bug in `inventory-service` - confidence 79%
deployment bug in inventory-service: own metrics anomalous: error_rate_pct x62.76; 31 own error logs; named in 17 error/warn logs of ['product-db']; deepest implicated node in the dependency chain
- **Supporting:**
  - [fact] inventory-service error_rate_pct moved from baseline 0.4 to 25.05 (x62.76), first anomalous at 2026-03-20T08:55:00Z (refs: M-inventory-service-error_rate_pct)
  - [fact] inventory-service logged 31x ERROR 'stock check failed: product-db query timeout' between 2026-03-20T08:54:14Z and 2026-03-20T09:54:30Z (refs: L-0276)
  - [fact] product-db logged 17x ERROR 'lock wait timeout exceeded on table products (holder: inventory-service migration)' between 2026-03-20T08:53:20Z and 2026-03-20T09:54:07Z (refs: L-0244)
  - [fact] deployment D-001: inventory-service v7.1.0 at 2026-03-20T08:52:00Z (Add column warehouse_zone to products table (online migration)) (refs: D-001)

### 2. deployment_bug in `product-db` - confidence 43%
deployment bug in product-db: own metrics anomalous: query_latency_ms x39.92; 32 own error logs; named in 62 error/warn logs of ['inventory-service', 'search-service']; deepest implicated node in the dependency chain
- **Supporting:**
  - [fact] product-db query_latency_ms moved from baseline 12.06 to 481.57 (x39.92), first anomalous at 2026-03-20T08:55:00Z (refs: M-product-db-query_latency_ms)
  - [fact] product-db logged 17x ERROR 'lock wait timeout exceeded on table products (holder: inventory-service migration)' between 2026-03-20T08:53:20Z and 2026-03-20T09:54:07Z (refs: L-0244)
  - [fact] product-db logged 15x ERROR 'ALTER TABLE products ADD COLUMN warehouse_zone ... waiting for metadata lock' between 2026-03-20T09:21:37Z and 2026-03-20T09:56:29Z (refs: L-0258)
  - [fact] search-service logged 31x WARN 'product-db query slow, retrying (attempt 3)' between 2026-03-20T08:54:57Z and 2026-03-20T09:54:44Z (refs: L-0307)
  - [fact] inventory-service logged 31x ERROR 'stock check failed: product-db query timeout' between 2026-03-20T08:54:14Z and 2026-03-20T09:54:30Z (refs: L-0276)

## Facts (directly observed)
- deployment D-001: inventory-service v7.1.0 at 2026-03-20T08:52:00Z (Add column warehouse_zone to products table (online migration))
- search-service logged 31x WARN 'product-db query slow, retrying (attempt 3)' between 2026-03-20T08:54:57Z and 2026-03-20T09:54:44Z
- product-db logged 17x ERROR 'lock wait timeout exceeded on table products (holder: inventory-service migration)' between 2026-03-20T08:53:20Z and 2026-03-20T09:54:07Z
- product-db logged 15x ERROR 'ALTER TABLE products ADD COLUMN warehouse_zone ... waiting for metadata lock' between 2026-03-20T09:21:37Z and 2026-03-20T09:56:29Z
- product-db query_latency_ms moved from baseline 12.06 to 481.57 (x39.92), first anomalous at 2026-03-20T08:55:00Z
- inventory-service logged 31x ERROR 'stock check failed: product-db query timeout' between 2026-03-20T08:54:14Z and 2026-03-20T09:54:30Z
- inventory-service error_rate_pct moved from baseline 0.4 to 25.05 (x62.76), first anomalous at 2026-03-20T08:55:00Z

## Inferences and assumptions (not directly observed)
- none

## Recommended actions
- **P0** Roll back inventory-service to the previous version - restores service fastest; deploy is the prime suspect
- **P1** Add a regression test and canary analysis gate for inventory-service - catch this class of defect before full rollout

## Investigation trace
- rounds: 1, termination: critic accepted in round 0
- tool calls: 21 (0 failed, 4 retried), LLM calls: 0, tokens: 0, latency: 0.39s
- critic round 0: **accept** - 
- tasks: OBS-1(recovered), DEP-2(recovered), REA-3(recovered), CRI-4(recovered), REP-5(recovered)
