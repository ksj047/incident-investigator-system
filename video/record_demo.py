"""Record the full-stack demo: real backend + real frontend, driven in Chromium, narrated.

  pip install playwright edge-tts      (Chromium must be available to Playwright)
  python3 video/record_demo.py

Steps: start `server.app` -> capture real terminal output (server start, curl, SSE, pytest) ->
synthesize narration per scene -> drive the UI in Chromium with Playwright's screen recorder ->
lay each narration clip at the moment its scene started -> mux to video/fullstack_demo.mp4.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import ssl
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "video" / "build_demo"
OUT = ROOT / "video" / "fullstack_demo.mp4"
PORT = int(os.getenv("DEMO_PORT", "8800"))
BASE = f"http://127.0.0.1:{PORT}"
VOICE = os.getenv("TTS_VOICE", "en-US-AndrewNeural")

# ---------------------------------------------------------------------------- narration
SCENES = {
    "terminal": """This recording walks through the full stack I built around the investigation engine: a Python backend that serves the agents over HTTP, and a browser frontend that shows an investigation as it happens.
We start in the terminal. The backend is a single Python server built only on the standard library, with no web framework. On startup it reports which language model backends are available. There is no OpenRouter key here, so investigations use the deterministic agent paths.
A health check returns JSON. The investigate endpoint streams server-sent events: one per task change, tool call, piece of evidence, hypothesis update and critique, and finally the report. The test suite now has twenty-six tests, including five that start the server and exercise the API end to end.""",
    "overview": """This is the frontend: plain HTML, CSS and JavaScript, served by the same backend, with no build step.
On the left are the twelve incidents. The top bar shows the selected incident and the run controls: multi-agent or single-agent, the LLM backend, and a playback speed. Offline runs finish in under a second, so demo speed replays the server's stream at a watchable pace.
Below are live counters, and six panels: the agents, the service dependency graph, the live activity feed, the critic, the competing hypotheses, and the evidence board. At the bottom is the backend console, a live stream of the server's own log.""",
    "api": """The Backend API tab calls the server directly. Health reports status and which backends are available. The incident list exposes only public fields; ground truth is never served to the investigators or to this list. An incident's detail includes its dependency graph and data volumes.
The investigate endpoint is a server-sent event stream, and here are the raw events arriving: the start, tasks, tool calls, evidence, and the final report. Each request also shows up in the backend console below.""",
    "run_multi": """Now a real investigation. Incident two: order placement timeouts, where a frontend deploy went out minutes before the report. I run the multi-agent investigator.
The orchestrator dispatches the observability and dependency agents in parallel, and you can see both running at once. Each tool call appears in the activity feed with its status, and the backend console logs the same calls on the server side.
The dependency graph lights up as services are examined. Blue means examined, amber means anomalies or errors, and the purple dot marks a recent change. Notice how the observability agent follows the trail: from the frontend to the API gateway, whose logs name the orders service, and from there to the orders database. Evidence lands on the board as facts with record ids. Then the reasoning agent ranks competing hypotheses, and the critic reviews them.""",
    "report": """The result: a configuration change on the orders database, at eighty-two percent confidence, accepted by the critic in the first round.
The report drawer shows the outcome and the ranked hypotheses, with supporting and contradicting evidence, each citing record ids. The frontend deploy is listed as contradicting evidence, because it happened after the frontend's own errors began. Below are the recommended actions, the facts kept separate from inferences and assumptions, and the critic's verdicts.
Scoring against ground truth, which only the evaluation endpoint reads, confirms the answer is correct.""",
    "single": """For comparison, here is the same incident with the single-agent baseline. It has the same tools and budgets, but makes one pass, with no specialists and no critic.
It examines the reported service and the change history, and stops at the loud symptom: it blames the frontend, with an unknown mechanism. Scoring confirms it is wrong. This is the failure mode the multi-agent design is built to avoid.""",
    "loop": """Incident ten shows the feedback loop. User-service is overloaded, and it had its own deploy that morning.
In round one, the reasoning agent leans toward a configuration change on the API gateway. But the critic objects: the gateway's downstream services were never examined, so the gateway might itself be a victim. It sends follow-up tasks back to the observability agent.
Watch the round counter move to two while those services are checked. With that evidence, the critic accepts. The gateway's retry policy was changed from one attempt to five, with no backoff, two minutes before user-service fell over. It's a retry storm, and user-service is the victim.""",
    "failures": """Incident seven is about failing tools. Log queries for the search service, the cache and the product database always time out.
In the feed, failed calls appear in red with their attempt counts. The executor retried each one with backoff before giving up, and the graph marks those services with dashed red borders.
The investigation keeps going. The observability agent widens its search and re-queries the partial metrics, and the dependency agent finds that the cache TTL was cut from an hour to five seconds. The conclusion rests on metrics and change history, and the critic records that log data was unavailable.""",
    "inconclusive": """Incident nine is deliberately vague: intermittent slowness, no changes, and incomplete metrics.
The system does not invent a cause. Its only hypothesis names no component, at ten percent. The critic rules the evidence insufficient, and the report says inconclusive, recommending better telemetry instead of a guess. Scoring confirms that is the expected answer.""",
    "evaluation": """The Evaluation tab loads the evaluation results from the backend. On the offline result set, the multi-agent system solved twelve out of twelve and the single agent seven. Key-evidence recall is point nine two versus point four two, and neither system gave a confidently wrong answer. The price is about three times more tool calls.
The per-incident table shows exactly where the single agent failed: loud victims, and culprits it never examined. These numbers come from the deterministic agents. With an OpenRouter key, the same screen shows the live LLM comparison, including LLM calls and tokens.""",
    "console": """Finally, the backend console. Every HTTP request, every agent tool call and recovery, and every finished run is logged by the server and streamed here over a second event stream, so you can watch the frontend and backend side by side.
Everything shown is in the repository: the server in the server folder, the frontend in the web folder, and the API tests next to the original suite. Start it with python three dash m server dot app, and open localhost port eight thousand. Thanks for watching.""",
}

CURSOR_JS = """
(() => {
  const install = () => {
    if (document.getElementById('__cursor')) return;
    const c = document.createElement('div');
    c.id = '__cursor';
    c.style.cssText = 'position:fixed;left:0;top:0;width:22px;height:22px;margin:-11px 0 0 -11px;border-radius:50%;' +
      'background:rgba(255,255,255,.22);border:2px solid #fff;box-shadow:0 0 0 2px rgba(0,0,0,.35);z-index:2147483647;' +
      'pointer-events:none;transition:transform .12s;';
    document.documentElement.appendChild(c);
    document.addEventListener('mousemove', e => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }, true);
    document.addEventListener('mousedown', () => { c.style.transform = 'scale(.7)'; c.style.background = 'rgba(249,115,22,.6)'; }, true);
    document.addEventListener('mouseup', () => { c.style.transform = ''; c.style.background = 'rgba(255,255,255,.22)'; }, true);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install); else install();
})();
"""


# ---------------------------------------------------------------------------- helpers
def tts_all() -> dict[str, tuple[Path, float]]:
    import edge_tts
    import edge_tts.communicate as comm
    ca = os.getenv("SSL_CERT_FILE") or ("/root/.ccr/ca-bundle.crt" if Path("/root/.ccr/ca-bundle.crt").exists() else None)
    if ca:
        comm._SSL_CTX = ssl.create_default_context(cafile=ca)
    out = {}
    for name, text in SCENES.items():
        text = " ".join(text.split())
        h = hashlib.sha1((VOICE + text).encode()).hexdigest()[:10]
        mp3 = BUILD / f"{name}-{h}.mp3"
        if not mp3.exists():
            for attempt in range(4):
                try:
                    asyncio.run(edge_tts.Communicate(text, VOICE).save(str(mp3)))
                    break
                except Exception:
                    if attempt == 3:
                        raise
                    time.sleep(2 ** attempt)
        out[name] = (mp3, probe(mp3))
        print(f"tts {name:13s} {out[name][1]:5.1f}s", flush=True)
    return out


def probe(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def wait_health(timeout=20):
    t = time.time()
    while time.time() - t < timeout:
        try:
            with urllib.request.urlopen(f"{BASE}/api/health", timeout=2) as r:
                return json.loads(r.read())
        except Exception:
            time.sleep(0.2)
    raise RuntimeError("server did not start")


def capture_terminal(server_first_line: str) -> list[tuple[str, list[str]]]:
    """Run the real commands and keep their real output for the terminal scene."""
    health = json.dumps(wait_health(), indent=2).splitlines()
    sse = []
    with urllib.request.urlopen(f"{BASE}/api/investigate?incident=INC-002&mode=multi&backend=offline", timeout=60) as r:
        for line in r:
            if line.startswith(b"data: "):
                sse.append(line.decode().strip())
    shown = [s[:150] + ("…" if len(s) > 150 else "") for s in sse[:9]] + [f"… ({len(sse)} events in total, last: {sse[-1][:60]})"]
    tests = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=ROOT, capture_output=True, text=True).stdout.strip().splitlines()
    return [
        (f"python3 -m server.app --port {PORT}", [server_first_line]),
        (f"curl -s {BASE}/api/health", health),
        (f'curl -sN "{BASE}/api/investigate?incident=INC-002&mode=multi"', shown),
        ("python3 -m pytest -q", tests[-3:]),
    ]


def terminal_html(blocks) -> str:
    data = json.dumps([[cmd, out] for cmd, out in blocks])
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
body{{margin:0;background:#0a0f1d;font-family:"JetBrains Mono",monospace;color:#e6ebf5;height:100vh;display:flex;align-items:center;justify-content:center}}
.win{{width:1760px;height:960px;background:#060a14;border:1px solid #1e2a45;border-radius:14px;overflow:hidden;box-shadow:0 30px 80px rgba(0,0,0,.5)}}
.bar{{height:40px;background:#111a2e;display:flex;align-items:center;gap:8px;padding:0 16px;font-family:Inter,sans-serif;font-size:14px;color:#8592b0}}
.bar i{{width:12px;height:12px;border-radius:50%;display:inline-block}}
#t{{padding:18px 24px;font-size:17px;line-height:1.5;white-space:pre-wrap;height:880px;overflow:hidden}}
.p{{color:#34d399}} .c{{color:#fff}} .o{{color:#aab5cc}} .cur{{background:#e6ebf5;color:#060a14}}
</style></head><body><div class="win"><div class="bar"><i style="background:#f87171"></i><i style="background:#fbbf24"></i><i style="background:#34d399"></i>
<span style="margin-left:10px">incident-investigator — backend</span></div><div id="t"></div></div>
<script>
const B={data};const t=document.getElementById('t');
const esc=s=>s.replace(/[&<>]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;'}}[c]));
async function play(i){{const [cmd,out]=B[i];
 const line=document.createElement('div');line.innerHTML='<span class="p">$ </span><span class="c"></span><span class="cur"> </span>';t.appendChild(line);
 const c=line.querySelector('.c');for(const ch of cmd){{c.textContent+=ch;await new Promise(r=>setTimeout(r,26));}}
 line.querySelector('.cur').remove();await new Promise(r=>setTimeout(r,350));
 for(const o of out){{const d=document.createElement('div');d.className='o';d.innerHTML=esc(o);t.appendChild(d);t.scrollTop=t.scrollHeight;await new Promise(r=>setTimeout(r,70));}}
 t.appendChild(document.createElement('br'));t.scrollTop=t.scrollHeight;}}
</script></body></html>"""


# ---------------------------------------------------------------------------- recording
class Screencast:
    """Chrome DevTools screencast -> ffmpeg, timestamped by wall clock.

    Each unique frame is piped to ffmpeg once as it arrives; ffmpeg stamps it with the arrival time
    (-use_wallclock_as_timestamps) and fills gaps itself at a constant frame rate. The video timeline
    therefore matches wall-clock time, which keeps the narration in sync (Playwright's built-in recorder
    drifts under load), and the browser is never blocked writing duplicate frames.
    """

    def __init__(self, ctx, page, out: Path, fps: int = 25):
        import base64
        self.b64 = base64.b64decode
        self.out = out
        self.proc = subprocess.Popen(["nice", "-n", "10", "ffmpeg", "-y", "-loglevel", "error", "-use_wallclock_as_timestamps", "1",
                                      "-f", "image2pipe", "-c:v", "mjpeg", "-i", "-", "-fps_mode", "cfr", "-r", str(fps),
                                      "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p", str(out)],
                                     stdin=subprocess.PIPE)
        self.cdp = ctx.new_cdp_session(page)
        self.cdp.on("Page.screencastFrame", self._on_frame)
        self.t0 = None
        self.last = None

    def start(self) -> float:
        self.cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 85, "maxWidth": 1920, "maxHeight": 1080})
        deadline = time.time() + 5
        while self.last is None and time.time() < deadline:  # t0 = arrival of the first frame = video time 0
            self.cdp.send("Runtime.evaluate", {"expression": "1"})
            time.sleep(0.02)
        self.t0 = self.t0 or time.time()
        return self.t0

    def _on_frame(self, params) -> None:
        data = self.b64(params["data"])
        if self.last is None:
            self.t0 = time.time()
        self.last = data
        self.proc.stdin.write(data)
        try:
            self.cdp.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]})
        except Exception:
            pass

    def stop(self) -> None:
        self.cdp.send("Page.stopScreencast")
        if self.last is not None:
            self.proc.stdin.write(self.last)  # stamped "now": holds the final frame to the end
        self.proc.stdin.close()
        self.proc.wait()


def record(audio: dict[str, tuple[Path, float]], blocks) -> tuple[Path, dict[str, float]]:
    offsets: dict[str, float] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--force-device-scale-factor=1"])
        ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
        ctx.add_init_script(CURSOR_JS)
        page = ctx.new_page()
        cast = Screencast(ctx, page, BUILD / "screen.mp4")
        page.set_content("<body style='background:#0a0f1d'></body>")
        t0 = cast.start()
        page.mouse.move(960, 540)

        def wait(ms):
            page.wait_for_timeout(ms)

        def move(sel, steps=14):
            box = page.locator(sel).first.bounding_box()
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=steps)

        def click(sel, pause=280):
            # A real mouse press at the element's centre: no actionability waits that can stall a recording.
            t = time.time()
            move(sel)
            wait(pause)
            page.mouse.down()
            page.mouse.up()
            wait(200)
            if time.time() - t > 3:
                print(f"  slow click {sel}: {time.time() - t:.1f}s", flush=True)

        def set_pace(v):
            page.eval_on_selector("#paceSel", "(el, v) => { el.value = v; }", v)

        def scroll(sel, dy, smooth=True):
            page.locator(sel).first.evaluate(f"el => el.scrollBy({{top: {dy}, behavior: '{'smooth' if smooth else 'auto'}'}})")

        def run_done(timeout=180000):
            page.wait_for_selector("#reportBtn:not([disabled])", timeout=timeout)
            page.wait_for_function("() => !document.querySelector('#runBtn').classList.contains('running')", timeout=timeout)

        def scene(name, actions):
            start = time.time() - t0
            offsets[name] = start
            print(f"scene {name:13s} at {start:6.1f}s  (wall {time.strftime('%H:%M:%S')})", flush=True)
            actions()
            print(f"  actions took {time.time() - t0 - start:5.1f}s of {audio[name][1]:4.1f}s narration", flush=True)
            remaining = audio[name][1] + 0.9 - (time.time() - t0 - start)
            if remaining > 0:
                wait(remaining * 1000)

        # 1 terminal (real captured output)
        def s_terminal():
            page.set_content(terminal_html(blocks))
            wait(600)
            for i in range(len(blocks)):
                page.evaluate(f"play({i})")
                wait(int(audio["terminal"][1] * 1000 / (len(blocks) + 0.6)))
        scene("terminal", s_terminal)

        # 2 UI overview
        def s_overview():
            page.goto(f"{BASE}/?incident=INC-002")
            wait(1500)
            for sel in ["#incidentList", "#modeSeg", "#backendSel", "#paceSel", "#stats", "#pipelineCard", "#graphCard",
                        "#feedCard", "#criticCard", "#hypCard", "#evidenceCard", "#console"]:
                move(sel, steps=18)
                wait(1500)
        scene("overview", s_overview)

        # 3 backend API tab
        def s_api():
            click("#tabs button[data-view=api]")
            for i, w in [(0, 3200), (1, 3500), (2, 4200)]:
                click(f".ep button[data-i='{i}']")
                wait(w)
            click(".ep button[data-i='3']")
            wait(6000)
            move("#console")
        scene("api", s_api)

        # 4 multi-agent run on INC-002
        def s_run_multi():
            click("#tabs button[data-view=investigate]")
            set_pace("300")
            move("#paceSel")
            wait(600)
            click("#runBtn")
            wait(3500)
            move("#pipelineCard")
            wait(4000)
            move("#feedCard")
            wait(4000)
            move("#graphCard")
            run_done()
            wait(1500)
            move("#hypCard")
            wait(2500)
            move("#evidenceCard")
        scene("run_multi", s_run_multi)

        # 5 report drawer + score
        def s_report():
            move("#hypCard")
            wait(4000)
            click("#reportBtn")
            wait(5000)
            for _ in range(4):
                scroll("#report", 330)
                wait(3300)
            scroll("#report", 4000)
            wait(1200)
            click("#scoreBtn")
            wait(2500)
        scene("report", s_report)

        # 6 single-agent baseline
        def s_single():
            click("#drawerClose")
            click("#modeSeg button[data-mode=single]")
            set_pace("140")
            click("#runBtn")
            run_done()
            wait(2500)
            move("#hypCard")
            wait(3000)
            click("#reportBtn")
            wait(2500)
            scroll("#report", 5000)
            wait(1200)
            click("#scoreBtn")
            wait(2000)
        scene("single", s_single)

        # 7 feedback loop on INC-010
        def s_loop():
            click("#drawerClose")
            click("#modeSeg button[data-mode=multi]")
            click(".inc-item[data-id='INC-010']")
            wait(1200)
            set_pace("300")
            click("#runBtn")
            wait(5000)
            move("#criticCard")
            page.wait_for_selector(".verdict.investigate", timeout=120000)
            wait(3000)
            move("#stats")
            wait(2500)
            move("#pipelineCard")
            run_done()
            wait(1500)
            move("#criticCard")
            scroll("#critic", 600)
            wait(2500)
            move("#hypCard")
        scene("loop", s_loop)

        # 8 tool failures on INC-007
        def s_failures():
            click(".inc-item[data-id='INC-007']")
            wait(1000)
            set_pace("140")
            click("#runBtn")
            wait(3000)
            move("#feedCard")
            wait(3500)
            move("#graphCard")
            run_done()
            wait(1500)
            move("#stats")
            wait(2500)
            move("#criticCard")
            wait(2500)
            move("#hypCard")
        scene("failures", s_failures)

        # 9 inconclusive INC-009
        def s_inconclusive():
            click(".inc-item[data-id='INC-009']")
            wait(800)
            set_pace("60")
            click("#runBtn")
            run_done()
            wait(1500)
            move("#hypCard")
            wait(2500)
            move("#criticCard")
            wait(2000)
            click("#reportBtn")
            wait(3500)
            scroll("#report", 5000)
            wait(1200)
            click("#scoreBtn")
            wait(2000)
        scene("inconclusive", s_inconclusive)

        # 10 evaluation dashboard
        def s_eval():
            click("#drawerClose")
            click("#tabs button[data-view=evaluation]")
            wait(2500)
            move("#evalCards")
            wait(4000)
            move("#evalChart")
            wait(5000)
            scroll("#view-evaluation", 700)
            wait(2000)
            move("#evalTable")
            wait(6000)
            scroll("#view-evaluation", -700)
        scene("evaluation", s_eval)

        # 11 backend console
        def s_console():
            click("#tabs button[data-view=investigate]")
            wait(1000)
            move("#console")
            wait(3000)
            scroll("#console", -400)
            wait(3000)
            scroll("#console", 4000)
        scene("console", s_console)
        wait(1500)

        total = time.time() - t0
        cast.stop()
        video = cast.out
        ctx.close()
        browser.close()
    print(f"recorded {total:.1f}s -> {video}")
    return video, offsets


def mux(video: Path, audio, offsets):
    names = list(offsets)
    inputs = []
    filt = []
    for i, n in enumerate(names):
        inputs += ["-i", str(audio[n][0])]
        ms = int(offsets[n] * 1000) + 500
        filt.append(f"[{i + 1}:a]adelay={ms}|{ms}[a{i}]")
    filt.append("".join(f"[a{i}]" for i in range(len(names))) + f"amix=inputs={len(names)}:normalize=0:duration=longest[aout]")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), *inputs, "-filter_complex", ";".join(filt),
                    "-map", "0:v", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest", str(OUT)], check=True)
    (ROOT / "video" / "fullstack_narration.md").write_text(
        "# Full-stack demo narration\n\n" + "\n".join(f"## {n} (starts {offsets[n]:.0f}s)\n\n{' '.join(SCENES[n].split())}\n" for n in names))
    print(f"wrote {OUT}: {probe(OUT) / 60:.1f} min")


def main():
    BUILD.mkdir(parents=True, exist_ok=True)
    audio = tts_all()
    log_path = BUILD / "server.log"
    log = open(log_path, "w")
    server = subprocess.Popen([sys.executable, "-m", "server.app", "--port", str(PORT)], cwd=ROOT,
                              stdout=log, stderr=subprocess.STDOUT, text=True)
    try:
        wait_health()
        first = log_path.read_text().splitlines()[0].strip()
        blocks = capture_terminal(first)
        video, offsets = record(audio, blocks)
        mux(video, audio, offsets)
    finally:
        server.terminate()


if __name__ == "__main__":
    main()
