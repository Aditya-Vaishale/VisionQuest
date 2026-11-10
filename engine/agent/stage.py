"""A stage = one job for the AI: instructions, allowed tools and tables, output format, checks, budget."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from engine.agent.budget import Budget

@dataclass(frozen=True)
class Stage:
    name: str
    instructions: str                                     # what this stage must achieve
    output: type[BaseModel]                               # what `finish` must contain (validated)
    tools: tuple[str, ...] = ("look", "query")
    tables: tuple[str, ...] | None = None                 # tables this stage may read; None = all
    check: Callable[[Any, Any], list[str]] | None = None  # finish gate: (output, workspace) -> problems
    thinking: bool = True
    budget: Budget = field(default_factory=Budget)
    max_output_tokens: int | None = None                  # per AI call; None = connector default
