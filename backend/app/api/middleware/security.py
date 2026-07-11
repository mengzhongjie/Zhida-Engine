"""
智答引擎（ZhiDa Engine）—— 安全中间件

本地桌面应用的安全防护：
- 请求来源校验（仅允许 127.0.0.1）
- 请求体大小限制
- 安全响应头
- 文件上传校验
"""

import hashlib
import hmac
import time

from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from loguru import logger

from app.core.config import settings
from app.core.security import validate_local_request


class SecurityMiddleware(BaseHTTPMiddleware):
    """
    安全中间件 —— 请求来源校验 + 安全响应头

    因为是本地桌面应用（非服务端），安全策略侧重：
    1. 确保只有本地请求能访问 API
    2. 添加安全响应头防止 MIME 嗅探、点击劫持等
    3. 请求体大小限制
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
    def _is_valid_miniapp_gateway_request(request: Request) -> bool:
        """允许通过签名校验的小程序网关穿过本地模式限制。

        路由层会再次校验签名并验证邀请码；中间件只用于避免公网请求在
        到达路由前被本地桌面策略误拦截。
        """
        if not (
            request.url.path.startswith("/api/v1/miniapp/")
            or request.url.path == "/api/v1/admin/auth/confirm"
        ):
            return False
        secret = settings.MINIPROGRAM_GATEWAY_SECRET
        openid = request.headers.get("X-Miniapp-Openid", "")
        timestamp = request.headers.get("X-Miniapp-Timestamp", "")
        signature = request.headers.get("X-Miniapp-Signature", "")
        if not secret or not openid or not timestamp or not signature:
            return False
        try:
            timestamp_int = int(timestamp)
        except ValueError:
            return False
        if abs(time.time() - timestamp_int) > settings.MINIPROGRAM_SIGNATURE_TTL_SECONDS:
            return False
        expected = hmac.new(
            secret.encode("utf-8"),
            f"{timestamp}.{openid}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    async def dispatch(self, request: Request, call_next):
        # 1. 请求来源校验
        if settings.ENABLE_LOCAL_ONLY:
            client_host = request.client.host if request.client else ""
            public_admin_auth = request.url.path.startswith("/api/v1/admin/auth/")
            if not validate_local_request(client_host) and not public_admin_auth and not self._is_valid_miniapp_gateway_request(request):
                logger.warning(f"拒绝非本地请求: {client_host} → {request.url.path}")
                raise HTTPException(status_code=403, detail="仅允许本地访问")

        # 2. 请求体大小限制
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

        # 3. 处理请求
        response = await call_next(request)

        # 4. 添加安全响应头
        if isinstance(response, Response):
            for header_name, header_value in self.SECURITY_HEADERS.items():
                if header_name not in response.headers:
                    response.headers[header_name] = header_value

        return response
