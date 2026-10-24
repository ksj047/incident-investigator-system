"""Render docs/architecture.png (also used in the walkthrough video)."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONT = "/usr/share/fonts/opentype/inter/Inter-SemiBold.otf"
FONT_R = "/usr/share/fonts/opentype/inter/Inter-Regular.otf"

BG, INK, MUTED = "#0f172a", "#e2e8f0", "#94a3b8"
C = {"orch": "#f97316", "spec": "#38bdf8", "ana": "#a78bfa", "rep": "#34d399", "tool": "#facc15", "state": "#f472b6", "fb": "#64748b"}


def font(size, bold=True):
    return ImageFont.truetype(FONT if bold else FONT_R, size)


def box(d, xy, title, lines, color, title_size=30, body_size=21):
    x0, y0, x1, y1 = xy
    d.rounded_rectangle(xy, radius=18, fill="#1e293b", outline=color, width=4)
    d.text((x0 + 20, y0 + 14), title, font=font(title_size), fill=color)
    y = y0 + 18 + title_size + 8
    for ln in lines:
        d.text((x0 + 20, y), ln, font=font(body_size, False), fill=INK)
        y += body_size + 7


def arrow(d, p0, p1, color=INK, width=4, label=None, dashed=False, label_off=(8, -30)):
    import math
    if dashed:
        n = int(math.dist(p0, p1) // 18)
        for i in range(0, n, 2):
            a = (p0[0] + (p1[0] - p0[0]) * i / n, p0[1] + (p1[1] - p0[1]) * i / n)
            b = (p0[0] + (p1[0] - p0[0]) * (i + 1) / n, p0[1] + (p1[1] - p0[1]) * (i + 1) / n)
            d.line([a, b], fill=color, width=width)
    else:
        d.line([p0, p1], fill=color, width=width)
    ang = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
    s = 18
    d.polygon([p1, (p1[0] - s * math.cos(ang - 0.4), p1[1] - s * math.sin(ang - 0.4)),
               (p1[0] - s * math.cos(ang + 0.4), p1[1] - s * math.sin(ang + 0.4))], fill=color)
    if label:
        mx, my = (p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2
        d.text((mx + label_off[0], my + label_off[1]), label, font=font(20), fill=color)


def draw(path: Path, size=(1920, 1080)):
    img = Image.new("RGB", size, BG)
    d = ImageDraw.Draw(img)
    d.text((60, 30), "Multi-agent incident investigation - architecture", font=font(40), fill=INK)

    box(d, (60, 120, 420, 270), "Incident report", ["title, symptoms, onset,", "reported service, severity"], MUTED)
    box(d, (560, 110, 1360, 300), "Orchestrator", ["LLM plan -> task DAG (depends_on); runs ready tasks in parallel",
                                                   "feedback loop: max 3 rounds; budgets: tool/LLM calls, tokens, wall time",
                                                   "termination: accept | inconclusive | max rounds | budget"], C["orch"])
    arrow(d, (420, 195), (560, 195))

    box(d, (120, 390, 680, 590), "Observability agent", ["tool loop: query_logs, query_metrics,", "get_service_dependencies",
                                                          "follows leads down the dependency chain"], C["spec"])
    box(d, (760, 390, 1320, 590), "Dependency agent", ["tool loop: get_deployments, get_config_changes,", "get_service_dependencies, search_incident_history",
                                                        "change timeline + topology + history"], C["spec"])
    d.text((1140, 330), "round N - in parallel", font=font(22), fill=C["spec"])
    arrow(d, (800, 300), (400, 390))
    arrow(d, (1120, 300), (1040, 390))

    box(d, (1440, 360, 1880, 620), "Tool layer", ["schema validation", "timeouts + bounded retries", "budget enforcement",
                                                  "scripted faults: timeout,", "partial data, HTTP 503", "+ random chaos"], C["tool"])
    arrow(d, (1320, 470), (1440, 470), C["tool"])
    arrow(d, (1600, 620), (1600, 680), C["tool"])
    box(d, (1440, 680, 1880, 900), "Simulated world", ["logs  metrics  deployments", "config changes  dependency graph",
                                                       "historical incidents", "(12 incident files)"], MUTED)

    box(d, (120, 680, 1320, 790), "Shared investigation state (blackboard)",
        ["evidence (fact / inference / assumption + record refs) - hypotheses - tasks - critiques - tool calls - budget - trace"], C["state"], body_size=20)
    arrow(d, (400, 590), (400, 680), C["state"], label="findings")
    arrow(d, (1040, 590), (1040, 680), C["state"], label="findings")

    box(d, (120, 860, 500, 1040), "Reasoning agent", ["competing hypotheses,", "cites evidence ids,", "calibrated confidence"], C["ana"])
    box(d, (580, 860, 960, 1040), "Critic agent", ["LLM critique + rule checks", "(timeline, victims, gaps,", "independent cross-check)"], C["ana"])
    box(d, (1110, 860, 1420, 1040), "Reporting agent", ["ranked hypotheses,", "facts vs assumptions,", "actions"], C["rep"])
    arrow(d, (310, 790), (310, 860), C["state"])
    arrow(d, (500, 950), (580, 950), C["ana"])
    arrow(d, (960, 950), (1110, 950), C["rep"])
    d.text((972, 896), "accept /", font=font(20), fill=C["rep"])
    d.text((972, 918), "inconclusive", font=font(20), fill=C["rep"])
    # feedback loop
    d.line([(770, 860), (770, 820), (1390, 820), (1390, 330), (1360, 330)], fill=C["orch"], width=4)
    arrow(d, (1390, 330), (1362, 300), C["orch"])
    d.text((790, 828), "critic says investigate -> follow-up tasks (feedback loop)", font=font(20), fill=C["orch"])
    d.text((1440, 925), "Every agent: deterministic fallback", font=font(22), fill=C["fb"])
    d.text((1440, 955), "on LLM / tool failure (recovery)", font=font(22), fill=C["fb"])
    d.text((1440, 985), "LLM: OpenRouter (cheap / free)", font=font(22), fill=C["fb"])
    img.save(path)


if __name__ == "__main__":
    out = ROOT / "docs" / "architecture.png"
    draw(out)
    print("wrote", out)
