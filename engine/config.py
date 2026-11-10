"""
App settings, read from .env (never hard-coded).

Every LLM setting can be overridden per role with a prefix. Example: the
reviewer AI can set REVIEWER_LLM_MODEL while all other values fall back
to LLM_*. Only LLM settings exist for now; later stages add their own.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field, SecretStr

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# Also accepted, so an existing .env keeps working.
_LEGACY_KEY_NAMES = ("NVIDIA_API_KEY", "NGC_API_KEY", "API_KEY")

# Settings field -> .env name (without prefix)
_ENV_NAMES = {
    "provider": "PROVIDER",
    "base_url": "BASE_URL",
    "model": "MODEL",
    "temperature": "TEMPERATURE",
    "top_p": "TOP_P",
    "max_output_tokens": "MAX_OUTPUT_TOKENS",
    "timeout_s": "TIMEOUT_S",
    "max_retries": "MAX_RETRIES",
    "requests_per_minute": "REQUESTS_PER_MINUTE",
    "thinking_style": "THINKING_STYLE",
    "supports_json_mode": "SUPPORTS_JSON_MODE",
}

def _read(prefix: str, name: str) -> str | None:
    """Return {prefix}{name}, else LLM_{name}, else None. Blank counts as missing."""
    for key in dict.fromkeys((f"{prefix}{name}", f"LLM_{name}")):
        value = (os.getenv(key) or "").strip()
        if value:
            return value
    return None

class LLMSettings(BaseModel):
    provider: Literal["openai_compatible"] = "openai_compatible"
    base_url: str = "https://integrate.api.nvidia.com/v1"
    model: str = "nvidia/nemotron-3-ultra-550b-a55b"
    api_key: SecretStr                                    # hidden when printed/logged
    temperature: float = Field(default=1.0, ge=0.0, le=2.0)
    top_p: float = Field(default=0.95, gt=0.0, le=1.0)
    max_output_tokens: int = Field(default=8192, gt=0)    # thinking text counts toward this
    timeout_s: float = Field(default=180.0, gt=0)         # thinking replies can be slow
    max_retries: int = Field(default=3, ge=0, le=10)
    requests_per_minute: int = Field(default=35, gt=0)    # free tier is ~40; stay under it
    thinking_style: Literal["nemotron", "none"] = "nemotron"
    supports_json_mode: bool = True

    @classmethod
    def from_env(cls, prefix: str = "LLM_") -> LLMSettings:
        api_key = _read(prefix, "API_KEY") or next(
            (v for v in ((os.getenv(n) or "").strip() for n in _LEGACY_KEY_NAMES) if v),
            None,
        )
        if not api_key:
            raise RuntimeError("No API key found. Add LLM_API_KEY=... (or NVIDIA_API_KEY=...) to .env")

        overrides = {
            field: value
            for field, env_name in _ENV_NAMES.items()
            if (value := _read(prefix, env_name)) is not None
        }
        return cls(api_key=api_key, **overrides)
