import logging
import httpx
from config.settings import (
    OPENROUTER_API_KEY, OPENROUTER_BASE_URL,
    ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL, ANTHROPIC_VERSION,
    MODEL_NSFW, MODEL_CHAT,
)
from src.db import log_usage
from src.pricing import claude_cost, openrouter_cost

logger = logging.getLogger(__name__)


SEARCH_TOOL = {
    "name": "search_web",
    "description": (
        "Search the live web for real, current information and return URLs. "
        "Use this ONLY when:\n"
        "- The user asks a factual question about a specific named entity "
        "(company, product, paper, person, technology)\n"
        "- You're about to mention a specific real-world reference and want a real URL\n"
        "- The user asks about recent news or events\n"
        "DO NOT use for: general chit-chat, emotional conversation, "
        "discussion of opinions, your own life details, or hypotheticals."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Focused search query — be specific, 3-8 words ideal",
            }
        },
        "required": ["query"],
    },
}


def _split_system(messages: list[dict]) -> tuple[str, list[dict]]:
    system = ""
    turns = []
    for m in messages:
        if m["role"] == "system":
            system = m["content"]
        else:
            turns.append(m)
    return system, turns


async def chat_claude(
    messages: list[dict],
    max_tokens: int = 1024,
    with_tools: bool = False,
    model: str | None = None,
) -> str:
    """Chat via Anthropic API. If with_tools=True, runs a tool-use loop."""
    system, turns = _split_system(messages)
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": ANTHROPIC_VERSION,
        "Content-Type": "application/json",
    }

    for _ in range(5):  # safety cap on tool-use rounds
        payload = {
            "model": model or MODEL_CHAT,
            "system": system,
            "messages": turns,
            "max_tokens": max_tokens,
        }
        if with_tools:
            payload["tools"] = [SEARCH_TOOL]

        async with httpx.AsyncClient(timeout=90) as client:
            r = await client.post(
                f"{ANTHROPIC_BASE_URL}/messages", headers=headers, json=payload
            )
            r.raise_for_status()
            data = r.json()

        usage = data.get("usage", {})
        in_tok  = usage.get("input_tokens", 0)
        out_tok = usage.get("output_tokens", 0)
        used_model = payload["model"]
        log_usage(
            service="claude", model=used_model,
            input_tokens=in_tok, output_tokens=out_tok,
            cost_usd=claude_cost(used_model, in_tok, out_tok),
        )

        if data.get("stop_reason") != "tool_use":
            text_parts = [b["text"] for b in data["content"] if b["type"] == "text"]
            return "\n".join(text_parts).strip()

        # Append assistant turn (with tool_use blocks) so next call sees it
        turns.append({"role": "assistant", "content": data["content"]})

        # Execute each tool_use block
        from src.search import tavily_search, format_search_results

        tool_results = []
        for block in data["content"]:
            if block["type"] != "tool_use":
                continue
            if block["name"] == "search_web":
                query = block["input"].get("query", "")
                logger.info(f"[search_web] {query}")
                try:
                    raw = await tavily_search(query)
                    result_text = format_search_results(raw)
                except Exception as e:
                    logger.warning(f"Tavily search failed: {e}")
                    result_text = f"Search failed: {e}"
            else:
                result_text = f"Unknown tool: {block['name']}"
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block["id"],
                "content": result_text,
            })

        turns.append({"role": "user", "content": tool_results})

    return "（検索ループの上限に到達しました）"


async def chat_openrouter(
    messages: list[dict],
    model: str,
    max_tokens: int = 1024,
    stop: list[str] | None = None,
) -> str:
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/naoya/myaifriend",
        "X-Title": "MyAIFriend",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.85,
        "max_tokens": max_tokens,
    }
    if stop:
        payload["stop"] = stop

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            f"{OPENROUTER_BASE_URL}/chat/completions",
            headers=headers,
            json=payload,
        )
        r.raise_for_status()
        data = r.json()

    usage = data.get("usage", {})
    in_tok  = usage.get("prompt_tokens", 0)
    out_tok = usage.get("completion_tokens", 0)
    log_usage(
        service="openrouter", model=model,
        input_tokens=in_tok, output_tokens=out_tok,
        cost_usd=openrouter_cost(model, in_tok, out_tok),
    )

    return data["choices"][0]["message"]["content"]
