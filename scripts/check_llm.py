"""
Step 1 check: does the AI connector work end to end?
Tests: plain reply, thinking, a full tool-call round trip, JSON output.
Run from the project folder:  python -m scripts.check_llm
"""
from __future__ import annotations

import json
import sys
from collections.abc import Callable

from engine.llm import LLMClient, LLMError, get_llm

STOP_KINDS = {"auth", "permission", "not_found", "connection", "config"}  # later checks would fail too

COUNT_ROWS_TOOL = {
    "type": "function",
    "function": {
        "name": "count_rows",
        "description": "Return how many rows a table in the loaded dataset has.",
        "parameters": {
            "type": "object",
            "properties": {"table": {"type": "string", "description": "Table name"}},
            "required": ["table"],
        },
    },
}

class CheckFailed(Exception):
    pass

def expect(condition: object, problem: str) -> None:
    if not condition:
        raise CheckFailed(problem)

def check_plain(llm: LLMClient) -> str:
    r = llm.chat(
        [{"role": "user", "content": "Tell me a single-line joke. Reply with only the joke."}],
        max_output_tokens=200,
    )
    expect(r.content, "empty reply")
    return f"{r.content!r} ({r.latency_s:.1f}s)"

def check_thinking(llm: LLMClient) -> str:
    r = llm.chat(
        [{"role": "user", "content": "Pens cost $4 for a pack of 3. How much do 12 pens cost? Reply with only the number."}],
        thinking=True,
        max_output_tokens=4096,
    )
    expect("16" in r.content, f"expected 16, got {r.content!r}")
    shown = "returned" if r.reasoning else "not returned"
    return f"answer {r.content!r} | {r.usage.reasoning_tokens} thinking tokens, thinking text {shown} ({r.latency_s:.1f}s)"

def check_tools(llm: LLMClient) -> str:
    messages = [
        {"role": "system", "content": "You can call tools. The dataset has one table named 'sales'."},
        {"role": "user", "content": "How many rows does the sales table have? Use the tool, then answer in one short sentence."},
    ]
    first = llm.chat(messages, tools=[COUNT_ROWS_TOOL])
    expect(first.tool_calls, f"model answered without calling the tool: {first.content[:80]!r}")
    for call in first.tool_calls:
        expect(call.parse_error is None, f"broken tool arguments: {call.parse_error}")
        expect(call.name == "count_rows", f"called unknown tool {call.name!r}")

    messages.append(first.as_history_message())
    for call in first.tool_calls:  # every tool call needs its own reply
        messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps({"rows": 1234})})

    final = llm.chat(messages, tools=[COUNT_ROWS_TOOL])
    expect("1234" in final.content.replace(",", ""), f"answer ignored the tool result: {final.content!r}")
    call = first.tool_calls[0]
    return f"{call.name}({call.arguments}) -> {final.content!r}"

def check_json(llm: LLMClient) -> str:
    r = llm.chat(
        [
            {"role": "system", "content": "Reply with a single JSON object only."},
            {"role": "user", "content": 'A CSV column is named "order_date". Return {"column": <name>, "role": <one of "id", "measure", "category", "date">}.'},
        ],
        json_mode=True,
        max_output_tokens=300,
    )
    try:
        data = json.loads(r.content)
    except json.JSONDecodeError:
        raise CheckFailed(f"not valid JSON: {r.content[:120]!r}") from None
    expect(isinstance(data, dict) and data.get("role") == "date", f"unexpected JSON: {data}")
    return json.dumps(data)

CHECKS: list[tuple[str, Callable[[LLMClient], str]]] = [
    ("Plain reply (thinking off)", check_plain),
    ("Thinking on", check_thinking),
    ("Tool call round trip", check_tools),
    ("JSON output", check_json),
]

def main() -> int:
    try:
        llm = get_llm()
    except (RuntimeError, ValueError) as exc:  # missing key or bad value in .env
        print(f"✗ Settings problem: {exc}")
        return 1
    print(f"Model:    {llm.settings.model}\nEndpoint: {llm.settings.base_url}\n")

    passed = 0
    for name, check in CHECKS:
        try:
            print(f"✓ {name}: {check(llm)}")
            passed += 1
        except CheckFailed as exc:
            print(f"✗ {name}: {exc}")
        except LLMError as exc:
            print(f"✗ {name}: [{exc.kind}] {exc}")
            if exc.kind in STOP_KINDS:
                break

    m = llm.meter.snapshot()
    print(
        f"\n{passed}/{len(CHECKS)} passed | {m['calls']} calls | "
        f"{m['input_tokens']} in / {m['output_tokens']} out tokens ({m['reasoning_tokens']} thinking) | "
        f"{m['seconds']}s | {m['failed_attempts']} failed attempts"
    )
    return 0 if passed == len(CHECKS) else 1

if __name__ == "__main__":
    sys.exit(main())
