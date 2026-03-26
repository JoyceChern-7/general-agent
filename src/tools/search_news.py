from __future__ import annotations

import asyncio
import logging
import time
import uuid
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator

LOGGER = logging.getLogger(__name__)
RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


class SearchNewsInput(BaseModel):
    query: str = Field(min_length=2, max_length=80, description="News search query.")
    max_items: int = Field(default=5, ge=1, le=10, description="Maximum items to return.")
    language: str = Field(default="zh-CN", description="Feed language.")
    region: str = Field(default="CN", min_length=2, max_length=2, description="Market region.")

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("query cannot be empty")
        return normalized

    @field_validator("region")
    @classmethod
    def normalize_region(cls, value: str) -> str:
        return value.upper()


class NewsItem(BaseModel):
    title: str
    link: str
    source: str | None = None
    published_at: str | None = None


class SearchNewsData(BaseModel):
    query: str
    source_feed: str
    total_found: int
    items: list[NewsItem]


class ToolError(BaseModel):
    error_type: str
    message: str
    retryable: bool


class SearchNewsResult(BaseModel):
    tool_name: str
    trace_id: str
    success: bool
    data: SearchNewsData | None = None
    error: ToolError | None = None


class RetryableHTTPError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class SearchNewsTool:
    name = "search_news"
    description = "Search public news RSS feeds and return structured articles."

    def __init__(
        self,
        timeout_seconds: float = 8.0,
        max_attempts: int = 3,
        backoff_base_seconds: float = 0.5,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.backoff_base_seconds = backoff_base_seconds
        self.transport = transport
        self.http2_enabled = self._detect_http2_support()

    async def run(self, raw_input: dict[str, Any], trace_id: str | None = None) -> SearchNewsResult:
        trace_id = trace_id or str(uuid.uuid4())

        try:
            validated_input = SearchNewsInput.model_validate(raw_input)
        except ValidationError as exc:
            LOGGER.warning(
                "search_news.validation_failed",
                extra={
                    "trace_id": trace_id,
                    "tool_name": self.name,
                    "error_type": "validation_error",
                },
                exc_info=exc,
            )
            return SearchNewsResult(
                tool_name=self.name,
                trace_id=trace_id,
                success=False,
                error=ToolError(
                    error_type="validation_error",
                    message=str(exc),
                    retryable=False,
                ),
            )

        LOGGER.info(
            "search_news.started",
            extra={
                "trace_id": trace_id,
                "tool_name": self.name,
                "query": validated_input.query,
            },
        )

        started_at = time.perf_counter()

        try:
            data = await self._fetch_with_retry(validated_input, trace_id)
        except Exception as exc:  # noqa: BLE001
            latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
            tool_error = self._map_error(exc)
            LOGGER.error(
                "search_news.failed",
                extra={
                    "trace_id": trace_id,
                    "tool_name": self.name,
                    "query": validated_input.query,
                    "latency_ms": latency_ms,
                    "error_type": tool_error.error_type,
                },
                exc_info=exc,
            )
            return SearchNewsResult(
                tool_name=self.name,
                trace_id=trace_id,
                success=False,
                error=tool_error,
            )

        latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
        LOGGER.info(
            "search_news.finished",
            extra={
                "trace_id": trace_id,
                "tool_name": self.name,
                "query": validated_input.query,
                "latency_ms": latency_ms,
            },
        )

        return SearchNewsResult(
            tool_name=self.name,
            trace_id=trace_id,
            success=True,
            data=data,
        )

    async def _fetch_with_retry(self, tool_input: SearchNewsInput, trace_id: str) -> SearchNewsData:
        owned_client = None

        if self.transport is not None:
            client = httpx.AsyncClient(
                timeout=self._build_timeout(),
                headers=self._default_headers(),
                follow_redirects=True,
                http2=self.http2_enabled,
                transport=self.transport,
            )
            owned_client = client
        else:
            client = httpx.AsyncClient(
                timeout=self._build_timeout(),
                headers=self._default_headers(),
                follow_redirects=True,
                http2=self.http2_enabled,
            )
            owned_client = client

        try:
            for attempt in range(1, self.max_attempts + 1):
                try:
                    response = await client.get(self._build_feed_url(tool_input))

                    if response.status_code in RETRYABLE_STATUS_CODES:
                        raise RetryableHTTPError(
                            status_code=response.status_code,
                            message=f"retryable HTTP status {response.status_code}",
                        )

                    response.raise_for_status()
                    items = self._parse_rss(response.text, limit=tool_input.max_items)

                    return SearchNewsData(
                        query=tool_input.query,
                        source_feed="google_news_rss",
                        total_found=len(items),
                        items=items,
                    )
                except (httpx.TimeoutException, httpx.NetworkError, RetryableHTTPError) as exc:
                    should_retry = attempt < self.max_attempts
                    status_code = getattr(exc, "status_code", None)
                    LOGGER.warning(
                        "search_news.retryable_error",
                        extra={
                            "trace_id": trace_id,
                            "tool_name": self.name,
                            "query": tool_input.query,
                            "attempt": attempt,
                            "status_code": status_code,
                            "error_type": type(exc).__name__,
                        },
                    )
                    if not should_retry:
                        raise
                    await asyncio.sleep(self.backoff_base_seconds * (2 ** (attempt - 1)))
                except httpx.HTTPStatusError:
                    raise
        finally:
            if owned_client is not None:
                await owned_client.aclose()

        raise RuntimeError("unreachable")

    def _build_feed_url(self, tool_input: SearchNewsInput) -> str:
        encoded_query = quote(tool_input.query)
        return (
            "https://news.google.com/rss/search"
            f"?q={encoded_query}&hl={tool_input.language}"
            f"&gl={tool_input.region}&ceid={tool_input.region}:zh-Hans"
        )

    def _build_timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            connect=self.timeout_seconds,
            read=self.timeout_seconds,
            write=self.timeout_seconds,
            pool=self.timeout_seconds,
        )

    def _default_headers(self) -> dict[str, str]:
        return {
            "User-Agent": "Mozilla/5.0 (compatible; TickAgent/0.1)",
        }

    def _detect_http2_support(self) -> bool:
        try:
            import h2  # noqa: F401
        except ImportError:
            return False
        return True

    def _parse_rss(self, xml_text: str, limit: int) -> list[NewsItem]:
        root = ET.fromstring(xml_text)
        parsed_items: list[NewsItem] = []

        for item in root.findall("./channel/item"):
            if len(parsed_items) >= limit:
                break

            title = item.findtext("title", default="").strip()
            link = item.findtext("link", default="").strip()
            pub_date = item.findtext("pubDate", default="").strip() or None
            source_element = item.find("source")
            source = (
                source_element.text.strip()
                if source_element is not None and source_element.text
                else None
            )

            if not title or not link:
                continue

            parsed_items.append(
                NewsItem(
                    title=title,
                    link=link,
                    source=source,
                    published_at=pub_date,
                )
            )

        return parsed_items

    def _map_error(self, exc: Exception) -> ToolError:
        if isinstance(exc, RetryableHTTPError):
            return ToolError(
                error_type="retryable_http_error",
                message=str(exc),
                retryable=True,
            )

        if isinstance(exc, httpx.TimeoutException):
            return ToolError(
                error_type="timeout_error",
                message=str(exc),
                retryable=True,
            )

        if isinstance(exc, httpx.NetworkError):
            return ToolError(
                error_type="network_error",
                message=str(exc),
                retryable=True,
            )

        if isinstance(exc, httpx.HTTPStatusError):
            return ToolError(
                error_type="http_status_error",
                message=f"non-retryable HTTP status {exc.response.status_code}",
                retryable=False,
            )

        if isinstance(exc, ET.ParseError):
            return ToolError(
                error_type="parse_error",
                message=str(exc),
                retryable=False,
            )

        return ToolError(
            error_type="unknown_error",
            message=str(exc),
            retryable=False,
        )
