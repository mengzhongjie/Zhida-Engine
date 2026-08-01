"""轻量网络检索：支持 Tavily 与无需密钥的 Bing RSS 实验通道。"""

from dataclasses import dataclass
from xml.etree import ElementTree

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
        provider = settings.WEB_SEARCH_PROVIDER
        return await self.search_with_config(
            query, provider, settings.WEB_SEARCH_API_KEY, settings.WEB_SEARCH_MAX_RESULTS
        )

    async def search_with_config(
        self, query: str, provider: str, api_key: str, max_results: int
    ) -> list[WebSearchResult]:
        try:
            if provider == "tavily":
                return await self._search_tavily(query, api_key, max_results)
            if provider == "bing_rss":
                return await self._search_bing_rss(query, max_results)
            logger.warning(f"不支持的网络检索服务: {provider}")
            return []
        except Exception as exc:
            logger.warning(f"网络检索失败 ({provider}): {exc}")
            return []

    async def _search_tavily(self, query: str, api_key: str, max_results: int) -> list[WebSearchResult]:
        if not api_key:
            logger.warning("网络检索已启用但未配置 Tavily API Key")
            return []
        async with httpx.AsyncClient(timeout=12.0) as client:
            response = await client.post("https://api.tavily.com/search", json={
                "api_key": api_key,
                "query": query,
                "search_depth": "basic",
                "max_results": max_results,
                "include_answer": False,
            })
            response.raise_for_status()
        return [
            WebSearchResult(
                title=item.get("title", "网络来源"),
                url=item.get("url", ""),
                content=item.get("content", ""),
            )
            for item in response.json().get("results", [])
            if item.get("content")
        ]

    async def _search_bing_rss(self, query: str, max_results: int) -> list[WebSearchResult]:
        """读取 Bing 公开 RSS；适合个人/非商业试验，正式部署优先 Tavily。"""
        async with httpx.AsyncClient(
            timeout=12.0,
            follow_redirects=True,
            headers={"User-Agent": "ZhiDaEngine/0.1 RSS Reader"},
        ) as client:
            response = await client.get(
                "https://www.bing.com/search",
                params={"format": "rss", "q": query},
            )
            response.raise_for_status()

        root = ElementTree.fromstring(response.content)
        results = []
        for item in root.findall("./channel/item"):
            title = (item.findtext("title") or "网络来源").strip()
            url = (item.findtext("link") or "").strip()
            content = (item.findtext("description") or "").strip()
            if not content or not url:
                continue
            results.append(WebSearchResult(title=title, url=url, content=content))
            if len(results) >= max_results:
                break
        return results


web_search_service = WebSearchService()
