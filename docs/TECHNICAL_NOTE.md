# Technical note: key decisions, trade-offs, limitations

**Blackboard plus task DAG, not a prompt chain.** All agents share one typed state: evidence, hypotheses, tasks, critiques, tool calls, budget. Each round is a small DAG (`specialists -> reasoning -> critic`) where independent tasks run concurrently. The critic's structured follow-ups become the next round's tasks, so what the Observability agent examines in round 2 is decided by the critic's objection to the round-1 hypothesis.

**Grounded evidence.** Tools return dataset record ids, and agents must cite them. Each citation is checked against what tools actually returned. An unsupported "fact" is downgraded to an assumption, and a hypothesis without support is capped at 0.2 confidence. This makes hallucination measurable and keeps facts and assumptions separate.

**A deterministic fallback for every agent.** Each agent has an LLM path and a rule-based path that uses the same tools. Any LLM failure (network, quota, invalid JSON after bounded re-asks) degrades that one task to `recovered` instead of killing the investigation. The same analytics power the critic's independent cross-check and an offline mode that runs with no API key. Trade-off: the rules encode SRE priors (a change shortly before the first anomaly; the cause sits at the bottom of the blast radius; logs naming a service are leads), and those priors can be wrong.

**A JSON action protocol instead of native tool calling.** This keeps every OpenRouter model usable, including free ones without function-calling. Tolerant JSON extraction, schema validation and corrective re-asks recover most of the lost robustness.

**The critic combines an LLM and rules.** An LLM critic alone tends to accept plausible stories. The rule checks (cause after effect, fewer than two facts, no separation between the top two, unexplored downstream dependencies, data gaps, topology/timeline disagreement) give it concrete reasons to send work back. In the final round, the system must accept or declare the incident inconclusive below 0.45 confidence.

**Trade-offs observed.** The multi-agent system makes about 3.4 times as many tool calls as the single agent (25 vs 7 offline) and, with an LLM, many more tokens. It buys that with breadth: it solved all five incidents where the single agent stopped at a loud victim or never examined the culprit. Bounded rounds, step limits and a stagnation guard cap the cost.

**Limitations.**
- The LLM-backed evaluation has not been run yet (no key in the build environment). The offline results use the deterministic agents.
- The heuristics were developed against the same 12 incidents, so the offline accuracy is optimistic, not held-out.
- The world is simulated. Real telemetry is larger and noisier.
- Confidence is not formally calibrated.
- Twelve incidents is too few for statistical claims.

**Improvements.**
- A held-out, procedurally varied incident set.
- Calibration metrics (Brier score, reliability curves).
- Letting the reasoning agent request specific discriminating queries.
- A cross-agent tool-result cache.
- Native function-calling where supported.
- Prometheus, Loki and Kubernetes adapters in place of the simulated `ToolBox`.
- Heuristic weights learned from labelled post-mortems.
