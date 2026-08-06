"""
智答引擎（ZhiDa Engine）—— 安全中间件

本地桌面应用的安全防护：
- 请求体大小限制
- 安全响应头
- 文件上传校验
"""

from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from loguru import logger

from app.core.config import settings
from app.core.security import is_trusted_proxy_request


class SecurityMiddleware(BaseHTTPMiddleware):
    """
    安全中间件 —— 请求体限制 + 安全响应头

    安全策略侧重：
    1. 添加安全响应头防止 MIME 嗅探、点击劫持等
    2. 请求体大小限制
    """

    # 安全响应头
    SECURITY_HEADERS = {
        "X-Content-Type-Options": "nosniff",           # 禁止 MIME 类型嗅探
        "X-Frame-Options": "DENY",                     # 禁止被嵌入 iframe
        "X-XSS-Protection": "1; mode=block",           # 启用 XSS 过滤器
        "Referrer-Policy": "no-referrer",               # 不发送 Referrer
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",  # 禁用敏感 API
        "Server": "",                                   # 隐藏服务器信息
    }

    @staticmethod
    def _is_local_request(request: Request) -> bool:
        host = (request.url.hostname or "").lower()
        return host in {"localhost", "127.0.0.1", "::1"}

    @staticmethod
    def _is_https(request: Request) -> bool:
        forwarded = ""
        if is_trusted_proxy_request(request):
            forwarded = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip().lower()
        return request.url.scheme == "https" or forwarded == "https"

    async def dispatch(self, request: Request, call_next):
        is_https = self._is_https(request)

        # 公网用户端和管理端只接受 HTTPS；回环地址保留本地开发体验。
        # 反向代理必须传递 X-Forwarded-Proto，README 已提供对应配置。
        if settings.AUTH_REQUIRE_HTTPS and not self._is_local_request(request) and not is_https:
            return JSONResponse(status_code=426, content={"detail": "公网访问必须使用 HTTPS"})

        # 1. 请求体大小限制
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                size_mb = int(content_length) / (1024 * 1024)
                max_size = settings.MAX_REQUEST_SIZE_MB

                # 文件上传接口允许更大的请求体
                if "/upload" in request.url.path:
                    max_size = settings.MAX_UPLOAD_SIZE_MB

                if size_mb > max_size:
                    raise HTTPException(
                        status_code=413,
                        detail=f"请求体过大（{size_mb:.1f}MB > {max_size}MB）",
                    )
            except ValueError:
                pass

        # 2. 处理请求
        response = await call_next(request)

        # 3. 添加安全响应头
        if isinstance(response, Response):
            for header_name, header_value in self.SECURITY_HEADERS.items():
                if header_name not in response.headers:
                    response.headers[header_name] = header_value
            if request.url.path.startswith("/api/"):
                response.headers.setdefault("Cache-Control", "no-store")
            # 浏览器一旦通过 HTTPS 访问过公网域名，后续请求不允许降级回 HTTP。
            if is_https and not self._is_local_request(request):
                response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")

        return response
