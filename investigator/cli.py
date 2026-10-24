"""Command line entry point.

  python -m investigator.cli INC-002                 # multi-agent, backend from env
  python -m investigator.cli INC-002 --mode single   # single-agent baseline
  python -m investigator.cli data/incidents/INC-007.json --backend offline --json
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from .agents.orchestrator import investigate
from .baseline import investigate_single
from .config import ROOT, Settings
from .llm import make_client
from .report import to_markdown
from .tools import World


def resolve(incident: str) -> Path:
    p = Path(incident)
    return p if p.exists() else ROOT / "data" / "incidents" / f"{incident}.json"


def main() -> None:
    ap = argparse.ArgumentParser(description="Multi-agent production incident investigator")
    ap.add_argument("incident", help="incident id (e.g. INC-002) or path to an incident world JSON")
    ap.add_argument("--mode", choices=["multi", "single"], default="multi")
    ap.add_argument("--backend", choices=["openrouter", "offline"])
    ap.add_argument("--model")
    ap.add_argument("--json", action="store_true", help="print the JSON report instead of Markdown")
    ap.add_argument("--trace", help="write full trace/state JSON to this path")
    args = ap.parse_args()

    settings = Settings()
    if args.backend:
        settings.backend = args.backend
    if args.model:
        settings.model = args.model
    world = World.load(resolve(args.incident))
    llm = make_client(settings)
    fn = investigate if args.mode == "multi" else investigate_single
    report = asyncio.run(fn(world, settings, llm))
    print(json.dumps(report, indent=2) if args.json else to_markdown(report))


if __name__ == "__main__":
    main()
