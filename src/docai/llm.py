"""Minimal Ollama client with JSON-schema constrained output."""

from __future__ import annotations

import json
import os
import time

import httpx
from pydantic import BaseModel

DEFAULT_MODEL = os.environ.get("DOCAI_MODEL", "qwen2.5:7b")
DEFAULT_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_s: float = 0.0


class OllamaClient:
    def __init__(self, model: str = DEFAULT_MODEL, host: str = DEFAULT_HOST, num_ctx: int = 8192, timeout: float = 600):
        self.model = model
        self.host = host.rstrip("/")
        # Ollama's default context window silently truncates multi-page documents.
        self.num_ctx = num_ctx
        self._http = httpx.Client(timeout=timeout)

    def chat_json(self, system: str, user: str, schema: dict) -> tuple[dict, Usage]:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "format": schema,
            "stream": False,
            "options": {"temperature": 0, "seed": 0, "num_ctx": self.num_ctx},
        }
        start = time.perf_counter()
        resp = self._http.post(f"{self.host}/api/chat", json=payload)
        resp.raise_for_status()
        body = resp.json()
        usage = Usage(
            prompt_tokens=body.get("prompt_eval_count", 0),
            completion_tokens=body.get("eval_count", 0),
            latency_s=round(time.perf_counter() - start, 3),
        )
        return json.loads(body["message"]["content"]), usage
