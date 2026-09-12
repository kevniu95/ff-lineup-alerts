"""
LLM connectivity spike (Claude) -- see docs/build-plan.md step 1.

Throwaway: one prompt in, one response out. Confirms our own API key/billing
account can reach Claude programmatically, and reports real cost/latency/shape
so step 5's Telegram-to-LLM plumbing isn't built on a wrong assumption.

Run: .venv/bin/python scripts/spike_llm_claude.py
"""
import os
import time
from pathlib import Path

import anthropic

MODEL = "claude-sonnet-5"
PRICE_PER_MTOK = {"input": 2.00, "output": 10.00}


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> None:
    load_dotenv(Path(__file__).parent.parent / ".env")

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY

    prompt = (
        "I have Christian McCaffrey and Rachaad White on my bench, and my "
        "flex spot is empty this week. Who should I start in flex?"
    )

    start = time.monotonic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    elapsed = time.monotonic() - start

    text = next((b.text for b in response.content if b.type == "text"), "")
    input_cost = response.usage.input_tokens / 1_000_000 * PRICE_PER_MTOK["input"]
    output_cost = response.usage.output_tokens / 1_000_000 * PRICE_PER_MTOK["output"]

    print(f"--- Claude ({MODEL}) ---")
    print(f"Latency: {elapsed:.2f}s")
    print(f"Stop reason: {response.stop_reason}")
    print(f"Input tokens: {response.usage.input_tokens}  Output tokens: {response.usage.output_tokens}")
    print(f"Est. cost: ${input_cost + output_cost:.6f}")
    print(f"Response:\n{text}")


if __name__ == "__main__":
    main()
