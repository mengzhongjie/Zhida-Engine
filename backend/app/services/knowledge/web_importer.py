"""公开网页导入：受限抓取、正文提取与预览。

仅处理用户明确提供的公开 http(s) 链接，不使用 Cookie、Token 或浏览器自动化。
"""

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup


MAX_RESPONSE_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 3


@dataclass
class WebPage:
    title: str
    content: str
    url: str


def _is_public_ip(value: str) -> bool:
    ip = ipaddress.ip_address(value)
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified)


async def _validate_public_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("仅支持不含账号信息的公开 http/https 链接")
    if parsed.port not in (None, 80, 443):
        raise ValueError("仅支持标准 HTTP/HTTPS 端口")
    try:
        addresses = await asyncio.to_thread(socket.getaddrinfo, parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
        ips = {item[4][0] for item in addresses}
    except socket.gaierror as exc:
        raise ValueError("无法解析该网站域名") from exc
    if not ips or any(not _is_public_ip(ip) for ip in ips):
        raise ValueError("不允许访问本机、内网或保留地址")
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.params, parsed.query, ""))


def _extract_html(html: str, url: str) -> WebPage:
    soup = BeautifulSoup(html, "lxml")
    for node in soup(["script", "style", "noscript", "iframe", "svg", "nav", "footer", "header", "aside", "form"]):
        node.decompose()
    title = (soup.title.get_text(" ", strip=True) if soup.title else "") or urlparse(url).hostname or "网页资料"
    main = soup.find("article") or soup.find("main") or soup.find(attrs={"role": "main"}) or soup.body or soup
    text = main.get_text("\n", strip=True)
    lines, seen = [], set()
    for line in (item.strip() for item in text.splitlines()):
        if len(line) < 2 or line in seen:
            continue
        seen.add(line)
        lines.append(line)
    content = "\n\n".join(lines)
    if len(content) < 100:
        raise ValueError("未提取到足够的公开正文；该网页可能需要登录、动态渲染或禁止访问")
    return WebPage(title=title[:300], content=content, url=url)


async def fetch_public_page(url: str) -> WebPage:
    """带 SSRF 保护地获取公开网页，并在每次重定向后重新校验目标。"""
    current = await _validate_public_url(url)
    headers = {"User-Agent": "ZhidaEngine/0.1 (+local knowledge import)", "Accept": "text/html,application/xhtml+xml"}
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0), follow_redirects=False, headers=headers) as client:
        for _ in range(MAX_REDIRECTS + 1):
            async with client.stream("GET", current) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("网页重定向缺少目标地址")
                    current = await _validate_public_url(urljoin(current, location))
                    continue
                if response.status_code >= 400:
                    raise ValueError(f"网页返回 HTTP {response.status_code}")
                content_type = response.headers.get("content-type", "").lower()
                if "html" not in content_type:
                    raise ValueError("当前仅支持 HTML 网页链接")
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_RESPONSE_BYTES:
                        raise ValueError("网页内容超过 5MB 限制")
                    chunks.append(chunk)
                return _extract_html(b"".join(chunks).decode(response.encoding or "utf-8", errors="replace"), current)
    raise ValueError("网页重定向次数超过限制")
