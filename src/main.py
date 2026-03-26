from __future__ import annotations

import argparse
import asyncio
import json

from runtime.logging_utils import configure_logging
from tools.search_news import SearchNewsTool


async def _run(query: str, max_items: int) -> None:
    tool = SearchNewsTool(timeout_seconds=8.0, max_attempts=3)
    result = await tool.run({"query": query, "max_items": max_items})
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the search_news tool.")
    parser.add_argument("query", help="News query, for example: 宁德时代 A股")
    parser.add_argument("--max-items", type=int, default=5, help="Maximum number of news items.")
    args = parser.parse_args()

    configure_logging()
    asyncio.run(_run(query=args.query, max_items=args.max_items))


if __name__ == "__main__":
    main()
