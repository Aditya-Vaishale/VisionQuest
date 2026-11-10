"""Connector for any OpenAI-compatible API: NVIDIA (default), OpenAI, OpenRouter, vLLM, Ollama."""
from __future__ import annotations

import json
import random
import re
import time
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    OpenAI,
    PermissionDeniedError,
    RateLimitError,
)

from engine.config import LLMSettings
from engine.llm.base import LLMError, LLMResponse, Message, ToolCall, Usage, UsageMeter
from engine.llm.rate_limit import RateLimiter

_RETRYABLE = (RateLimitError, APITimeoutError, APIConnectionError, InternalServerError)
_THINK_BLOCK = re.compile(r"<think>(.*?)</think>", re.DOTALL)

# Order matters: subclasses first (APITimeoutError is a kind of APIConnectionError).
_ERROR_KINDS: list[tuple[type[Exception], str, str]] = [
    (AuthenticationError, "auth", "API key rejected (401). Check the key in .env."),
    (PermissionDeniedError, "permission", "This key has no access to the model (403)."),
    (NotFoundError, "not_found", "Model or endpoint not found (404). Check LLM_MODEL / LLM_BASE_URL."),
    (RateLimitError, "rate_limit", "Still rate-limited after retries (429)."),
    (BadRequestError, "bad_request", "Request rejected by the provider (400)."),
    (APITimeoutError, "timeout", "No reply before the timeout, even after retries."),
    (APIConnectionError, "connection", "Could not reach the provider. Check internet / VPN / proxy."),
    (InternalServerError, "server", "Provider server error (5xx), even after retries."),
]

class OpenAICompatibleClient:
    def __init__(self, settings: LLMSettings) -> None:
        self.settings = settings
        self.meter = UsageMeter()
        self._limiter = RateLimiter(settings.requests_per_minute)
        # SDK retries are off: we retry ourselves so every attempt passes the rate limiter.
        self._client = OpenAI(
            base_url=settings.base_url,
            api_key=settings.api_key.get_secret_value(),
            timeout=settings.timeout_s,
            max_retries=0,
        )

    def chat(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] = "auto",
        thinking: bool = False,
        json_mode: bool = False,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMResponse:
        params = self._build_params(
            messages, tools, tool_choice, thinking, json_mode, max_output_tokens, temperature
        )
        last_attempt = self.settings.max_retries

        for attempt in range(last_attempt + 1):
            self._limiter.acquire()
            started = time.perf_counter()
            try:
                raw = self._client.chat.completions.create(**params)
            except _RETRYABLE as exc:
                self.meter.record_failure()
                if attempt == last_attempt:
                    raise _as_llm_error(exc) from exc
                time.sleep(_backoff_seconds(exc, attempt))
                continue
            except APIStatusError as exc:  # other 4xx: retrying will not help
                self.meter.record_failure()
                raise _as_llm_error(exc) from exc

            response = _parse(raw, time.perf_counter() - started)
            self.meter.record(response.usage, response.latency_s)

            if not response.content and not response.tool_calls:
                hint = " It ran out of room; raise max_output_tokens." if response.finish_reason == "length" else ""
                raise LLMError(
                    "empty_response",
                    f"Model replied with no text and no tool call (finish_reason={response.finish_reason}).{hint}",
                )
            return response

        raise LLMError("unknown", "Retry loop ended unexpectedly.")  # not reachable

    def _build_params(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None,
        tool_choice: str | dict[str, Any],
        thinking: bool,
        json_mode: bool,
        max_output_tokens: int | None,
        temperature: float | None,
    ) -> dict[str, Any]:
        s = self.settings
        params: dict[str, Any] = {
            "model": s.model,
            "messages": messages,
            "max_tokens": max_output_tokens or s.max_output_tokens,
            "temperature": s.temperature if temperature is None else temperature,
            "top_p": s.top_p,
        }
        if tools:
            params["tools"] = tools
            params["tool_choice"] = tool_choice
        if json_mode and s.supports_json_mode:
            params["response_format"] = {"type": "json_object"}
        if s.thinking_style == "nemotron":
            # NVIDIA's on/off switch for thinking. With style "none", `thinking` is ignored.
            params["extra_body"] = {"chat_template_kwargs": {"enable_thinking": thinking}}
        return params

def _parse(raw: Any, latency_s: float) -> LLMResponse:
    choice = raw.choices[0] if raw.choices else None
    message = choice.message if choice else None
    content, inline_thoughts = _split_think_tags((message.content or "") if message else "")
    return LLMResponse(
        content=content,
        tool_calls=_tool_calls(message),
        reasoning=_reasoning_field(message) or inline_thoughts,
        finish_reason=choice.finish_reason if choice else None,
        usage=_usage(getattr(raw, "usage", None)),
        latency_s=latency_s,
        model=getattr(raw, "model", "") or "",
    )

def _split_think_tags(content: str) -> tuple[str, str | None]:
    """Some servers leave thinking inside the text as <think>...</think>; move it out."""
    thoughts = [t.strip() for t in _THINK_BLOCK.findall(content)]
    content = _THINK_BLOCK.sub("", content)
    if "</think>" in content:  # opening tag was in the prompt template; only the closing one came back
        before, _, content = content.rpartition("</think>")
        thoughts.append(before.strip())
    thoughts = [t for t in thoughts if t]
    return content.strip(), ("\n\n".join(thoughts) or None)

def _reasoning_field(message: Any) -> str | None:
    """Servers name the thinking field differently; check the known names."""
    if message is None:
        return None
    extra = getattr(message, "model_extra", None) or {}
    for key in ("reasoning_content", "reasoning"):
        value = getattr(message, key, None) or extra.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None

def _tool_calls(message: Any) -> tuple[ToolCall, ...]:
    calls: list[ToolCall] = []
    for index, call in enumerate(getattr(message, "tool_calls", None) or []):
        function = getattr(call, "function", None)
        if function is None:  # non-function tool types are not used by this app
            continue
        raw_args = function.arguments or "{}"
        try:
            parsed = json.loads(raw_args)
            error = None if isinstance(parsed, dict) else "Tool arguments must be a JSON object."
        except json.JSONDecodeError as exc:
            parsed, error = {}, f"Tool arguments are not valid JSON: {exc}"
        calls.append(
            ToolCall(
                id=call.id or f"call_{index}",
                name=function.name,
                arguments=parsed if isinstance(parsed, dict) else {},
                raw_arguments=raw_args,
                parse_error=error,
            )
        )
    return tuple(calls)

def _usage(raw_usage: Any) -> Usage:
    if raw_usage is None:
        return Usage()
    details = getattr(raw_usage, "completion_tokens_details", None)
    return Usage(
        input_tokens=getattr(raw_usage, "prompt_tokens", 0) or 0,
        output_tokens=getattr(raw_usage, "completion_tokens", 0) or 0,
        reasoning_tokens=getattr(details, "reasoning_tokens", 0) or 0,
    )

def _backoff_seconds(exc: Exception, attempt: int) -> float:
    """Honour the server's Retry-After if given; otherwise 1s, 2s, 4s... plus jitter."""
    response = getattr(exc, "response", None)
    retry_after = response.headers.get("retry-after") if response is not None else None
    if retry_after:
        try:
            return min(float(retry_after), 60.0)
        except ValueError:
            pass
    return min(2.0**attempt, 30.0) + random.uniform(0.0, 1.0)

def _as_llm_error(exc: Exception) -> LLMError:
    detail = getattr(exc, "message", "") or str(exc)
    for exc_type, kind, text in _ERROR_KINDS:
        if isinstance(exc, exc_type):
            return LLMError(kind, f"{text} Details: {detail}")
    status = getattr(exc, "status_code", "?")
    return LLMError("unknown", f"Provider error ({status}). Details: {detail}")
