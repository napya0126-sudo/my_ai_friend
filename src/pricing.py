"""Pricing constants and helpers. All prices in USD."""

JPY_PER_USD = 150  # rough conversion for display

# Per million tokens
ANTHROPIC_PRICES = {
    "claude-sonnet-4-6":      {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5-20251001": {"input": 1.00, "output":  5.00},
}

# OpenRouter — input/output usually similar
OPENROUTER_PRICES = {
    "gryphe/mythomax-l2-13b":              {"input": 0.18, "output": 0.18},
    "mistralai/mistral-small-3.1-24b-instruct": {"input": 0.10, "output": 0.10},
}

# Per image
FAL_PRICE_PER_IMAGE = 0.025

# Tavily: first 1000/month free, then $0.008 per call
TAVILY_FREE_MONTHLY = 1000
TAVILY_OVER_PRICE   = 0.008


def claude_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    p = ANTHROPIC_PRICES.get(model, {"input": 3.00, "output": 15.00})
    return (input_tokens * p["input"] + output_tokens * p["output"]) / 1_000_000


def openrouter_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    p = OPENROUTER_PRICES.get(model, {"input": 0.20, "output": 0.20})
    return (input_tokens * p["input"] + output_tokens * p["output"]) / 1_000_000


def fal_cost(num_images: int) -> float:
    return num_images * FAL_PRICE_PER_IMAGE


def tavily_cost(month_count: int) -> float:
    """Cost for a single Tavily call given current count this month (after this call)."""
    if month_count <= TAVILY_FREE_MONTHLY:
        return 0.0
    return TAVILY_OVER_PRICE


def usd_to_jpy(usd: float) -> float:
    return usd * JPY_PER_USD
