# Incident investigation report - INC-006 (multi-agent)

**Outcome:** CONCLUSIVE - certificate_expiry in `auth-service` (confidence 55%)

Most likely root cause: certificate expiry in auth-service (confidence 55%). certificate expiry in auth-service: own metrics anomalous: request_rate_rps x0.05; named in 37 error/warn logs of ['api-gateway']; deepest implicated node in the dependency chain; log keywords indicate certificate_expiry

## Ranked hypotheses
### 1. certificate_expiry in `auth-service` - confidence 55%
certificate expiry in auth-service: own metrics anomalous: request_rate_rps x0.05; named in 37 error/warn logs of ['api-gateway']; deepest implicated node in the dependency chain; log keywords indicate certificate_expiry
- **Supporting:**
  - [fact] auth-service request_rate_rps moved from baseline 216.47 to 10.89 (x0.05), first anomalous at 2026-03-14T00:00:00Z (refs: M-auth-service-request_rate_rps)
  - [fact] api-gateway logged 20x ERROR 'TLS handshake with auth-service failed: x509: certificate has expired or is not yet valid' between 2026-03-14T00:02:04Z and 2026-03-14T00:53:41Z (refs: L-0205)
  - [fact] api-gateway logged 17x ERROR 'upstream auth-service connect error: certificate expired (notAfter=2026-03-14T00:00:00Z)' between 2026-03-14T00:00:37Z and 2026-03-14T00:54:26Z (refs: L-0204)

### 2. certificate_expiry in `api-gateway` - confidence 44%
certificate expiry in api-gateway: own metrics anomalous: error_rate_pct x86.98; 37 own error logs; named in 12 error/warn logs of ['auth-service']; downstream services also implicated: ['auth-service'] (may be a victim)
- **Supporting:**
  - [fact] api-gateway error_rate_pct moved from baseline 0.4 to 34.94 (x86.98), first anomalous at 2026-03-14T00:00:00Z (refs: M-api-gateway-error_rate_pct)
  - [fact] api-gateway logged 20x ERROR 'TLS handshake with auth-service failed: x509: certificate has expired or is not yet valid' between 2026-03-14T00:02:04Z and 2026-03-14T00:53:41Z (refs: L-0205)
  - [fact] api-gateway logged 17x ERROR 'upstream auth-service connect error: certificate expired (notAfter=2026-03-14T00:00:00Z)' between 2026-03-14T00:00:37Z and 2026-03-14T00:54:26Z (refs: L-0204)
  - [fact] auth-service logged 12x WARN 'inbound TLS handshake failure from api-gateway' between 2026-03-14T00:03:03Z and 2026-03-14T00:58:47Z (refs: L-0241)

### 3. unknown in `redis-cache` - confidence 26%
unknown in redis-cache: own metrics anomalous: evictions_per_min x1.64; deepest implicated node in the dependency chain; historical incident(s) ['H-003'] involved redis-cache (lead only)
- **Supporting:**
  - [fact] redis-cache evictions_per_min moved from baseline 19.72 to 32.29 (x1.64), first anomalous at 2026-03-13T23:40:00Z (refs: M-redis-cache-evictions_per_min)
- **Assumptions:** no signal pins down the failure mechanism

## Facts (directly observed)
- auth-service logged 12x WARN 'inbound TLS handshake failure from api-gateway' between 2026-03-14T00:03:03Z and 2026-03-14T00:58:47Z
- auth-service request_rate_rps moved from baseline 216.47 to 10.89 (x0.05), first anomalous at 2026-03-14T00:00:00Z
- api-gateway logged 20x ERROR 'TLS handshake with auth-service failed: x509: certificate has expired or is not yet valid' between 2026-03-14T00:02:04Z and 2026-03-14T00:53:41Z
- api-gateway logged 17x ERROR 'upstream auth-service connect error: certificate expired (notAfter=2026-03-14T00:00:00Z)' between 2026-03-14T00:00:37Z and 2026-03-14T00:54:26Z
- api-gateway error_rate_pct moved from baseline 0.4 to 34.94 (x86.98), first anomalous at 2026-03-14T00:00:00Z
- redis-cache evictions_per_min moved from baseline 19.72 to 32.29 (x1.64), first anomalous at 2026-03-13T23:40:00Z

## Inferences and assumptions (not directly observed)
- none

## Recommended actions
- **P0** Rotate the expired certificate on auth-service - TLS handshakes are failing on expiry
- **P1** Automate certificate renewal and alert 30 days before expiry - prevent recurrence

## Investigation trace
- rounds: 1, termination: critic accepted in round 0
- tool calls: 29 (0 failed, 3 retried), LLM calls: 0, tokens: 0, latency: 0.39s
- critic round 0: **accept** - 
- tasks: OBS-1(recovered), DEP-2(recovered), REA-3(recovered), CRI-4(recovered), REP-5(recovered)
