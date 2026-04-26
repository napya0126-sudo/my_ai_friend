import logging
import time
from datetime import datetime
import httpx
from config.settings import TAVILY_API_KEY
from src.db import log_usage, _conn
from src.pricing import tavily_cost

logger = logging.getLogger(__name__)


def _tavily_count_this_month() -> int:
    start = int(datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp())
    with _conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(count),0) FROM usage WHERE service='tavily' AND ts >= ?",
            (start,),
        ).fetchone()
    return row[0] or 0


async def tavily_search(query: str, max_results: int = 5) -> dict:
    """Hit Tavily search API. Returns the raw JSON response."""
    payload = {
        "api_key": TAVILY_API_KEY,
        "query": query,
        "max_results": max_results,
        "search_depth": "basic",
        "include_answer": False,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post("https://api.tavily.com/search", json=payload)
        r.raise_for_status()
        result = r.json()

    new_count = _tavily_count_this_month() + 1
    log_usage(service="tavily", count=1, cost_usd=tavily_cost(new_count))
    return result


def format_search_results(data: dict) -> str:
    """Compact text representation of Tavily results for tool_result content."""
    results = data.get("results", [])
    if not results:
        return "No results found."
    lines = []
    for i, r in enumerate(results[:5], 1):
        title   = r.get("title", "").strip()
        snippet = r.get("content", "").strip()[:240]
        url     = r.get("url", "").strip()
        lines.append(f"{i}. {title}\n   {snippet}\n   URL: {url}")
    return "\n\n".join(lines)
