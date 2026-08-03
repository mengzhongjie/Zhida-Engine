"""公开网页导入：受限抓取、正文提取与预览。

仅处理用户明确提供的公开 http(s) 链接，不使用 Cookie、Token 或浏览器自动化。
"""

import asyncio
import ipaddress
import re
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup

try:
    import trafilatura
except ImportError:  # 兼容旧安装；正式安装 requirements 后自动启用正文去噪。
    trafilatura = None


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


def _normalize_content(text: str) -> str:
    """压缩空白、去除重复行，保持适合后续切分和检索的正文结构。"""
    lines, seen = [], set()
    for line in (item.strip() for item in text.splitlines()):
        if len(line) < 2 or line in seen:
            continue
        seen.add(line)
        lines.append(line)
    return "\n\n".join(lines)


def _replace_markdown_images(text: str, url: str) -> str:
    """将 trafilatura 输出的 Markdown 图片转为既有视觉处理占位标记。"""
    count = 0

    def replace(match: re.Match) -> str:
        nonlocal count
        count += 1
        alt, source = match.groups()
        return f"\n[图片 {count}：说明={alt.strip() or '未提供'}；链接={urljoin(url, source.strip())}]\n"

    return re.sub(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+[^)]*)?\)", replace, text)


def _extract_with_trafilatura(html: str, url: str) -> str:
    """使用成熟正文提取规则过滤模板噪声；失败时由旧解析器兜底。"""
    if trafilatura is None:
        return ""
    extracted = trafilatura.extract(
        html,
        output_format="markdown",
        include_links=True,
        include_images=True,
        include_tables=True,
        favor_precision=True,
        deduplicate=True,
    )
    if not extracted:
        return ""
    return _normalize_content(_replace_markdown_images(extracted, url))


def _extract_with_bs4(html: str, url: str) -> str:
    """当通用正文提取失败时保留原有的轻量解析兜底。"""
    soup = BeautifulSoup(html, "lxml")
    for node in soup(["script", "style", "noscript", "iframe", "svg", "nav", "footer", "header", "aside", "form"]):
        node.decompose()
    main = soup.find("article") or soup.find("main") or soup.find(attrs={"role": "main"}) or soup.body or soup
    # 纯文本模型无法读取图片像素，但保留网页提供的 alt、标题和原图链接，供重写时结合上下文说明。
    for index, image in enumerate(main.find_all("img"), start=1):
        alt = (image.get("alt") or image.get("title") or "").strip()
        source = image.get("src") or image.get("data-src") or ""
        if not alt and not source:
            image.decompose()
            continue
        image.replace_with(f"\n[图片 {index}：说明={alt or '未提供'}；链接={urljoin(url, source) if source else '未提供'}]\n")
    content = _normalize_content(main.get_text("\n", strip=True))
    return content


def _append_missing_html_images(content: str, html: str, url: str) -> str:
    """通用正文提取器漏掉图片时，从原始正文容器回补图片标记。"""
    known_urls = set(re.findall(r"；链接=(.*?)\]", content))
    count = len(re.findall(r"\[图片 \d+：", content))
    soup = BeautifulSoup(html, "lxml")
    main = soup.find("article") or soup.find("main") or soup.find(attrs={"role": "main"}) or soup.body or soup
    markers: list[str] = []
    for image in main.find_all("img"):
        source = image.get("src") or image.get("data-src") or image.get("data-original") or ""
        if not source:
            continue
        image_url = urljoin(url, source)
        if image_url in known_urls:
            continue
        known_urls.add(image_url)
        count += 1
        alt = (image.get("alt") or image.get("title") or "").strip() or "未提供"
        markers.append(f"[图片 {count}：说明={alt}；链接={image_url}]")
    return content if not markers else f"{content}\n\n## 页面图片\n\n" + "\n\n".join(markers)


def _extract_html(html: str, url: str) -> WebPage:
    soup = BeautifulSoup(html, "lxml")
    title = (soup.title.get_text(" ", strip=True) if soup.title else "") or urlparse(url).hostname or "网页资料"
    # 优先使用 trafilatura 的正文密度与模板过滤规则；正文过短时才退回旧解析。
    content = _extract_with_trafilatura(html, url)
    if len(content) < 100:
        content = _extract_with_bs4(html, url)
    else:
        content = _append_missing_html_images(content, html, url)
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
