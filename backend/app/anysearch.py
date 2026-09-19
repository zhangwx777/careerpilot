"""AnySearch MCP 搜索源。"""

import asyncio
import ast
import re
from datetime import datetime, timezone
from pydantic import BaseModel, ConfigDict, Field

from langchain_mcp_adapters.client import MultiServerMCPClient

from app.config import settings


class AnySearchError(Exception):
    pass


class AnySearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=500)
    url: str = Field(pattern=r"^https?://")
    text: str = Field(default="", max_length=12000)
    published_at: str | None = None


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
    results: list[dict] = []
    for title, url, body in matches:
        published_at = None
        date_match = re.search(r"date:\s*([A-Z][a-z]{2} \d{1,2}, \d{4})", body)
        if date_match:
            published_at = datetime.strptime(date_match.group(1), "%b %d, %Y").replace(tzinfo=timezone.utc).isoformat()
        try:
            results.append(AnySearchResult(title=title.strip(), url=url.rstrip(".,)"), text=body.strip(), published_at=published_at).model_dump())
        except ValueError:
            continue
    if text.strip() and not matches:
        raise AnySearchError("AnySearch MCP 返回格式无法解析")
    return results


def search(query: str, *, timeout_seconds: float | None = None) -> list[dict]:
    try:
        operation = _search(query)
        if timeout_seconds is not None:
            operation = asyncio.wait_for(operation, timeout_seconds)
        return asyncio.run(operation)
    except asyncio.TimeoutError as exc:
        raise AnySearchError("AnySearch 查询超时") from exc
    except (AnySearchError, RuntimeError, ValueError, OSError) as exc:
        if isinstance(exc, AnySearchError):
            raise
        raise AnySearchError(f"AnySearch 查询失败：{exc}") from exc
    except Exception as exc:
        # MCP/client implementations expose different transport exceptions;
        # normalize them here so callers can consistently classify a public
        # search failure instead of treating it as an unknown tool error.
        raise AnySearchError("AnySearch 查询失败") from exc
