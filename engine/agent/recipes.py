"""Recipes: saved metric definitions. Data, not numbers: the SQL is re-run whenever a value is needed."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

_NAME = re.compile(r"[a-z][a-z0-9_]{0,59}")

class Recipe(BaseModel):
    name: str
    meaning: str                                            # what the number means, in plain words
    sql: str                                                # one read-only SELECT; re-run for filters and checks
    assumptions: list[str] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)        # result columns when saved
    preview: list[list[Any]] = Field(default_factory=list)  # first rows when saved (JSON-safe)
    saved_at: str = ""
    version: int = 1                                        # goes up each time the AI replaces it

class RecipeBook:
    def __init__(self) -> None:
        self._items: dict[str, Recipe] = {}

    @staticmethod
    def valid_name(name: str) -> bool:
        return bool(_NAME.fullmatch(name))

    def save(self, recipe: Recipe) -> Recipe:
        old = self._items.get(recipe.name)
        stored = recipe.model_copy(update={
            "version": old.version + 1 if old else 1,
            "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        self._items[recipe.name] = stored
        return stored

    def get(self, name: str) -> Recipe | None:
        return self._items.get(name)

    def all(self) -> list[Recipe]:
        return list(self._items.values())

    def __contains__(self, name: object) -> bool:
        return name in self._items

    def __len__(self) -> int:
        return len(self._items)
