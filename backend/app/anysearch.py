"""可配置的 MCP 公开检索适配器。"""

import asyncio
import ast
import re
from datetime import datetime, timezone
from pydantic import BaseModel, ConfigDict, Field

from langchain_mcp_adapters.client import MultiServerMCPClient

class PublicSearchError(Exception):
    pass


class PublicSearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=500)
    url: str = Field(pattern=r"^https?://")
    text: str = Field(default="", max_length=12000)
    published_at: str | None = None


async def _search(
    query: str,
    api_key: str | None,
    endpoint: str | None,
    tool_name: str,
) -> list[dict]:
    if not api_key:
        raise PublicSearchError("未配置公开检索 Key")
    if not endpoint:
        raise PublicSearchError("未配置公开检索地址")
    client = MultiServerMCPClient(
        {
            "public_search": {
                "transport": "http",
                "url": endpoint,
                "headers": {
                    "Authorization": f"Bearer {api_key}",
                },
            }
        }
    )
    tools = await client.get_tools()
    search_tool = next((tool for tool in tools if tool.name == tool_name), None)
    if search_tool is None:
        raise PublicSearchError(f"联网工具未提供 {tool_name} 工具")
    result = await search_tool.ainvoke({"query": query, "max_results": 5})
    content = getattr(result, "structuredContent", None) or (result.content if hasattr(result, "content") else result)
    direct_items = content.get("results") if isinstance(content, dict) else content
    if isinstance(direct_items, list) and any(isinstance(item, dict) and item.get("url") for item in direct_items):
        results = []
        for item in direct_items[:5]:
            try:
                results.append(PublicSearchResult(
                    title=str(item.get("title") or item.get("name") or "公开来源"),
                    url=str(item["url"]),
                    text=str(item.get("text") or item.get("snippet") or item.get("description") or ""),
                    published_at=item.get("published_at") or item.get("publishedAt"),
                ).model_dump())
            except (KeyError, ValueError):
                continue
        return results
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
            results.append(PublicSearchResult(title=title.strip(), url=url.rstrip(".,)"), text=body.strip(), published_at=published_at).model_dump())
        except ValueError:
            continue
    if text.strip() and not matches:
        raise PublicSearchError("联网工具返回格式无法解析")
    return results


def search(
    query: str,
    *,
    api_key: str | None,
    endpoint: str | None,
    tool_name: str = "search",
    timeout_seconds: float | None = None,
) -> list[dict]:
    try:
        operation = _search(query, api_key, endpoint, tool_name)
        if timeout_seconds is not None:
            operation = asyncio.wait_for(operation, timeout_seconds)
        return asyncio.run(operation)
    except asyncio.TimeoutError as exc:
        raise PublicSearchError("公开检索查询超时") from exc
    except (PublicSearchError, RuntimeError, ValueError, OSError) as exc:
        if isinstance(exc, PublicSearchError):
            raise
        raise PublicSearchError(f"公开检索查询失败：{exc}") from exc
    except Exception as exc:
        # MCP/client implementations expose different transport exceptions;
        # normalize them here so callers can consistently classify a public
        # search failure instead of treating it as an unknown tool error.
        raise PublicSearchError("公开检索查询失败") from exc
