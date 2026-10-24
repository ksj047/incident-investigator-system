# Walkthrough narration script

## Slide 1

Hi, and welcome. This is my submission for the AI engineer assignment: a multi-agent system that investigates production incidents. In about ten minutes I will cover the problem, the architecture and how the agents coordinate, the tools and their failures, how conclusions are grounded in evidence, the incident dataset, a few real runs, and the evaluation against a single-agent baseline, including the limitations. It is plain Python with no runtime dependencies, and it reaches language models through OpenRouter, using a cheap model by default with a free fallback.

## Slide 2

The system receives an incident report: symptoms, an onset time and the service where the problem was noticed. It can query logs, metrics, deployments, configuration changes, the dependency graph and past incidents. That data may be incomplete, contradictory or misleading, and the tools can time out or return partial results. The output must be ranked hypotheses with supporting and contradicting evidence, confidence, actions, and a clear split between facts and assumptions. And it must be allowed to say "inconclusive". Finally, the agents have to genuinely collaborate. A chain of prompts is not enough, and that was my main design driver.

## Slide 3

Here is the architecture. The orchestrator receives the incident, asks the model for a plan, validates it and turns it into a small graph of tasks with dependencies. In each round, the observability agent, working with logs and metrics, and the dependency agent, working with deployments, configuration, topology and history, run in parallel, each in its own bounded tool loop. Everything they find goes onto a shared blackboard: typed evidence, hypotheses, tasks, critiques, every tool call, and the budget. The reasoning agent builds competing hypotheses from that board. The critic then challenges the leader. If the critic says "investigate", its follow-up requests become the next round's tasks. That is the orange feedback loop. When it accepts, or rules the evidence insufficient, the reporting agent writes the report. Every tool call goes through a layer with validation, timeouts, retries, budgets and fault injection, and every agent has a deterministic fallback.

## Slide 4

Here is a real trace from incident ten, a retry storm. In round zero, the observability and dependency tasks run in parallel, reasoning waits for both, and the critic waits for reasoning. The leading hypothesis blamed a configuration change on the API gateway. But the critic noticed that services downstream of the suspect had never been examined, so it could not rule out that the gateway was a victim. It returned "investigate", with structured follow-ups naming the agent, the goal and the services. In round one, the observability agent checked those services, reasoning re-ranked, and the critic accepted. So what a specialist does in round one is decided by the critic's objection to round zero. That is the collaboration. The loop is bounded by three rounds, step limits, and budgets on tool calls, model calls, tokens and time, and it always ends with a report.

## Slide 5

There are six tools, covering logs, metrics, deployments, configuration, dependencies and history. Each has a declared schema. Bad arguments return structured, non-retryable errors instead of exceptions. Results are compact and easy to analyze: log message counts with first-seen times and example record ids, and metric summaries with a baseline, a change ratio and the first anomalous timestamp. Each incident can script failures: a call that hangs until the timeout fires, partial results with missing data, or an HTTP five-oh-three. A random chaos rate adds more. The executor applies timeouts and up to two retries with backoff, and it checks the budget. If a call still fails, that failure becomes evidence, so the other agents know what the team could not see.

## Slide 6

Every evidence item is typed as a fact, an inference or an assumption, and it carries the dataset record ids it rests on. Each cited id is checked against what the tools actually returned. Unknown ids are dropped, and a claimed fact with no valid reference is downgraded to an assumption and counted, so hallucinated evidence becomes a measurable number. Hypotheses must cite evidence for and against. Without support, confidence is capped at twenty percent. The report separates observed facts from inferences and assumptions, and if the best hypothesis is below forty-five percent after the final round, the outcome is inconclusive.

## Slide 7

The OpenRouter client defaults to DeepSeek V4 Flash, about nine cents per million input tokens, with a free Gemma fallback. It retries on rate limits, walks a model fallback list and records real token usage. Agents use a small JSON action protocol instead of native function calling, so any model works. Replies are parsed tolerantly and validated, and the model is re-asked with the exact error a bounded number of times. If the model fails or crashes, that agent's deterministic fallback takes over with the same tools, and the task is marked recovered. The same analytics give the critic an independent cross-check, and they power an offline mode that runs everything without an API key.

## Slide 8

For evaluation I generated twelve incidents. Each is a full world: fifteen services, seven hours of noisy logs and metrics, changes, a dependency graph, history and a fault profile. Each one has a trap. In incident two, a frontend deploy lands just before the report, but the cause is a database connection limit cut from five hundred to fifty. In four, the real cause is a slow memory leak from a deploy five hours earlier. In six, a near-identical past incident blames the cache, but the cause is an expired certificate. In seven, log queries for the key services always time out. In eight, the loudest symptom belongs to a victim. Nine is designed to be inconclusive, and twelve is a cascading failure from a full disk. Ground truth sits in a separate folder that only the evaluator reads, and a test enforces that.

## Slide 9

Here is a real run of incident two. The result is conclusive: a configuration change on the orders database, at eighty-two percent confidence. Every piece of supporting evidence is a fact with a record id. Connections flattened at fifty, the database logged "too many clients", and max connections was lowered one minute before the first anomaly. The frontend hypothesis is contradicted, because its deploy happened after the frontend's errors had started. The P-zero action is to revert the change. The observability agent got here by following leads: from the frontend, to the gateway log naming the orders service, to the database. The single agent stopped at the frontend.

## Slide 10

In incident seven, every log query for the key services times out, even after retries. The observability agent widens its search to the dependencies it cannot observe, re-queries truncated metrics, and finds the cache hit rate collapsing. The dependency agent finds that the cache TTL was cut from an hour to five seconds. The critic records that logs were unavailable and that the conclusion relies on other sources. In incident nine there are no changes, the signal is weak, and the metrics stay incomplete. The system does not invent a story. It reports inconclusive and recommends better telemetry.

## Slide 11

Now the comparison. Both systems use the same tools, budgets and report schema. The baseline is a single agent with no specialists and no critique loop. A case counts as correct when both the service and the cause type are right. For incident nine, the right answer is inconclusive. I also measure top-three recall, confidently wrong answers, grounding, key-evidence recall and cost. On the offline backend, the multi-agent system got 12 out of 12, and the single agent got 7. Key-evidence recall is 0.92 versus 0.42. Neither system was confidently wrong. The price is breadth: about 25 tool calls per incident versus 7. The single agent missed exactly the traps that punish one-pass investigation: blaming a loud victim, or never examining what actually changed.

## Slide 12

What made the difference? First, the critic's objections: "the suspect may be a victim" and "no failure mechanism yet" each trigger a targeted follow-up round. Second, lead-following: services named in errors, and dependencies of anomalous or unobservable services. Third, timing: a change after the symptoms counts as contradicting evidence, and history is a lead, never proof. The cost is about three times more tool calls, plus more model calls and tokens with an LLM. Bounded rounds and a stagnation guard keep that predictable.

## Slide 13

There are twenty-one automated tests. They cover dataset integrity, ground-truth isolation, tool validation, timeouts and retries, partial results, budgets, the feedback loop and the inconclusive outcome. The language model path is tested with a scripted model. A fabricated fact gets downgraded, a garbage critic reply gets recovered by the rules, and a crashing agent falls back to the deterministic path. One command runs each incident, the baseline, or the full evaluation.

## Slide 14

Now the limitations. These results come from the offline deterministic agents, because there was no OpenRouter key in my build environment. The language model path is implemented and tested, and a live run on the cheap default model is a single command costing well under fifty cents. I also developed the heuristics on these same twelve incidents, so the accuracy is optimistic, not held-out. The world is simulated, the dataset is small, and confidence is not formally calibrated. Next steps are a varied held-out dataset, calibration metrics, hypothesis-driven queries, a shared tool cache, native function calling, and real Prometheus, Loki and Kubernetes adapters.

## Slide 15

To summarize: six agents collaborate on a shared blackboard. They plan, gather evidence in parallel, compete on hypotheses, criticize and loop, then write a grounded report that can say "inconclusive". The tools fail realistically, and the system recovers. The dataset, tests, evaluation, technical note and transcript are all in the repository, and the README explains how to run them. Thanks for watching.
