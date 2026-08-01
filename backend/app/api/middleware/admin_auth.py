"""云端网页管理接口的短期令牌认证。"""

import hashlib
from datetime import datetime

from fastapi import Request
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.config import settings


class AdminAuthMiddleware(BaseHTTPMiddleware):
    """仅在部署时开启，保护后台配置、知识库与邀请码管理接口。"""

    PUBLIC_PREFIXES = (
        "/api/v1/miniapp",
        "/api/v1/admin/auth/",
        "/health",
    )

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not settings.ADMIN_AUTH_REQUIRED:
            return await call_next(request)
        if any(path.startswith(prefix) for prefix in self.PUBLIC_PREFIXES):
            return await call_next(request)
        if not path.startswith("/api/v1/"):
            return await call_next(request)

        authorization = request.headers.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            return JSONResponse({"detail": "需要管理员登录"}, status_code=401)
        token_hash = hashlib.sha256(authorization[7:].encode("utf-8")).hexdigest()
        try:
            from app.core.database import async_session_factory
            from app.models.miniapp import AdminSession
            async with async_session_factory() as db:
                session = await db.get(AdminSession, token_hash)
                if session is None or session.expires_at < datetime.utcnow():
                    return JSONResponse({"detail": "管理员会话已失效"}, status_code=401)
        except Exception as exc:
            logger.error(f"校验管理员会话失败: {exc}")
            return JSONResponse({"detail": "管理员认证暂不可用"}, status_code=503)
        return await call_next(request)
