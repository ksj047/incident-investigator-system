# Full-stack demo narration

## terminal (starts 0s)

This recording walks through the full stack I built around the investigation engine: a Python backend that serves the agents over HTTP, and a browser frontend that shows an investigation as it happens. We start in the terminal. The backend is a single Python server built only on the standard library, with no web framework. On startup it reports which language model backends are available. There is no OpenRouter key here, so investigations use the deterministic agent paths. A health check returns JSON. The investigate endpoint streams server-sent events: one per task change, tool call, piece of evidence, hypothesis update and critique, and finally the report. The test suite now has twenty-six tests, including five that start the server and exercise the API end to end.

## overview (starts 54s)

This is the frontend: plain HTML, CSS and JavaScript, served by the same backend, with no build step. On the left are the twelve incidents. The top bar shows the selected incident and the run controls: multi-agent or single-agent, the LLM backend, and a playback speed. Offline runs finish in under a second, so demo speed replays the server's stream at a watchable pace. Below are live counters, and six panels: the agents, the service dependency graph, the live activity feed, the critic, the competing hypotheses, and the evidence board. At the bottom is the backend console, a live stream of the server's own log.

## api (starts 96s)

The Backend API tab calls the server directly. Health reports status and which backends are available. The incident list exposes only public fields; ground truth is never served to the investigators or to this list. An incident's detail includes its dependency graph and data volumes. The investigate endpoint is a server-sent event stream, and here are the raw events arriving: the start, tasks, tool calls, evidence, and the final report. Each request also shows up in the backend console below.

## run_multi (starts 128s)

Now a real investigation. Incident two: order placement timeouts, where a frontend deploy went out minutes before the report. I run the multi-agent investigator. The orchestrator dispatches the observability and dependency agents in parallel, and you can see both running at once. Each tool call appears in the activity feed with its status, and the backend console logs the same calls on the server side. The dependency graph lights up as services are examined. Blue means examined, amber means anomalies or errors, and the purple dot marks a recent change. Notice how the observability agent follows the trail: from the frontend to the API gateway, whose logs name the orders service, and from there to the orders database. Evidence lands on the board as facts with record ids. Then the reasoning agent ranks competing hypotheses, and the critic reviews them.

## report (starts 182s)

The result: a configuration change on the orders database, at eighty-two percent confidence, accepted by the critic in the first round. The report drawer shows the outcome and the ranked hypotheses, with supporting and contradicting evidence, each citing record ids. The frontend deploy is listed as contradicting evidence, because it happened after the frontend's own errors began. Below are the recommended actions, the facts kept separate from inferences and assumptions, and the critic's verdicts. Scoring against ground truth, which only the evaluation endpoint reads, confirms the answer is correct.

## single (starts 221s)

For comparison, here is the same incident with the single-agent baseline. It has the same tools and budgets, but makes one pass, with no specialists and no critic. It examines the reported service and the change history, and stops at the loud symptom: it blames the frontend, with an unknown mechanism. Scoring confirms it is wrong. This is the failure mode the multi-agent design is built to avoid.

## loop (starts 246s)

Incident ten shows the feedback loop. User-service is overloaded, and it had its own deploy that morning. In round one, the reasoning agent leans toward a configuration change on the API gateway. But the critic objects: the gateway's downstream services were never examined, so the gateway might itself be a victim. It sends follow-up tasks back to the observability agent. Watch the round counter move to two while those services are checked. With that evidence, the critic accepts. The gateway's retry policy was changed from one attempt to five, with no backoff, two minutes before user-service fell over. It's a retry storm, and user-service is the victim.

## failures (starts 288s)

Incident seven is about failing tools. Log queries for the search service, the cache and the product database always time out. In the feed, failed calls appear in red with their attempt counts. The executor retried each one with backoff before giving up, and the graph marks those services with dashed red borders. The investigation keeps going. The observability agent widens its search and re-queries the partial metrics, and the dependency agent finds that the cache TTL was cut from an hour to five seconds. The conclusion rests on metrics and change history, and the critic records that log data was unavailable.

## inconclusive (starts 326s)

Incident nine is deliberately vague: intermittent slowness, no changes, and incomplete metrics. The system does not invent a cause. Its only hypothesis names no component, at ten percent. The critic rules the evidence insufficient, and the report says inconclusive, recommending better telemetry instead of a guess. Scoring confirms that is the expected answer.

## evaluation (starts 350s)

The Evaluation tab loads the evaluation results from the backend. On the offline result set, the multi-agent system solved twelve out of twelve and the single agent seven. Key-evidence recall is point nine two versus point four two, and neither system gave a confidently wrong answer. The price is about three times more tool calls. The per-incident table shows exactly where the single agent failed: loud victims, and culprits it never examined. These numbers come from the deterministic agents. With an OpenRouter key, the same screen shows the live LLM comparison, including LLM calls and tokens.

## console (starts 388s)

Finally, the backend console. Every HTTP request, every agent tool call and recovery, and every finished run is logged by the server and streamed here over a second event stream, so you can watch the frontend and backend side by side. Everything shown is in the repository: the server in the server folder, the frontend in the web folder, and the API tests next to the original suite. Start it with python three dash m server dot app, and open localhost port eight thousand. Thanks for watching.
