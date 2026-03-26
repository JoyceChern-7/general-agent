from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from tools.search_news import SearchNewsTool  # noqa: E402


def test_search_news_success() -> None:
    xml_payload = """
    <rss>
      <channel>
        <item>
          <title>宁德时代发布新电池技术</title>
          <link>https://example.com/article-1</link>
          <pubDate>Wed, 26 Mar 2026 10:00:00 GMT</pubDate>
          <source>示例财经</source>
        </item>
        <item>
          <title>动力电池板块盘中走弱</title>
          <link>https://example.com/article-2</link>
          <pubDate>Wed, 26 Mar 2026 11:00:00 GMT</pubDate>
          <source>示例新闻</source>
        </item>
      </channel>
    </rss>
    """

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=xml_payload)

    tool = SearchNewsTool(transport=httpx.MockTransport(handler))
    result = asyncio.run(tool.run({"query": "宁德时代 A股", "max_items": 2}, trace_id="test-trace"))

    assert result.success is True
    assert result.data is not None
    assert result.data.total_found == 2
    assert result.data.items[0].title == "宁德时代发布新电池技术"


def test_search_news_validation_error() -> None:
    tool = SearchNewsTool()
    result = asyncio.run(tool.run({"query": " "} , trace_id="test-trace"))

    assert result.success is False
    assert result.error is not None
    assert result.error.error_type == "validation_error"


def test_search_news_retries_before_success() -> None:
    attempts = {"count": 0}
    xml_payload = """
    <rss>
      <channel>
        <item>
          <title>市场情绪回暖</title>
          <link>https://example.com/article-3</link>
          <pubDate>Wed, 26 Mar 2026 12:00:00 GMT</pubDate>
          <source>示例源</source>
        </item>
      </channel>
    </rss>
    """

    async def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] < 3:
            return httpx.Response(503, text="temporary unavailable")
        return httpx.Response(200, text=xml_payload)

    tool = SearchNewsTool(
        transport=httpx.MockTransport(handler),
        backoff_base_seconds=0.01,
    )
    result = asyncio.run(tool.run({"query": "上证指数"}))

    assert attempts["count"] == 3
    assert result.success is True
