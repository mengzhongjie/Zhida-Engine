"""轻量网络检索：默认接入 Tavily，仅在显式启用且 RAG 未命中时调用。"""

from dataclasses import dataclass

import httpx
from loguru import logger

from app.core.config import settings


@dataclass
class WebSearchResult:
    title: str
    url: str
    content: str


class WebSearchService:
    async def search(self, query: str) -> list[WebSearchResult]:
        if not settings.WEB_SEARCH_ENABLED:
            return []
        if settings.WEB_SEARCH_PROVIDER != "tavily":
            logger.warning(f"不支持的网络检索服务: {settings.WEB_SEARCH_PROVIDER}")
            return []
        if not settings.WEB_SEARCH_API_KEY:
            logger.warning("网络检索已启用但未配置 Tavily API Key")
            return []
        try:
            async with httpx.AsyncClient(timeout=12.0) as client:
                response = await client.post("https://api.tavily.com/search", json={
                    "api_key": settings.WEB_SEARCH_API_KEY,
                    "query": query,
                    "search_depth": "basic",
                    "max_results": settings.WEB_SEARCH_MAX_RESULTS,
                    "include_answer": False,
                })
                response.raise_for_status()
            return [WebSearchResult(title=item.get("title", "网络来源"), url=item.get("url", ""), content=item.get("content", "")) for item in response.json().get("results", []) if item.get("content")]
        except Exception as exc:
            logger.warning(f"网络检索失败: {exc}")
            return []


web_search_service = WebSearchService()
