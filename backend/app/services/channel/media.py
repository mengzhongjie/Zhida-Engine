"""私信图片的安全下载与事件解析工具。原图只在内存中短暂存在。"""
import base64
import ipaddress
import json
from urllib.parse import quote, urlparse
import re

import httpx

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGES = 3
ALLOWED_HOST_SUFFIXES = (
    "qq.com", "qq.com.cn", "nt.qq.com.cn", "qpic.cn", "qlogo.cn",
    "feishu.cn", "larksuite.com",
)
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


def _safe_host(host: str) -> bool:
    host = (host or "").lower().rstrip(".")
    if not host or host in {"localhost", "127.0.0.1", "::1"}:
        return False
    try:
        ip = ipaddress.ip_address(host)
        return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved)
    except ValueError:
        return any(host == suffix or host.endswith("." + suffix) for suffix in ALLOWED_HOST_SUFFIXES)


async def download_image(url: str, *, headers: dict[str, str] | None = None) -> str:
    """下载官方媒体 URL 并返回 data URI；拒绝任意外部/内网地址。"""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not _safe_host(parsed.hostname or ""):
        raise ValueError("图片来源不在允许的 HTTPS 域名范围内")
    async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=4.0), follow_redirects=False) as client:
        current_url = url
        response = None
        raw = b""
        for _ in range(3):
            parsed = urlparse(current_url)
            if parsed.scheme != "https" or not _safe_host(parsed.hostname or ""):
                raise ValueError("图片重定向目标不在允许的 HTTPS 域名范围内")
            async with client.stream("GET", current_url, headers=headers or {}, follow_redirects=False) as candidate:
                response = candidate
                if candidate.status_code in {301, 302, 303, 307, 308}:
                    current_url = candidate.headers.get("location", "")
                    if not current_url:
                        raise ValueError("图片重定向缺少目标地址")
                    continue
                if candidate.is_error:
                    # 飞书会在 400/403 中返回具体的 code/msg；仅保留截断后的错误正文，禁止记录 Token。
                    detail = (await candidate.aread())[:600].decode("utf-8", errors="replace")
                    raise ValueError(f"媒体接口 HTTP {candidate.status_code}: {detail}")
                media_type = (candidate.headers.get("content-type") or "").split(";", 1)[0].lower()
                if media_type not in ALLOWED_TYPES:
                    raise ValueError("不支持的图片格式")
                length = int(candidate.headers.get("content-length") or 0)
                if length > MAX_IMAGE_BYTES:
                    raise ValueError("图片超过 10MB 限制")
                chunks: list[bytes] = []
                total = 0
                async for chunk in candidate.aiter_bytes(64 * 1024):
                    total += len(chunk)
                    if total > MAX_IMAGE_BYTES:
                        raise ValueError("图片超过 10MB 限制")
                    chunks.append(chunk)
                raw = b"".join(chunks)
                break
        if response is None or response.is_redirect:
            raise ValueError("图片重定向次数过多")
    # 检查常见魔数，避免仅凭 Content-Type 信任外部响应。
    if not (raw.startswith(b"\x89PNG") or raw.startswith(b"\xff\xd8\xff") or raw.startswith(b"RIFF") or raw.startswith(b"GIF8")):
        raise ValueError("图片内容校验失败")
    return f"data:{media_type};base64,{base64.b64encode(raw).decode('ascii')}"


async def download_feishu_image(message_id: str, image_key: str, token: str) -> str:
    """下载用户消息中的图片资源；不能使用仅适用于机器人自有图片的 images 接口。"""
    if not token or not token.strip():
        raise ValueError("飞书租户访问令牌为空")
    message_id = (message_id or "").strip()
    image_key = (image_key or "").strip()
    if not message_id or not re.fullmatch(r"[A-Za-z0-9_.:-]{8,300}", message_id):
        raise ValueError("飞书 message_id 格式无效")
    if not image_key or not re.fullmatch(r"[A-Za-z0-9_.:-]{8,300}", image_key):
        raise ValueError(f"飞书 file_key 格式无效（长度={len(image_key)}）")
    return await download_image(
        f"https://open.feishu.cn/open-apis/im/v1/messages/{quote(message_id, safe='')}/resources/{quote(image_key, safe='')}?type=image",
        headers={"Authorization": f"Bearer {token}"},
    )


def qq_image_urls(event: dict) -> list[str]:
    """兼容 QQ 官方事件中 attachments/attachments[].url 的图片结构。"""
    urls: list[str] = []
    for item in event.get("attachments") or []:
        if isinstance(item, dict) and item.get("url"):
            urls.append(str(item["url"]))
    return urls[:MAX_IMAGES]


def feishu_image_keys(message) -> list[str]:
    """从飞书消息 content JSON 提取 image_key；仅在单聊调用。"""
    try:
        body = json.loads(getattr(message, "content", "") or "{}")
    except (TypeError, ValueError):
        return []
    keys: list[str] = []
    if isinstance(body, dict) and body.get("image_key"):
        keys.append(str(body["image_key"]))
    return keys[:MAX_IMAGES]


def feishu_text_content(raw: str) -> str:
    try:
        body = json.loads(raw or "{}")
        if isinstance(body, dict) and isinstance(body.get("text"), str):
            return body["text"]
    except (TypeError, ValueError):
        pass
    return raw or ""
