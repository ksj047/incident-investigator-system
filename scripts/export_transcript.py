"""Convert a Claude Code session log (.jsonl) into a readable Markdown transcript.

  python scripts/export_transcript.py <session.jsonl> transcript/claude_code_transcript.md
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

MAX_TOOL_IO = 1500


def clip(text: str, n: int = MAX_TOOL_IO) -> str:
    text = text if isinstance(text, str) else json.dumps(text, indent=1)
    return text if len(text) <= n else text[:n] + f"\n... [{len(text) - n} more characters trimmed]"


def main(src: str, dst: str) -> None:
    out = ["# Coding assistant transcript (Claude Code)", "",
           "Exported from the Claude Code session log. Tool inputs/outputs are trimmed for length; "
           "internal reasoning is not included.", ""]
    for line in Path(src).read_text().splitlines():
        d = json.loads(line)
        if d.get("type") not in ("user", "assistant") or d.get("isSidechain"):
            continue
        content = d["message"]["content"]
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        for part in content:
            kind = part.get("type")
            if kind == "text" and part["text"].strip():
                role = "User" if d["type"] == "user" else "Assistant"
                out += [f"### {role}", "", part["text"].strip(), ""]
            elif kind == "tool_use":
                inp = part.get("input", {})
                desc = inp.get("description") or inp.get("file_path") or ""
                body = inp.get("command") or inp.get("content") or json.dumps(inp, indent=1)
                out += [f"**Tool call - {part['name']}** {desc}", "", "```", clip(body), "```", ""]
            elif kind == "tool_result":
                res = part.get("content")
                if isinstance(res, list):
                    res = "\n".join(x.get("text", "[image]") for x in res if isinstance(x, dict))
                out += ["<details><summary>tool result</summary>", "", "```", clip(str(res or "")), "```", "</details>", ""]
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    Path(dst).write_text("\n".join(out))
    print(f"wrote {dst}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
