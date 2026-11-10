"""Terminal helpers for the check scripts: show the AI's question with numbered options."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from engine.agent import Agent, Question, RunResult

def pick_answer(q: Question) -> str:
    print(f"   AI asks: {q.question}")
    if q.why_it_matters:
        print(f"   why it matters: {q.why_it_matters}")
    for i, option in enumerate(q.options, 1):
        print(f"     {i}. {option}")
    try:
        typed = input("   your answer (number, or type your own; Enter = 1): ").strip()
    except EOFError:
        typed = ""
    if not typed:
        return q.options[0] if q.options else "no preference"
    if typed.isdigit() and 1 <= int(typed) <= len(q.options):
        return q.options[int(typed) - 1]
    return typed

def ask_loop(agent: Agent, outcome: Any, resume: Callable[[Agent, RunResult, str], Any]) -> Any:
    """Answer the AI's questions from the terminal until the stage stops asking."""
    while outcome.run.status == "needs_user" and outcome.run.question is not None:
        outcome = resume(agent, outcome.run, pick_answer(outcome.run.question))
    return outcome
