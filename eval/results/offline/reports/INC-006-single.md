# Incident investigation report - INC-006 (single-agent)

**Outcome:** CONCLUSIVE - certificate_expiry in `auth-service` (confidence 54%)

Most likely root cause: certificate expiry in auth-service (confidence 54%). certificate_expiry in auth-service: own metrics anomalous: request_rate_rps x0.05; deepest implicated node in the dependency chain; log keywords indicate certificate_expiry

## Ranked hypotheses
### 1. certificate_expiry in `auth-service` - confidence 54%
certificate_expiry in auth-service: own metrics anomalous: request_rate_rps x0.05; deepest implicated node in the dependency chain; log keywords indicate certificate_expiry
- **Supporting:**
  - [fact] auth-service request_rate_rps moved from baseline 216.47 to 10.89 (x0.05), first anomalous at 2026-03-14T00:00:00Z (refs: M-auth-service-request_rate_rps)

### 2. certificate_expiry in `api-gateway` - confidence 29%
certificate_expiry in api-gateway: named in 12 error/warn logs of ['auth-service']; downstream services also implicated: ['auth-service'] (may be a victim); log keywords indicate certificate_expiry
- **Supporting:**
  - [fact] auth-service logged 12x WARN 'inbound TLS handshake failure from api-gateway' between 2026-03-14T00:03:03Z and 2026-03-14T00:58:47Z (refs: L-0241)

## Facts (directly observed)
- auth-service logged 12x WARN 'inbound TLS handshake failure from api-gateway' between 2026-03-14T00:03:03Z and 2026-03-14T00:58:47Z
- auth-service request_rate_rps moved from baseline 216.47 to 10.89 (x0.05), first anomalous at 2026-03-14T00:00:00Z

## Inferences and assumptions (not directly observed)
- none

## Recommended actions
- **P0** Rotate the expired certificate on auth-service - TLS handshakes are failing on expiry
- **P1** Automate certificate renewal and alert 30 days before expiry - prevent recurrence

## Investigation trace
- rounds: 1, termination: LLM path failed (LLMUnavailable); heuristic single pass
- tool calls: 7 (0 failed, 1 retried), LLM calls: 0, tokens: 0, latency: 0.03s
- tasks: SINGLE-1(recovered)
