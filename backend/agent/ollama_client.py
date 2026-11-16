"""Minimal Ollama chat client with explicit failure modes.

The agent runs fully offline against the user's local Ollama. Defaults:
host http://127.0.0.1:11434, model gemma4:e4b (override with
TEMPO_OLLAMA_HOST / TEMPO_OLLAMA_MODEL in .env — e.g. gemma4:e4b).

Two calling modes:
* native — the /api/chat request carries the tool specs and the model returns
  structured tool_calls (Ollama models with tool templates, e.g. llama3.1,
  qwen2.5).
* json — models whose Ollama template has no tool support (gemma family)
  reject the tools parameter with a 400. The client detects that once and the
  service switches to prompt-mode: the model is instructed to answer either
  with plain text or with a single JSON object {"tool": ..., "arguments": ...}.
  Parsing of that object is strict and happens in service.py.

Nothing here raises except OllamaError with a user-friendly message.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from django.conf import settings


class OllamaError(Exception):
    def __init__(self, message: str, kind: str = "error", status: int | None = None):
        super().__init__(message)
        self.kind = kind  # unreachable | timeout | http | tools_unsupported
        self.status = status


def ollama_host() -> str:
    return str(getattr(settings, "TEMPO_OLLAMA_HOST", "http://127.0.0.1:11434")).rstrip("/")


def ollama_model() -> str:
    return str(getattr(settings, "TEMPO_OLLAMA_MODEL", "gemma4:e4b"))


def _request(path: str, payload: dict | None, timeout: float) -> dict:
    url = f"{ollama_host()}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", "replace")[:400]
        except Exception:
            body = ""
        lowered = body.lower()
        if "does not support tools" in lowered or "not support tool" in lowered:
            raise OllamaError("This model has no native tool support.", kind="tools_unsupported",
                              status=exc.code) from exc
        raise OllamaError(f"Ollama returned HTTP {exc.code}: {body or exc.reason}",
                          kind="http", status=exc.code) from exc
    except urllib.error.URLError as exc:
        raise OllamaError(
            f"Could not reach Ollama at {ollama_host()} ({getattr(exc, 'reason', exc)}). "
            "Start it with `ollama serve` and make sure the model is pulled "
            f"(`ollama pull {ollama_model()}`).", kind="unreachable") from exc
    except TimeoutError as exc:
        raise OllamaError("Ollama took too long to respond — try again or use a smaller model.",
                          kind="timeout") from exc
    except json.JSONDecodeError as exc:
        raise OllamaError("Ollama returned a non-JSON response.", kind="http") from exc


def status() -> dict:
    """Cheap reachability + model presence probe for the UI status chip."""
    try:
        url = f"{ollama_host()}/api/tags"
        with urllib.request.urlopen(url, timeout=2) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        models = [m.get("name", "") for m in data.get("models", [])]
        model = ollama_model()
        pulled = any(m == model or m.split(":")[0] == model.split(":")[0] for m in models)
        return {"ok": True, "model": model, "pulled": pulled, "models": models[:12]}
    except Exception as exc:
        return {"ok": False, "model": ollama_model(), "pulled": False, "error": str(exc)[:200],
                "hint": f"Install/run Ollama locally ({ollama_host()}) and `ollama pull {ollama_model()}`"}


def chat(messages: list[dict], tools: list[dict] | None = None, timeout: float = 180.0) -> dict:
    """One non-streaming /api/chat call.
    Returns {"content": str, "tool_calls": [{"name", "arguments"}...]}.
    Raises OllamaError(kind=...) on failure.
    Low temperature + a prediction cap keep small local models from rambling
    or echoing the whole system prompt (a common 1B-class failure mode)."""
    payload: dict = {"model": ollama_model(), "messages": messages, "stream": False,
                     "options": {"temperature": 0.2, "num_predict": 400}}
    if tools:
        payload["tools"] = tools
    try:
        data = _request("/api/chat", payload, timeout)
    except OllamaError as exc:
        if exc.kind == "http" and exc.status == 400 and tools:
            # Some builds report unsupported tools with a generic 400 body.
            if "tool" in str(exc).lower():
                exc.kind = "tools_unsupported"
        raise
    message = data.get("message") or {}
    tool_calls = []
    for call in message.get("tool_calls") or []:
        fn = call.get("function") or {}
        args = fn.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = None
        tool_calls.append({"name": str(fn.get("name") or ""),
                           "arguments": args if isinstance(args, dict) else {}})
    return {"content": str(message.get("content") or ""), "tool_calls": tool_calls}
