"""Runtime configuration (env-driven, with safe defaults)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"'))


_load_dotenv()


@dataclass
class Limits:
    max_rounds: int = 3              # orchestrator feedback-loop rounds (reason -> critique -> more evidence)
    agent_max_steps: int = 5         # tool-loop steps per agent task
    max_parallel_calls: int = 4      # tool calls an agent may issue in one step
    max_tool_calls: int = 70         # per investigation
    max_llm_calls: int = 45          # per investigation
    max_tokens: int = 300_000        # per investigation (prompt + completion)
    max_wall_seconds: float = 420.0  # per investigation
    tool_timeout_s: float = 0.3      # simulated tool call timeout
    tool_retries: int = 2            # bounded retries per tool call
    llm_retries: int = 2             # re-asks on invalid JSON per agent call
    inconclusive_threshold: float = 0.45


@dataclass
class Settings:
    backend: str = field(default_factory=lambda: os.getenv("LLM_BACKEND", "openrouter" if os.getenv("OPENROUTER_API_KEY") else "offline"))
    api_key: str | None = field(default_factory=lambda: os.getenv("OPENROUTER_API_KEY"))
    # Cheap default (~$0.09 / 1M input tokens) with a free fallback.
    model: str = field(default_factory=lambda: os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-v4-flash"))
    fallback_models: list[str] = field(default_factory=lambda: [m for m in os.getenv(
        "OPENROUTER_FALLBACK_MODELS", "google/gemma-4-31b-it:free").split(",") if m])
    base_url: str = field(default_factory=lambda: os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"))
    request_timeout_s: float = float(os.getenv("LLM_TIMEOUT_S", "90"))
    temperature: float = 0.1
    chaos_rate: float = float(os.getenv("TOOL_CHAOS_RATE", "0.05"))  # random transient tool failures on top of scripted faults
    seed: int = 7
    limits: Limits = field(default_factory=Limits)
