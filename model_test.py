"""
check_model.py
Quick check: can we reach NVIDIA Nemotron 3 Ultra? Asks it for a one-line joke.
Run from the project folder:  python check_model.py
"""
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    NotFoundError,
    OpenAI,
    PermissionDeniedError,
    RateLimitError,
)

BASE_URL = "https://integrate.api.nvidia.com/v1"
MODEL = "nvidia/nemotron-3-ultra-550b-a55b"
KEY_NAMES = ("NVIDIA_API_KEY", "NGC_API_KEY", "API_KEY")  # first one found is used

def load_api_key() -> str:
    """Read the key from .env (next to this file). Never prints the value."""
    load_dotenv(Path(__file__).with_name(".env"))
    for name in KEY_NAMES:
        key = os.getenv(name, "").strip()
        if key:
            print(f"✓ API key found in {name} (hidden)")
            return key
    sys.exit(f"✗ No API key found. Add one of {', '.join(KEY_NAMES)} to .env")

def suggest_model_names(client: OpenAI) -> None:
    """If the model name is wrong, list the Nemotron Ultra names this key can see."""
    try:
        names = [m.id for m in client.models.list() if "nemotron-3-ultra" in m.id]
        print("  Available names:", ", ".join(names) or "none found")
    except Exception as exc:  # only a hint; never hide the main error
        print(f"  Could not list models: {exc}")

def main() -> None:
    client = OpenAI(base_url=BASE_URL, api_key=load_api_key(), timeout=60, max_retries=1)

    print(f"→ Calling {MODEL} ...")
    start = time.perf_counter()
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": "Tell me a single-line joke. Reply with only the joke."}],
            max_tokens=200,
            temperature=1.0,
            top_p=0.95,
            # Thinking off: a joke needs no deep reasoning, keeps the reply fast
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
    except AuthenticationError:
        sys.exit("✗ Key rejected (401). Check the key in .env.")
    except PermissionDeniedError:
        sys.exit("✗ Key has no access to this model (403).")
    except NotFoundError:
        print(f"✗ Model '{MODEL}' not found (404).")
        suggest_model_names(client)
        sys.exit(1)
    except RateLimitError:
        sys.exit("✗ Rate limit hit (429). Wait a minute and retry.")
    except APITimeoutError:
        sys.exit("✗ Timed out after 60s. Service may be busy; retry.")
    except APIConnectionError:
        sys.exit("✗ Could not connect. Check internet / VPN / proxy.")
    except APIStatusError as exc:
        sys.exit(f"✗ Unexpected error {exc.status_code}: {exc.message}")

    seconds = time.perf_counter() - start
    choice = response.choices[0]
    joke = (choice.message.content or "").strip()

    if not joke:
        sys.exit(f"✗ Model replied but text was empty (finish_reason={choice.finish_reason}).")

    print("✓ Model is reachable")
    print(f"  Joke: {joke}")
    usage = response.usage
    tokens = f"{usage.prompt_tokens} in / {usage.completion_tokens} out" if usage else "n/a"
    print(f"  Time: {seconds:.1f}s | Tokens: {tokens}")

if __name__ == "__main__":
    main()
