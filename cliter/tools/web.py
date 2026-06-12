"""Web search tool — DuckDuckGo (no API key needed)."""
import httpx
import re
from cliter.tools.base import BaseTool

class WebSearchTool(BaseTool):
    name = "web_search"
    description = "Search the web using DuckDuckGo. Returns top results."
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "max_results": {"type": "integer", "description": "Max results (default 5)", "default": 5},
        },
        "required": ["query"],
    }

    async def execute(self, query: str, max_results: int = 5, **kw) -> str:
        try:
            # DuckDuckGo HTML lite (no API key)
            async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
                resp = await client.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": query},
                    headers={"User-Agent": "Mozilla/5.0"}
                )
                resp.raise_for_status()
                html = resp.text

            # simple parse
            results = []
            # find result links
            for m in re.finditer(r'<a rel="nofollow" class="result__a" href="([^"]+)">(.+?)</a>', html):
                url = m.group(1)
                title = re.sub(r"<[^>]+>", "", m.group(2))
                results.append(f"- {title}\n  {url}")
                if len(results) >= max_results:
                    break

            if not results:
                return "No results found."
            return "\n".join(results)
        except Exception as e:
            return f"Search error: {e}"
