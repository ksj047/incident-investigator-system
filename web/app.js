/* Incident Investigator - web frontend (vanilla JS, no build step). */
"use strict";

const $ = (s) => document.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (x) => `${Math.round((x || 0) * 100)}%`;

const AGENTS = {
  orchestrator: { label: "Orchestrator", color: "#f97316", desc: "plans · schedules DAG · loops" },
  observability: { label: "Observability", color: "#38bdf8", desc: "logs + metrics" },
  dependency: { label: "Dependency", color: "#38bdf8", desc: "deploys · config · topology · history" },
  reasoning: { label: "Reasoning", color: "#a78bfa", desc: "competing hypotheses" },
  critic: { label: "Critic", color: "#f472b6", desc: "challenges the leader" },
  reporting: { label: "Reporting", color: "#34d399", desc: "report + actions" },
  single_agent: { label: "Single agent", color: "#fbbf24", desc: "one agent, all tools" },
};

const app = {
  health: null, incidents: [], incident: null, mode: "multi",
  run: null, es: null, timer: null,
};

/* ------------------------------------------------------------------ boot */
async function api(path) {
  const r = await fetch(path);
  const body = await r.json();
  if (!r.ok) throw new Error(body.error || r.statusText);
  return body;
}

async function boot() {
  bindUI();
  connectConsole();
  try {
    app.health = await api("/api/health");
    const b = app.health.backends;
    $("#apiStatus").innerHTML = `<span class="dot ok"></span><span>API online · ${app.health.incidents} incidents · LLM: ${b.openrouter ? esc(b.model) : "offline mode (no key)"}</span>`;
    const opt = $('#backendSel option[value="openrouter"]');
    opt.disabled = !b.openrouter;
    if (!b.openrouter) opt.textContent = "OpenRouter LLM (no API key on server)";
    $("#backendSel").value = b.openrouter ? "openrouter" : "offline";
  } catch (e) {
    $("#apiStatus").innerHTML = `<span class="dot bad"></span><span>API unreachable</span>`;
  }
  app.incidents = await api("/api/incidents");
  $("#incCount").textContent = app.incidents.length;
  $("#incidentList").innerHTML = app.incidents.map((i) => `
    <div class="inc-item" data-id="${esc(i.id)}">
      <div class="row"><span class="mono">${esc(i.id)}</span><span class="sev ${esc(i.severity)}">${esc(i.severity)}</span><span>${esc(i.reported_service)}</span></div>
      <div class="t">${esc(i.title)}</div>
    </div>`).join("");
  document.querySelectorAll(".inc-item").forEach((el) => el.addEventListener("click", () => selectIncident(el.dataset.id)));
  renderStats();
  renderPipeline();
  const first = new URLSearchParams(location.search).get("incident") || app.incidents[0]?.id;
  if (first) selectIncident(first);
  buildEndpoints();
  loadEvalSets();
}

function bindUI() {
  document.querySelectorAll("#tabs button").forEach((b) => b.addEventListener("click", () => showView(b.dataset.view)));
  document.querySelectorAll("#modeSeg button").forEach((b) => b.addEventListener("click", () => {
    if (app.run?.running) return;
    app.mode = b.dataset.mode;
    document.querySelectorAll("#modeSeg button").forEach((x) => x.classList.toggle("active", x === b));
    renderPipeline();
  }));
  $("#runBtn").addEventListener("click", runInvestigation);
  $("#reportBtn").addEventListener("click", () => openDrawer(true));
  $("#drawerClose").addEventListener("click", () => openDrawer(false));
  $("#scrim").addEventListener("click", () => openDrawer(false));
  $("#dockToggle").addEventListener("click", () => {
    document.body.classList.toggle("dock-collapsed");
    $("#dockToggle").textContent = document.body.classList.contains("dock-collapsed") ? "show" : "hide";
  });
  $("#evalSel").addEventListener("change", () => loadEval($("#evalSel").value));
}

function showView(v) {
  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("active", b.dataset.view === v));
  document.querySelectorAll(".view").forEach((s) => s.classList.toggle("active", s.id === `view-${v}`));
}

/* --------------------------------------------------------------- incident */
async function selectIncident(id) {
  if (app.run?.running) return;
  document.querySelectorAll(".inc-item").forEach((el) => el.classList.toggle("active", el.dataset.id === id));
  const d = await api(`/api/incidents/${encodeURIComponent(id)}`);
  app.incident = d;
  const i = d.incident;
  $("#incId").textContent = i.id;
  $("#incSev").textContent = i.severity;
  $("#incSev").className = `sev ${i.severity}`;
  $("#incTitle").textContent = i.title;
  $("#incMeta").innerHTML = `<span>reported service <b>${esc(i.reported_service)}</b></span>
    <span>symptom onset <b>${esc(i.symptom_onset.replace("T", " ").replace("Z", " UTC"))}</b></span>
    <span>data: <b>${d.volumes.logs}</b> log lines · <b>${d.volumes.metric_series}</b> metric series · <b>${d.volumes.deployments}</b> deploys · <b>${d.volumes.config_changes}</b> config changes · <b>${d.volumes.history}</b> past incidents</span>`;
  $("#incDesc").textContent = i.description;
  $("#runBtn").disabled = false;
  resetRun();
}

function resetRun() {
  app.run = { running: false, tasks: {}, evidence: [], hyps: [], critiques: [], feed: 0, tools: 0, failed: 0, retried: 0,
              llm: 0, tokens: 0, round: 0, started: 0, elapsed: 0, report: null, runId: null,
              svc: {} };
  $("#feed").innerHTML = "";
  $("#feedCount").textContent = "";
  $("#evidence").innerHTML = `<div class="empty">Shared blackboard: every finding with its record ids.</div>`;
  $("#hyps").innerHTML = `<div class="empty">Hypotheses appear once evidence is gathered.</div>`;
  $("#critic").innerHTML = `<div class="empty">The critic reviews each round's hypotheses.</div>`;
  $("#evCount").textContent = "";
  $("#hypHint").textContent = "";
  $("#roundHint").textContent = "idle";
  $("#reportBtn").disabled = true;
  $("#reportBtn").classList.remove("pulse");
  renderStats();
  renderPipeline();
  renderGraph();
}

/* ------------------------------------------------------------------ run */
function runInvestigation() {
  if (!app.incident || app.run?.running) return;
  resetRun();
  const r = app.run;
  r.running = true;
  r.started = performance.now();
  const btn = $("#runBtn");
  btn.disabled = true; btn.classList.add("running"); btn.textContent = "Investigating…";
  app.timer = setInterval(() => { r.elapsed = (performance.now() - r.started) / 1000; renderStats(); }, 200);
  const qs = new URLSearchParams({ incident: app.incident.incident.id, mode: app.mode, backend: $("#backendSel").value, pace_ms: $("#paceSel").value });
  const es = new EventSource(`/api/investigate?${qs}`);
  app.es = es;
  es.onmessage = (m) => onEvent(JSON.parse(m.data));
  es.onerror = () => { if (r.running) finishRun("stream closed"); };
}

function finishRun(err) {
  const r = app.run;
  r.running = false;
  clearInterval(app.timer);
  app.es?.close();
  const btn = $("#runBtn");
  btn.disabled = false; btn.classList.remove("running"); btn.textContent = "Run again";
  if (err && !r.report) feed("system", `<span class="fm">${esc(err)}</span>`, "err");
  renderPipeline();
}

function onEvent(e) {
  const r = app.run;
  if (e.round !== undefined && e.round > r.round) r.round = e.round;
  switch (e.kind) {
    case "start":
      r.runId = e.run_id;
      feed("server", `run <code>${esc(e.run_id)}</code> started · ${esc(e.mode)}-agent · backend ${esc(e.backend)}`, "key");
      break;
    case "task":
      r.tasks[e.task.id] = e.task;
      renderPipeline();
      break;
    case "trace":
      onTrace(e.entry);
      break;
    case "evidence":
      r.evidence.push(e.evidence);
      noteEvidence(e.evidence);
      renderEvidence(e.evidence);
      renderGraph();
      break;
    case "hypotheses":
      r.hyps = e.hypotheses;
      renderHyps();
      renderGraph();
      break;
    case "critique":
      r.critiques.push(e.critique);
      renderCritique(e.critique);
      break;
    case "report":
      r.report = e.report;
      r.runId = e.run_id;
      const inv = e.report.investigation;
      Object.assign(r, { tools: inv.tool_calls, llm: inv.llm_calls, tokens: inv.prompt_tokens + inv.completion_tokens });
      renderStats();
      renderReport();
      $("#reportBtn").disabled = false;
      $("#reportBtn").classList.add("pulse");
      const rc = e.report.root_cause;
      feed("server", rc ? `<b>CONCLUSIVE</b> · ${esc(rc.cause_type)} in <code>${esc(rc.service)}</code> (${pct(rc.confidence)})` : "<b>INCONCLUSIVE</b> · evidence insufficient", "key");
      break;
    case "error":
      finishRun(e.message);
      break;
    case "end":
      finishRun();
      break;
  }
  renderStats();
}

function onTrace(t) {
  const r = app.run;
  const a = t.actor;
  switch (t.event) {
    case "tool_call": {
      r.tools += t.attempts || 1;
      if (!t.ok) r.failed += 1;
      if ((t.attempts || 1) > 1) r.retried += 1;
      const svc = t.args?.service;
      if (svc && svc !== "*") {
        const s = (r.svc[svc] ||= {});
        if (["query_logs", "query_metrics"].includes(t.tool)) s.queried = true;
        if (!t.ok) s.failed = true;
      }
      const args = Object.entries(t.args || {}).filter(([k]) => ["service", "level", "metric", "query"].includes(k))
        .map(([k, v]) => `${k}=${String(v).slice(0, 34)}`).join(", ");
      let tags = t.ok ? `<span class="tag ok">ok</span>` : `<span class="tag fail">${esc((t.error || "failed").split(":")[0])}</span>`;
      if ((t.attempts || 1) > 1) tags += `<span class="tag retry">${t.attempts} attempts</span>`;
      if (t.incomplete) tags += `<span class="tag part">partial</span>`;
      feed(a, `<code>${esc(t.call)}</code> ${esc(t.tool)}(${esc(args)}) ${tags}`, t.ok ? "" : "err");
      renderGraph();
      break;
    }
    case "dispatch":
      feed("orchestrator", `dispatch ${t.tasks.map((x) => `<code>${esc(x)}</code>`).join(" ")}${t.parallel > 1 ? ` <b>in parallel</b>` : ""}`);
      break;
    case "plan": feed(a, `plan from LLM: ${esc(t.rationale)}`, "key"); break;
    case "plan_fallback": feed(a, `default plan (LLM unavailable)`, "warn"); break;
    case "llm_call":
      r.llm += 1; r.tokens += (t.prompt_tokens || 0) + (t.completion_tokens || 0);
      feed(a, `LLM call <code>${esc(t.model)}</code> ${t.prompt_tokens + t.completion_tokens} tokens`);
      break;
    case "invalid_llm_output": feed(a, `invalid LLM output → re-asking: ${esc(t.error)}`, "warn"); break;
    case "agent_fallback": feed(a, `recovery → deterministic path (${esc((t.reason || "").slice(0, 70))})`, "warn"); break;
    case "findings": feed(a, `${t.count} findings → blackboard`); break;
    case "hypotheses": feed(a, `ranked ${t.ranked.length} hypotheses (${esc(t.source)})`, "key"); break;
    case "critique": feed(a, `verdict <b>${esc(t.verdict)}</b>${t.follow_ups ? ` · ${t.follow_ups} follow-up task(s)` : ""}`, "key"); break;
    case "feedback_loop": feed(a, `feedback loop → round ${t.round}: ${t.new_tasks.map((x) => `<code>${esc(x)}</code>`).join(" ")}`, "key"); break;
    case "task_failed": feed(a, `task ${esc(t.task)} failed: ${esc(t.error)}`, "err"); break;
    default: break;
  }
}

function feed(actor, html, cls = "") {
  const r = app.run;
  r.feed += 1;
  const el = document.createElement("div");
  el.className = `fe ${cls}`;
  const c = AGENTS[actor]?.color || "#8592b0";
  const t = r.started ? ((performance.now() - r.started) / 1000).toFixed(1) : "0.0";
  el.innerHTML = `<span class="ft">${t}s</span><span class="fa" style="color:${c}">${esc(AGENTS[actor]?.label || actor)}</span><span class="fm">${html}</span>`;
  const box = $("#feed");
  box.appendChild(el);
  while (box.children.length > 220) box.removeChild(box.firstChild);
  box.scrollTop = box.scrollHeight;
  $("#feedCount").textContent = `${r.feed} events`;
}

/* -------------------------------------------------------------- render */
function renderStats() {
  const r = app.run || {};
  const items = [
    ["Round", r.running || r.report ? (r.round || 0) + 1 : "–"],
    ["Tool calls", r.tools || 0], ["Failed", r.failed || 0, r.failed ? "bad" : ""], ["Retried", r.retried || 0, r.retried ? "warn" : ""],
    ["LLM calls", r.llm || 0], ["Tokens", (r.tokens || 0).toLocaleString()], ["Evidence", (r.evidence || []).length],
    ["Elapsed", `${(r.elapsed || 0).toFixed(1)}s`],
  ];
  $("#stats").innerHTML = items.map(([k, v, c]) => `<div class="stat ${c || ""}"><div class="k">${k}</div><div class="v">${v}</div></div>`).join("");
}

function agentState(name) {
  if (name === "orchestrator" && app.run && (app.run.running || app.run.report)) {
    const n = Object.keys(app.run.tasks).length;
    return { status: app.run.running ? "running" : "done", detail: `${n} tasks scheduled · round ${(app.run.round || 0) + 1}` };
  }
  const tasks = Object.values(app.run?.tasks || {}).filter((t) => t.agent === name);
  if (!tasks.length) return { status: "idle", detail: AGENTS[name].desc };
  const last = tasks[tasks.length - 1];
  const running = tasks.find((t) => t.status === "running");
  const cur = running || last;
  const n = tasks.length;
  const detail = `${tasks.map((t) => t.id).slice(-3).join(", ")}${n > 3 ? "…" : ""} · round ${cur.round + 1}`;
  return { status: running ? "running" : cur.status, detail: cur.note ? `${detail} · ${cur.note}` : detail };
}

function renderPipeline() {
  const r = app.run || {};
  const single = app.mode === "single";
  const node = (name, dim) => {
    const s = agentState(name);
    return `<div class="agent ${s.status === "running" ? "running" : ""} ${dim ? "dim" : ""}" style="--c:${AGENTS[name].color}">
      <div class="n"><span>${AGENTS[name].label}</span><span class="pill ${s.status}">${s.status}</span></div>
      <div class="d" title="${esc(s.detail)}">${esc(s.detail)}</div></div>`;
  };
  const loops = (r.critiques || []).filter((c) => c.verdict === "investigate").length;
  if (single) {
    $("#pipeline").innerHTML = `<div class="prow">${node("single_agent")}</div>
      <div class="par" style="color:var(--muted)">one ReAct loop · same tools & budgets · no critique loop</div>
      <div class="prow">${node("observability", true)}${node("dependency", true)}</div>
      <div class="prow">${node("reasoning", true)}${node("critic", true)}</div>`;
  } else {
    $("#pipeline").innerHTML = `<div class="prow">${node("orchestrator")}</div>
      <div class="par">▼ parallel ▼</div>
      <div class="prow">${node("observability")}${node("dependency")}</div>
      <div class="prow">${node("reasoning")}${node("critic")}</div>
      <div class="loop ${loops ? "on" : ""}">${loops ? `↺ critic sent work back ${loops}× (feedback loop)` : "↺ critic may send follow-up tasks back"}</div>
      <div class="prow">${node("reporting")}</div>`;
  }
  $("#roundHint").textContent = r.running ? `round ${(r.round || 0) + 1} · running` : r.report ? `finished · ${r.report.investigation.rounds} round(s)` : "idle";
}

function noteEvidence(ev) {
  const r = app.run;
  if (!ev.service) return;
  const s = (r.svc[ev.service] ||= {});
  if (["metric_anomaly", "error_logs"].includes(ev.signal) && ev.kind === "fact") s.anomalous = true;
  if (["deployment", "config_change"].includes(ev.signal)) s.changed = true;
}

function layout(deps) {
  const names = Object.keys(deps);
  const depth = {};
  const visit = (n, d) => { if ((depth[n] ?? -1) >= d) return; depth[n] = d; (deps[n] || []).forEach((c) => visit(c, d + 1)); };
  const callers = new Set(names.flatMap((n) => deps[n]));
  names.filter((n) => !callers.has(n)).forEach((n) => visit(n, 0));
  const layers = {};
  names.forEach((n) => (layers[depth[n] ?? 0] ||= []).push(n));
  const L = Object.keys(layers).length;
  const pos = {};
  const W = 760, H = 300, nw = 132, nh = 26;
  Object.entries(layers).forEach(([d, ns]) => {
    ns.sort();
    const x = 14 + (+d) * ((W - nw - 28) / Math.max(1, L - 1));
    ns.forEach((n, i) => { pos[n] = { x, y: 20 + (i + 0.5) * ((H - 30) / ns.length) - nh / 2 }; });
  });
  return { pos, nw, nh };
}

function renderGraph() {
  if (!app.incident) return;
  const deps = app.incident.dependencies;
  const { pos, nw, nh } = layout(deps);
  const r = app.run || { svc: {}, hyps: [] };
  const top = (r.hyps || [])[0];
  const suspect = top && top.confidence >= 0.3 ? top.suspect_service : null;
  const rep = app.incident.incident.reported_service;
  const cls = (n) => {
    const s = r.svc?.[n] || {};
    return ["node", s.queried && "queried", s.anomalous && "anomalous", s.failed && "failed", n === suspect && "suspect"].filter(Boolean).join(" ");
  };
  let edges = "";
  Object.entries(deps).forEach(([a, cs]) => cs.forEach((b) => {
    const p = pos[a], q = pos[b];
    const hot = r.svc?.[a]?.anomalous && r.svc?.[b]?.anomalous;
    const x1 = p.x + nw, y1 = p.y + nh / 2, x2 = q.x, y2 = q.y + nh / 2, mx = (x1 + x2) / 2;
    edges += `<path class="edge ${hot ? "hot" : ""}" d="M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2 - 3},${y2}" marker-end="url(#arr)"/>`;
  }));
  let nodes = "";
  Object.keys(deps).forEach((n) => {
    const p = pos[n], s = r.svc?.[n] || {};
    nodes += `<g class="${cls(n)}" transform="translate(${p.x},${p.y})">
      <rect width="${nw}" height="${nh}"></rect>
      <text x="9" y="17">${esc(n)}</text>
      ${s.changed ? `<circle class="badge" cx="${nw - 9}" cy="9" r="5"></circle>` : ""}
      ${n === rep ? `<text class="reported" x="0" y="-4">▲ reported</text>` : ""}
      ${n === suspect ? `<text class="suspect-label" x="${n === rep ? 70 : 0}" y="${nh + 12}">◆ suspect ${pct(top.confidence)}</text>` : ""}
    </g>`;
  });
  $("#graph").innerHTML = `<defs><marker id="arr" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto">
    <path d="M0,0 L8,4 L0,8 z" fill="#3a4a70"/></marker></defs>${edges}${nodes}`;
}

function refs(list) { return (list || []).map((x) => `<span class="ref">${esc(x)}</span>`).join(""); }

function renderEvidence(ev) {
  const box = $("#evidence");
  if (box.querySelector(".empty")) box.innerHTML = "";
  const el = document.createElement("div");
  el.className = "evi";
  el.innerHTML = `<span class="id">${esc(ev.id)}</span><span class="kind ${esc(ev.kind)}">${esc(ev.kind)}</span>
    <span class="c">${esc(ev.claim)}${refs(ev.refs)}</span>`;
  box.appendChild(el);
  box.scrollTop = box.scrollHeight;
  $("#evCount").textContent = `${app.run.evidence.length} items · ${app.run.evidence.filter((e) => e.kind === "fact").length} facts`;
}

function renderHyps() {
  const hs = app.run.hyps;
  $("#hypHint").textContent = hs.length ? `round ${app.run.round + 1}` : "";
  if (!hs.length) { $("#hyps").innerHTML = `<div class="empty">No hypotheses.</div>`; return; }
  $("#hyps").innerHTML = hs.map((h, i) => `
    <div class="hyp">
      <div class="hrow"><span class="rank">#${i + 1}</span><span class="svc">${esc(h.suspect_service || "no specific component")}</span>
        <span class="cause">${esc(h.cause_type.replace(/_/g, " "))}</span><span class="conf">${pct(h.confidence)}</span></div>
      <div class="bar"><i style="width:0%" data-w="${Math.round(h.confidence * 100)}%"></i></div>
      <div class="ev"><b class="s">${h.supporting.length}</b> supporting · <b class="c">${h.contradicting.length}</b> contradicting${h.assumptions.length ? ` · ${h.assumptions.length} assumption(s)` : ""}</div>
    </div>`).join("");
  requestAnimationFrame(() => document.querySelectorAll("#hyps .bar i").forEach((b) => (b.style.width = b.dataset.w)));
}

function renderCritique(c) {
  const box = $("#critic");
  if (box.querySelector(".empty")) box.innerHTML = "";
  const el = document.createElement("div");
  el.className = "crit";
  el.innerHTML = `<div class="h">Round ${c.round + 1}<span class="verdict ${esc(c.verdict)}">${esc(c.verdict)}</span><span class="hint">${esc(c.source)}</span></div>
    <ul>${(c.issues || []).slice(0, 4).map((i) => `<li>${esc(i)}</li>`).join("") || "<li>no blocking issues</li>"}
    ${(c.follow_ups || []).map((f) => `<li class="fu">→ ${esc(f.agent)}: ${esc(f.goal)}</li>`).join("")}</ul>`;
  box.appendChild(el);
  box.scrollTop = box.scrollHeight;
}

/* ---------------------------------------------------------------- report */
function openDrawer(open) {
  $("#drawer").classList.toggle("open", open);
  $("#scrim").classList.toggle("open", open);
}

function evList(list) {
  return `<ul>${list.map((e) => `<li><span class="kind ${esc(e.kind)}">${esc(e.kind)}</span><span>${esc(e.claim)}${refs(e.refs)}</span></li>`).join("")}</ul>`;
}

function renderReport() {
  const rep = app.run.report;
  const inv = rep.investigation;
  const rc = rep.root_cause;
  $("#drawerTitle").textContent = `Investigation report · ${rep.incident_id} · ${rep.system}`;
  $("#report").innerHTML = `
    <div class="outcome ${esc(rep.outcome)}">
      <div><div class="lbl">Outcome</div><div class="big">${rep.outcome === "conclusive" ? "Conclusive" : "Inconclusive"}</div></div>
      ${rc ? `<div><div class="lbl">Root cause</div><div class="big">${esc(rc.cause_type.replace(/_/g, " "))} · ${esc(rc.service)}</div></div>
               <div><div class="lbl">Confidence</div><div class="big">${pct(rc.confidence)}</div></div>` : `<div class="muted">No hypothesis reached the confidence threshold.</div>`}
    </div>
    <p>${esc(rep.summary)}</p>
    <div class="kv">
      <div>rounds<b>${inv.rounds}</b></div><div>tool calls<b>${inv.tool_calls} <small class="muted">(${inv.failed_tool_calls} failed, ${inv.retried_tool_calls} retried)</small></b></div>
      <div>LLM calls / tokens<b>${inv.llm_calls} / ${(inv.prompt_tokens + inv.completion_tokens).toLocaleString()}</b></div><div>latency<b>${inv.latency_s}s</b></div>
    </div>
    <h3>Ranked hypotheses</h3>
    ${rep.hypotheses.map((h) => `<div class="rh">
      <div class="hrow">#${h.rank} ${esc(h.suspect_service || "no specific component")} <span class="cause">${esc(h.cause_type.replace(/_/g, " "))}</span><span style="margin-left:auto">${pct(h.confidence)}</span></div>
      <div class="stmt">${esc(h.statement)}</div>
      ${h.supporting.length ? `<div class="sub s">SUPPORTING</div>${evList(h.supporting)}` : ""}
      ${h.contradicting.length ? `<div class="sub c">CONTRADICTING</div>${evList(h.contradicting)}` : ""}
      ${h.assumptions.length ? `<div class="sub a">ASSUMPTIONS</div><ul>${h.assumptions.map((a) => `<li>${esc(a)}</li>`).join("")}</ul>` : ""}
    </div>`).join("")}
    <h3>Recommended actions</h3>
    ${rep.actions.map((a) => `<div class="action"><span class="prio ${esc(a.priority)}">${esc(a.priority || "P1")}</span><span><b>${esc(a.action)}</b> <span class="muted">— ${esc(a.rationale || "")}</span></span></div>`).join("")}
    <h3>Facts (directly observed)</h3>
    <ul class="facts">${rep.facts.map((f) => `<li>${esc(f)}</li>`).join("") || "<li class='muted'>none</li>"}</ul>
    <h3>Inferences &amp; assumptions</h3>
    <ul class="facts">${[...rep.inferences, ...rep.assumptions].map((f) => `<li>${esc(f)}</li>`).join("") || "<li class='muted'>none</li>"}</ul>
    <h3>Critic rounds</h3>
    ${inv.critiques.map((c) => `<div class="action"><span class="verdict ${esc(c.verdict)}">${esc(c.verdict)}</span><span>round ${c.round + 1}: ${esc(c.issues.slice(0, 3).join("; ") || "no blocking issues")}</span></div>`).join("") || "<p class='muted'>Single-agent mode has no critic.</p>"}
    <h3>Evaluation</h3>
    <button class="ghost" id="scoreBtn">Score against ground truth</button>
    <div id="scoreBox"></div>`;
  $("#scoreBtn").addEventListener("click", scoreRun);
}

async function scoreRun() {
  const d = await api(`/api/runs/${app.run.runId}/score`);
  const s = d.score;
  $("#scoreBox").innerHTML = `<div class="score ${s.correct ? "right" : "wrong"}">
    <div class="verdict-big">${s.correct ? "✓ Correct" : "✗ Incorrect"}</div>
    <div class="kv" style="margin-top:8px">
      <div>predicted<b class="mono">${esc(s.predicted)}</b></div><div>expected<b class="mono">${esc(s.expected)}</b></div>
      <div>evidence grounded<b>${s.evidence_grounded_rate ?? "–"}</b></div><div>key-evidence recall<b>${s.key_evidence_recall ?? "–"}</b></div>
    </div>
    <p class="muted" style="margin-top:8px">Trap in this incident: ${esc(d.ground_truth.traps)}</p></div>`;
  $("#scoreBox").scrollIntoView({ behavior: "smooth", block: "end" });
}

/* ------------------------------------------------------------- evaluation */
async function loadEvalSets() {
  const sets = await api("/api/eval");
  $("#evalSel").innerHTML = sets.map((s) => `<option>${esc(s)}</option>`).join("");
  if (sets.length) loadEval(sets[0]);
}

async function loadEval(label) {
  const d = await api(`/api/eval/${encodeURIComponent(label)}`);
  const m = d.summary.multi, s = d.summary.single;
  const card = (k, mv, sv, fmt = (x) => x) => `<div class="ecard"><div class="k">${k}</div><div class="vs">
    <div class="m">${fmt(mv)}<span class="lbl">multi-agent</span></div><div class="s">${fmt(sv)}<span class="lbl">single-agent</span></div></div></div>`;
  $("#evalCards").innerHTML =
    card("Root-cause accuracy", `${Math.round(m.accuracy * m.n)}/${m.n}`, `${Math.round(s.accuracy * s.n)}/${s.n}`) +
    card("Key-evidence recall", m.key_evidence_recall, s.key_evidence_recall, (x) => (x ?? 0).toFixed(2)) +
    card("Confident-wrong answers", m.confident_wrong, s.confident_wrong) +
    card("Avg tool calls", m.avg_tool_calls, s.avg_tool_calls, (x) => (+x).toFixed(1));
  const metrics = [["accuracy", "accuracy"], ["service_accuracy", "service"], ["cause_type_accuracy", "cause type"], ["top3_recall", "top-3 recall"], ["key_evidence_recall", "key evidence"], ["evidence_grounded_rate", "grounded"]];
  const W = 760, H = 330, base = 280, gw = (W - 60) / metrics.length;
  let svg = `<line x1="40" y1="${base}" x2="${W - 10}" y2="${base}" stroke="#24314f"/>`;
  [0, 0.5, 1].forEach((t) => { const y = base - t * 240; svg += `<line x1="40" x2="${W - 10}" y1="${y}" y2="${y}" stroke="#18223a"/><text x="8" y="${y + 4}">${t * 100}%</text>`; });
  metrics.forEach(([k, lbl], i) => {
    const x = 52 + i * gw;
    [[m[k], "#f97316"], [s[k], "#38bdf8"]].forEach(([v, c], j) => {
      const h = (v || 0) * 240, bx = x + j * (gw / 2 - 6);
      svg += `<rect x="${bx}" y="${base - h}" width="${gw / 2 - 12}" height="${h}" rx="4" fill="${c}"/><text class="val" x="${bx + (gw / 2 - 12) / 2}" y="${base - h - 6}" text-anchor="middle">${(v || 0).toFixed(2)}</text>`;
    });
    svg += `<text x="${x + gw / 2 - 12}" y="${base + 20}" text-anchor="middle">${lbl}</text>`;
  });
  svg += `<rect x="${W - 230}" y="6" width="12" height="12" fill="#f97316" rx="3"/><text x="${W - 212}" y="16">multi-agent</text><rect x="${W - 120}" y="6" width="12" height="12" fill="#38bdf8" rx="3"/><text x="${W - 102}" y="16">single-agent</text>`;
  $("#evalChart").innerHTML = svg;
  const costRow = (k, lbl, fmt) => { const mx = Math.max(m[k] || 0, s[k] || 0, 1e-9);
    return `<div class="crow"><div class="k">${lbl}</div>
      <div class="cbar"><span class="who">multi</span><i style="width:${(m[k] / mx) * 70}%;background:#f97316"></i>${fmt(m[k])}</div>
      <div class="cbar"><span class="who">single</span><i style="width:${(s[k] / mx) * 70}%;background:#38bdf8"></i>${fmt(s[k])}</div></div>`; };
  $("#evalCost").innerHTML = costRow("avg_tool_calls", "Tool calls", (x) => (+x).toFixed(1)) + costRow("avg_llm_calls", "LLM calls", (x) => (+x || 0).toFixed(1)) +
    costRow("avg_tokens", "Tokens", (x) => Math.round(x || 0).toLocaleString()) + costRow("avg_latency_s", "Latency (s)", (x) => (+x).toFixed(2)) +
    `<div class="muted" style="font-size:12px">backend: ${esc(d.meta.backend)}${d.meta.model ? " · " + esc(d.meta.model) : " (deterministic agents, no LLM tokens)"}</div>`;
  const byInc = {};
  d.rows.forEach((r) => ((byInc[r.incident] ||= {})[r.system] = r));
  $("#evalTable").innerHTML = `<table class="it"><tr><th>incident</th><th>expected</th><th>multi-agent</th><th></th><th>single-agent</th><th></th><th>tools (m / s)</th></tr>
    ${Object.entries(byInc).map(([i, r]) => `<tr><td class="mono">${esc(i)}</td><td class="mono">${esc(r.multi.expected)}</td>
      <td class="mono">${esc(r.multi.predicted)}</td><td class="${r.multi.correct ? "ok" : "no"}">${r.multi.correct ? "✓" : "✗"}</td>
      <td class="mono">${esc(r.single.predicted)}</td><td class="${r.single.correct ? "ok" : "no"}">${r.single.correct ? "✓" : "✗"}</td>
      <td>${r.multi.tool_calls} / ${r.single.tool_calls}</td></tr>`).join("")}</table>`;
}

/* -------------------------------------------------------------- API view */
const ENDPOINTS = [
  ["/api/health", "service status and LLM backend availability"],
  ["/api/incidents", "incident list (public fields, no ground truth)"],
  ["/api/incidents/INC-002", "incident + dependency graph + data volumes"],
  ["/api/investigate?incident=INC-002&mode=multi&backend=offline", "SSE stream of a live investigation", true],
  ["/api/runs", "recent runs"],
  ["/api/eval", "available evaluation result sets"],
  ["/api/eval/offline", "multi vs single evaluation results"],
];

function buildEndpoints() {
  $("#endpoints").innerHTML = ENDPOINTS.map(([p, d, sse], i) => `<div class="ep"><span class="verb">GET</span><div><div class="path">${esc(p)}</div><div class="desc">${esc(d)}</div></div>
    <button class="ghost small" data-i="${i}">${sse ? "stream" : "call"}</button></div>`).join("");
  document.querySelectorAll(".ep button").forEach((b) => b.addEventListener("click", () => callEndpoint(ENDPOINTS[+b.dataset.i])));
}

async function callEndpoint([path, , sse]) {
  $("#apiOutTitle").textContent = `GET ${path}`;
  const out = $("#apiOut");
  if (sse) {
    out.textContent = "";
    $("#apiOutMeta").textContent = "text/event-stream";
    const es = new EventSource(path);
    let n = 0;
    es.onmessage = (m) => {
      const e = JSON.parse(m.data);
      n += 1;
      const brief = e.kind === "report" ? { kind: "report", outcome: e.report.outcome, root_cause: e.report.root_cause } :
        e.kind === "trace" ? { kind: "trace", ...e.entry } : e.kind === "evidence" ? { kind: "evidence", id: e.evidence.id, claim: e.evidence.claim } : e;
      out.textContent += `data: ${JSON.stringify(brief)}\n`;
      out.scrollTop = out.scrollHeight;
      if (e.kind === "end") { es.close(); $("#apiOutMeta").textContent = `text/event-stream · ${n} events`; }
    };
    es.onerror = () => es.close();
    return;
  }
  const t0 = performance.now();
  const r = await fetch(path);
  const text = await r.text();
  $("#apiOutMeta").textContent = `${r.status} · ${r.headers.get("content-type")} · ${(performance.now() - t0).toFixed(0)} ms · ${text.length.toLocaleString()} bytes`;
  let pretty = text;
  try { pretty = JSON.stringify(JSON.parse(text), null, 2); } catch (_) { /* keep raw */ }
  out.textContent = pretty.length > 12000 ? pretty.slice(0, 12000) + "\n… (truncated in UI)" : pretty;
  out.scrollTop = 0;
}

/* ---------------------------------------------------------- backend log */
function connectConsole() {
  const box = $("#console");
  const es = new EventSource("/api/logs");
  es.onmessage = (m) => {
    const l = JSON.parse(m.data);
    const el = document.createElement("div");
    el.className = "cl";
    el.innerHTML = `<span class="ts">${esc(l.ts)}</span>  <span class="lv ${esc(l.level)}">${esc(l.level)}</span><span class="src">${esc(l.source)}</span>${esc(l.msg)}`;
    box.appendChild(el);
    while (box.children.length > 400) box.removeChild(box.firstChild);
    box.scrollTop = box.scrollHeight;
  };
}

boot();
