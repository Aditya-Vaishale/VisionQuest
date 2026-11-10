"""Provider-neutral types. The rest of the app only sees these, never a vendor SDK."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Protocol

from engine.config import LLMSettings

Message = dict[str, Any]  # OpenAI-style chat message: {"role": ..., "content": ...}

class LLMError(RuntimeError):
    """Single error type for callers. `kind` says what happened: 'auth', 'rate_limit', ..."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind

@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str
    parse_error: str | None = None  # set when the model sent broken JSON, so the loop can ask it to fix

@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0     # includes thinking tokens
    reasoning_tokens: int = 0

@dataclass(frozen=True)
class LLMResponse:
    content: str
    tool_calls: tuple[ToolCall, ...]
    reasoning: str | None
    finish_reason: str | None
    usage: Usage
    latency_s: float
    model: str

    def as_history_message(self) -> Message:
        """Assistant turn to add back into the conversation.
        Thinking text is left out on purpose (NVIDIA advises not to feed it back)."""
        message: Message = {
            "role": "assistant",
            "content": self.content if (self.content or not self.tool_calls) else None,
        }
        if self.tool_calls:
            message["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": call.raw_arguments},
                }
                for call in self.tool_calls
            ]
        return message

@dataclass
class UsageMeter:
    """Running totals for one client. The loop engine's budget will read these."""

    calls: int = 0
    failed_attempts: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    seconds: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def record(self, usage: Usage, latency_s: float) -> None:
        with self._lock:
            self.calls += 1
            self.input_tokens += usage.input_tokens
            self.output_tokens += usage.output_tokens
            self.reasoning_tokens += usage.reasoning_tokens
            self.seconds += latency_s

    def record_failure(self) -> None:
        with self._lock:
            self.failed_attempts += 1

    def snapshot(self) -> dict[str, int | float]:
        with self._lock:
            return {
                "calls": self.calls,
                "failed_attempts": self.failed_attempts,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "reasoning_tokens": self.reasoning_tokens,
                "seconds": round(self.seconds, 2),
            }

class LLMClient(Protocol):
    """What every provider connector must offer."""

    settings: LLMSettings
    meter: UsageMeter

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
    ) -> LLMResponse: ...
