"""LLM clients.

* OpenRouterClient - real calls to any OpenRouter model (cheap/free models by default).
* OfflineLLM       - always unavailable; every agent then uses its deterministic
                     fallback path. Lets the whole pipeline run with no API key.
* ScriptedLLM      - test double that answers from a callback.
"""
from __future__ import annotations

import asyncio
import json
import re
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Protocol


class LLMError(Exception):
    """The LLM could not produce a usable answer (network, quota, refusal...)."""


class LLMUnavailable(LLMError):
    pass


@dataclass
class LLMResponse:
    text: str
    prompt_tokens: int
    completion_tokens: int
    model: str
    latency_s: float


class LLMClient(Protocol):
    name: str

    async def complete(self, messages: list[dict], *, max_tokens: int = 1500, json_mode: bool = True) -> LLMResponse: ...


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def parse_json(text: str) -> dict:
    """Extract the first JSON object from a model reply (tolerates fences / chatter)."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.S)
    if fence:
        text = fence.group(1)
    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object in reply")
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError("unbalanced JSON object in reply")


class OfflineLLM:
    name = "offline"

    async def complete(self, messages, *, max_tokens=1500, json_mode=True) -> LLMResponse:
        raise LLMUnavailable("offline backend: no LLM configured")


class ScriptedLLM:
    """Test double: `responder(messages) -> str`."""

    name = "scripted"

    def __init__(self, responder: Callable[[list[dict]], str]):
        self.responder = responder
        self.calls: list[list[dict]] = []

    async def complete(self, messages, *, max_tokens=1500, json_mode=True) -> LLMResponse:
        self.calls.append(messages)
        text = self.responder(messages)
        prompt = sum(estimate_tokens(m["content"]) for m in messages)
        return LLMResponse(text, prompt, estimate_tokens(text), "scripted", 0.0)


class OpenRouterClient:
    name = "openrouter"

    def __init__(self, api_key: str, model: str, fallback_models: list[str] | None = None,
                 base_url: str = "https://openrouter.ai/api/v1", timeout_s: float = 90, temperature: float = 0.1,
                 max_attempts: int = 3, max_concurrency: int = 6):
        if not api_key:
            raise LLMUnavailable("OPENROUTER_API_KEY is not set")
        self.api_key = api_key
        self.models = [model] + [m for m in (fallback_models or []) if m != model]
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.temperature = temperature
        self.max_attempts = max_attempts
        self._sem = asyncio.Semaphore(max_concurrency)
        self._ssl = ssl.create_default_context()

    def _post(self, payload: dict) -> dict:
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json",
                     "HTTP-Referer": "https://github.com/incident-investigator", "X-Title": "incident-investigator"})
        with urllib.request.urlopen(req, timeout=self.timeout_s, context=self._ssl) as r:
            return json.loads(r.read())

    async def complete(self, messages, *, max_tokens=1500, json_mode=True) -> LLMResponse:
        last_err: Exception | None = None
        async with self._sem:
            for model in self.models:
                for attempt in range(self.max_attempts):
                    payload = {"model": model, "messages": messages, "temperature": self.temperature, "max_tokens": max_tokens}
                    if json_mode:
                        payload["response_format"] = {"type": "json_object"}
                    t0 = time.monotonic()
                    try:
                        data = await asyncio.to_thread(self._post, payload)
                        if "error" in data:
                            raise LLMError(str(data["error"]))
                        text = data["choices"][0]["message"].get("content") or ""
                        if not text.strip():
                            raise LLMError("empty completion")
                        usage = data.get("usage") or {}
                        return LLMResponse(
                            text,
                            usage.get("prompt_tokens") or sum(estimate_tokens(m["content"]) for m in messages),
                            usage.get("completion_tokens") or estimate_tokens(text),
                            data.get("model", model), time.monotonic() - t0)
                    except urllib.error.HTTPError as e:
                        last_err = LLMError(f"{model}: HTTP {e.code} {e.read()[:200]!r}")
                        if e.code in (400, 401, 402, 403, 404):
                            break  # not retryable on this model -> try the next model
                    except (urllib.error.URLError, TimeoutError, LLMError, KeyError, json.JSONDecodeError) as e:
                        last_err = LLMError(f"{model}: {e}")
                    await asyncio.sleep(min(8.0, 1.5 * 2 ** attempt))
        raise LLMError(f"all models failed: {last_err}")


def make_client(settings) -> LLMClient:
    if settings.backend == "openrouter":
        return OpenRouterClient(settings.api_key, settings.model, settings.fallback_models, settings.base_url,
                                settings.request_timeout_s, settings.temperature)
    return OfflineLLM()
