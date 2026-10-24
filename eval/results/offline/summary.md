# Evaluation results (offline)

| metric | multi | single |
|---|---|---|
| accuracy | 1 | 0.583 |
| service_accuracy | 1 | 0.583 |
| cause_type_accuracy | 1 | 0.667 |
| top3_recall | 1 | 0.667 |
| confident_wrong | 0 | 0 |
| evidence_grounded_rate | 1.0 | 1.0 |
| key_evidence_recall | 0.924 | 0.424 |
| avg_tool_calls | 24.667 | 7.333 |
| avg_llm_calls | 0 | 0 |
| avg_tokens | 0 | 0 |
| avg_latency_s | 0.553 | 0.138 |
| p50_latency_s | 0.39 | 0.03 |

## Per incident

| incident | system | correct | predicted | expected | conf | grounded | key-ev recall | tools | llm | tokens | latency s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| INC-001 | multi | yes | deployment_bug@payment-service | deployment_bug@payment-service | 0.91 | 1.0 | 1.0 | 23 | 0 | 0 | 0.37 |
| INC-001 | single | yes | deployment_bug@payment-service | deployment_bug@payment-service | 0.72 | 1.0 | 0.333 | 7 | 0 | 0 | 0.03 |
| INC-002 | multi | yes | config_change@orders-db | config_change@orders-db | 0.82 | 1.0 | 1.0 | 29 | 0 | 0 | 0.38 |
| INC-002 | single | NO | unknown@frontend | config_change@orders-db | 0.58 | 1.0 | 0.0 | 7 | 0 | 0 | 0.03 |
| INC-003 | multi | yes | dependency_outage@payment-gateway-ext | dependency_outage@payment-gateway-ext | 0.64 | 1.0 | 0.667 | 18 | 0 | 0 | 0.68 |
| INC-003 | single | NO | dependency_outage@payment-service | dependency_outage@payment-gateway-ext | 0.55 | 1.0 | 0.333 | 8 | 0 | 0 | 0.33 |
| INC-004 | multi | yes | resource_exhaustion@recommendation-service | resource_exhaustion@recommendation-service | 0.75 | 1.0 | 1.0 | 17 | 0 | 0 | 0.36 |
| INC-004 | single | yes | resource_exhaustion@recommendation-service | resource_exhaustion@recommendation-service | 0.75 | 1.0 | 1.0 | 7 | 0 | 0 | 0.03 |
| INC-005 | multi | yes | traffic_spike@api-gateway | traffic_spike@api-gateway | 0.66 | 1.0 | 0.5 | 27 | 0 | 0 | 0.4 |
| INC-005 | single | yes | traffic_spike@api-gateway | traffic_spike@api-gateway | 0.66 | 1.0 | 0.5 | 7 | 0 | 0 | 0.03 |
| INC-006 | multi | yes | certificate_expiry@auth-service | certificate_expiry@auth-service | 0.55 | 1.0 | 1.0 | 29 | 0 | 0 | 0.39 |
| INC-006 | single | yes | certificate_expiry@auth-service | certificate_expiry@auth-service | 0.54 | 1.0 | 0.5 | 7 | 0 | 0 | 0.03 |
| INC-007 | multi | yes | config_change@redis-cache | config_change@redis-cache | 0.71 | 1.0 | 1.0 | 28 | 0 | 0 | 2.12 |
| INC-007 | single | NO | inconclusive | config_change@redis-cache | 0.0 | None | 0.0 | 10 | 0 | 0 | 1.05 |
| INC-008 | multi | yes | deployment_bug@inventory-service | deployment_bug@inventory-service | 0.79 | 1.0 | 1.0 | 21 | 0 | 0 | 0.39 |
| INC-008 | single | NO | inconclusive | deployment_bug@inventory-service | 0.37 | 1.0 | 0.0 | 8 | 0 | 0 | 0.03 |
| INC-009 | multi | yes | inconclusive | inconclusive | 0.1 | 1.0 | None | 18 | 0 | 0 | 0.39 |
| INC-009 | single | yes | inconclusive | inconclusive | 0.0 | None | None | 6 | 0 | 0 | 0.01 |
| INC-010 | multi | yes | config_change@api-gateway | config_change@api-gateway | 0.56 | 1.0 | 1.0 | 43 | 0 | 0 | 0.43 |
| INC-010 | single | yes | config_change@api-gateway | config_change@api-gateway | 0.61 | 1.0 | 1.0 | 7 | 0 | 0 | 0.03 |
| INC-011 | multi | yes | config_change@notification-service | config_change@notification-service | 0.84 | 1.0 | 1.0 | 14 | 0 | 0 | 0.36 |
| INC-011 | single | yes | config_change@notification-service | config_change@notification-service | 0.84 | 1.0 | 1.0 | 7 | 0 | 0 | 0.03 |
| INC-012 | multi | yes | resource_exhaustion@orders-db | resource_exhaustion@orders-db | 0.64 | 1.0 | 1.0 | 29 | 0 | 0 | 0.37 |
| INC-012 | single | NO | unknown@frontend | resource_exhaustion@orders-db | 0.58 | 1.0 | 0.0 | 7 | 0 | 0 | 0.03 |
