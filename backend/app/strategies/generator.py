"""
Uses Claude to generate a StrategyConfig from a natural language prompt.
"""

import json
import logging
import os

import anthropic
from app.strategies.models import StrategyConfig

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a quantitative trading strategy designer.

Given a natural language description of a trading strategy, output a single valid JSON object that matches this exact schema:

{
  "name": "string — short strategy name",
  "description": "string — 1-2 sentence description",
  "type": "one of: MOMENTUM, BREAKOUT, MEAN_REVERSION, CUSTOM",
  "parameters": {
    // numeric parameters with defaults, e.g.:
    // "sma_period": 20,
    // "volume_multiplier": 1.5,
    // "atr_period": 14
  },
  "filters": {
    // entry/exit filter conditions, e.g.:
    // "min_price": 5.0,
    // "min_avg_volume": 500000
  },
  "signal_logic": "string — plain English description of the exact entry and exit rules"
}

Rules:
- Output valid JSON only. No markdown, no explanation, no code fences.
- Every numeric parameter must have a concrete default value.
- signal_logic must describe: entry trigger, exit trigger, and any stop-loss rule.
- Be specific — avoid vague terms like "when the stock is bullish".
"""


def generate_strategy(prompt: str) -> StrategyConfig:
    """Call Claude to generate a StrategyConfig from a natural language prompt."""
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    try:
        message = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APITimeoutError as e:
        raise RuntimeError(f"Claude API timed out: {e}") from e
    except anthropic.APIConnectionError as e:
        raise RuntimeError(f"Claude API connection failed: {e}") from e
    except anthropic.APIError as e:
        raise RuntimeError(f"Claude API error: {e}") from e

    raw = message.content[0].text.strip()

    # Strip markdown code fences if Claude added them despite instructions
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Claude returned invalid JSON: {e}\n\nRaw response:\n{raw}") from e

    try:
        return StrategyConfig(**data)
    except Exception as e:
        raise ValueError(
            f"Claude response did not match StrategyConfig schema: {e}\n\nData: {data}"
        ) from e
