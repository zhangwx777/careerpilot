"""AnySearch MCP 搜索源。"""

import asyncio
import ast
import re
from datetime import datetime, timezone

from langchain_mcp_adapters.client import MultiServerMCPClient

from app.config import settings


class AnySearchError(Exception):
    pass


async def _search(query: str) -> list[dict]:
    if not settings.anysearch_api_key:
        raise AnySearchError("未配置 ANYSEARCH_API_KEY")
    client = MultiServerMCPClient(
        {
            "anysearch": {
                "transport": "http",
                "url": "https://api.anysearch.com/mcp",
                "headers": {
                    "Authorization": f"Bearer {settings.anysearch_api_key}",
                    "X-Anysearch-Client": "mcp/1.0.0",
                },
            }
        }
    )
    tools = await client.get_tools()
    search_tool = next((tool for tool in tools if tool.name == "search"), None)
    if search_tool is None:
        raise AnySearchError("AnySearch MCP 未提供 search 工具")
    result = await search_tool.ainvoke({"query": query, "max_results": 5})
    content = result.content if hasattr(result, "content") else result
    if isinstance(content, list):
        text = "\n".join(item.get("text", "") for item in content if isinstance(item, dict))
    else:
        try:
            blocks = ast.literal_eval(str(content))
            text = "\n".join(item.get("text", "") for item in blocks if isinstance(item, dict))
        except (SyntaxError, ValueError):
            text = str(content)
    matches = re.findall(
        r"### \d+\. (?P<title>.+?)\n- \*\*URL\*\*: (?P<url>https?://\S+)\n(?P<body>.*?)(?=\n### |$)",
        text,
        flags=re.DOTALL,
    )
    results = []
    for title, url, body in matches:
        published_at = None
        date_match = re.search(r"date:\s*([A-Z][a-z]{2} \d{1,2}, \d{4})", body)
        if date_match:
            published_at = datetime.strptime(date_match.group(1), "%b %d, %Y").replace(tzinfo=timezone.utc).isoformat()
        results.append({"title": title, "url": url, "text": body.strip(), "published_at": published_at})
    return results


def search(query: str, *, timeout_seconds: float | None = None) -> list[dict]:
    try:
        operation = _search(query)
        if timeout_seconds is not None:
            operation = asyncio.wait_for(operation, timeout_seconds)
        return asyncio.run(operation)
    except asyncio.TimeoutError as exc:
        raise AnySearchError("AnySearch 查询超时") from exc
    except (AnySearchError, RuntimeError, ValueError) as exc:
        if isinstance(exc, AnySearchError):
            raise
        raise AnySearchError(f"AnySearch 查询失败：{exc}") from exc
