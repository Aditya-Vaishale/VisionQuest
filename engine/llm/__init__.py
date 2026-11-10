"""AI connector. Use get_llm() everywhere; switch providers through .env only."""
from engine.config import LLMSettings
from engine.llm.base import LLMClient, LLMError, LLMResponse, Message, ToolCall, Usage, UsageMeter
from engine.llm.openai_compat import OpenAICompatibleClient

def get_llm(role: str = "main") -> LLMClient:
    """role='main' reads LLM_*; any other role (e.g. 'reviewer') reads REVIEWER_LLM_* first, then LLM_*."""
    prefix = "LLM_" if role == "main" else f"{role.upper()}_LLM_"
    settings = LLMSettings.from_env(prefix)
    if settings.provider == "openai_compatible":
        return OpenAICompatibleClient(settings)
    raise LLMError("config", f"Unknown provider: {settings.provider}")

__all__ = [
    "LLMClient", "LLMError", "LLMResponse", "LLMSettings", "Message",
    "ToolCall", "Usage", "UsageMeter", "get_llm",
]
