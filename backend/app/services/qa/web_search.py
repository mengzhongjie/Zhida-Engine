"""轻量网络检索：支持 Tavily、Exa 及免密钥实验通道。"""

from dataclasses import dataclass
from html import unescape
import re
from urllib.parse import parse_qs, unquote, urlparse
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
            logger.info(f"联网检索未执行：功能开关关闭，query={query[:120]}")
            return []
        provider = settings.WEB_SEARCH_PROVIDER
        logger.info(f"开始联网检索：provider={provider}, query={query[:180]}")
        results = await self.search_with_config(
            query, provider, settings.WEB_SEARCH_API_KEY, settings.WEB_SEARCH_MAX_RESULTS
        )
        logger.info(f"联网检索完成：provider={provider}, results={len(results)}, query={query[:120]}")
        return results

    async def search_with_config(
        self, query: str, provider: str, api_key: str, max_results: int, *, raise_errors: bool = False,
    ) -> list[WebSearchResult]:
        try:
            if provider == "tavily":
                return await self._search_tavily(query, api_key, max_results)
            if provider == "exa":
                return await self._search_exa(query, api_key, max_results)
            if provider == "duckduckgo":
                return await self._search_duckduckgo(query, max_results)
            if provider == "bing_rss":
                return await self._search_bing_rss(query, max_results)
            logger.warning(f"不支持的网络检索服务: {provider}")
            return []
        except Exception as exc:
            logger.warning(f"网络检索失败 ({provider}): {type(exc).__name__}: {exc}")
            if raise_errors:
                if isinstance(exc, httpx.HTTPStatusError):
                    detail = exc.response.text[:240].replace("\n", " ")
                    raise RuntimeError(f"{provider} 返回 HTTP {exc.response.status_code}: {detail}") from exc
                raise RuntimeError(f"{provider} 请求失败: {type(exc).__name__}: {exc}") from exc
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

    async def _search_exa(self, query: str, api_key: str, max_results: int) -> list[WebSearchResult]:
        """调用 Exa Search，并直接获取适合 RAG 的网页正文片段。"""
        if not api_key:
            logger.warning("网络检索已启用但未配置 Exa API Key")
            return []
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                "https://api.exa.ai/search",
                headers={"x-api-key": api_key},
                json={
                    "query": query,
                    "numResults": max_results,
                    "contents": {"text": {"maxCharacters": 1600}},
                },
            )
            response.raise_for_status()

        results = []
        for item in response.json().get("results", []):
            text = item.get("text") or "\n".join(item.get("highlights") or [])
            url = item.get("url", "")
            if text and url:
                results.append(WebSearchResult(
                    title=item.get("title") or "网络来源",
                    url=url,
                    content=text,
                ))
        return results

    async def _search_duckduckgo(self, query: str, max_results: int) -> list[WebSearchResult]:
        """DuckDuckGo HTML 搜索，无密钥实验通道；页面结构变动或限流时会安全降级。"""
        async with httpx.AsyncClient(
            timeout=10.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; ZhiDaEngine/0.1)"},
        ) as client:
            response = await client.post(
                "https://html.duckduckgo.com/html/",
                data={"q": query},
            )
            response.raise_for_status()

        # DuckDuckGo 没有稳定的通用 Web Search API；只提取公开 HTML 页中的标题、URL、摘要。
        # 保持解析器无额外依赖，结构变化时返回空结果并由上层正常降级。
        anchors = list(re.finditer(
            r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            response.text,
            flags=re.IGNORECASE | re.DOTALL,
        ))
        results = []
        for index, anchor in enumerate(anchors):
            segment_end = anchors[index + 1].start() if index + 1 < len(anchors) else len(response.text)
            segment = response.text[anchor.end():segment_end]
            snippet_match = re.search(
                r'<(?:a|div)[^>]*class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</(?:a|div)>',
                segment,
                flags=re.IGNORECASE | re.DOTALL,
            )
            title = re.sub(r"<[^>]+>", "", anchor.group(2))
            content = re.sub(r"<[^>]+>", "", snippet_match.group(1)) if snippet_match else title
            url = unescape(anchor.group(1))
            parsed_url = urlparse(url)
            redirect_target = parse_qs(parsed_url.query).get("uddg", [""])[0]
            if redirect_target:
                url = unquote(redirect_target)
            title, content = unescape(title).strip(), unescape(content).strip()
            if title and content and url:
                results.append(WebSearchResult(title=title, url=url, content=content))
            if len(results) >= max_results:
                break
        return results

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
