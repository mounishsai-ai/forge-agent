"""Estimated cost per model, in USD per 1M tokens. Thinking tokens are billed as output.

Gemini 3.8 / 3.7 Flash: introductory rate through 2026-12-31 ($1.50 / $7.50 list price from 2027).
Models not listed here are counted as $0, so add a price before trusting /cost for them.
"""
PRICES = {
    "gemini-3.8-flash": {"input": 0.75, "output": 3.75},
    "gemini-3.7-flash": {"input": 0.75, "output": 3.75},
    # From third-party price trackers (Sept 2026), not yet confirmed on Google's pricing page:
    "gemini-3.5-flash": {"input": 1.50, "output": 9.00},
    "gemini-3.1-pro-preview": {"input": 2.00, "output": 12.00},   # prompts <= 200K tokens
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
}


def cost(model: str, usage) -> float | None:
    price = PRICES.get(model)
    if price is None:
        return None
    output = usage.output_tokens + usage.thinking_tokens
    return round((usage.input_tokens * price["input"] + output * price["output"]) / 1_000_000, 6)
