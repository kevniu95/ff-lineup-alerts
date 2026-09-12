"""
LLM connectivity spike (OpenAI) -- see docs/build-plan.md step 1.

Throwaway: one prompt in, one response out. Same purpose as
spike_llm_claude.py, run against OpenAI so we can compare cost/latency/
response shape between providers before committing to one for step 5.

Run: .venv/bin/python scripts/spike_llm_openai.py
"""
import os
import time
from pathlib import Path

from openai import OpenAI

MODEL = "gpt-5.6-luna"
PRICE_PER_MTOK = {"input": 0.20, "output": 1.20}


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

    client = OpenAI()  # reads OPENAI_API_KEY

    prompt = (
        "I have Christian McCaffrey and Rachaad White on my bench, and my "
        "flex spot is empty this week. Who should I start in flex?"
    )

    start = time.monotonic()
    response = client.chat.completions.create(
        model=MODEL,
        max_completion_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    elapsed = time.monotonic() - start

    text = response.choices[0].message.content
    usage = response.usage
    input_cost = usage.prompt_tokens / 1_000_000 * PRICE_PER_MTOK["input"]
    output_cost = usage.completion_tokens / 1_000_000 * PRICE_PER_MTOK["output"]

    print(f"--- OpenAI ({MODEL}) ---")
    print(f"Latency: {elapsed:.2f}s")
    print(f"Finish reason: {response.choices[0].finish_reason}")
    print(f"Input tokens: {usage.prompt_tokens}  Output tokens: {usage.completion_tokens}")
    print(f"Est. cost: ${input_cost + output_cost:.6f}")
    print(f"Response:\n{text}")


if __name__ == "__main__":
    main()
