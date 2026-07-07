"""
智答引擎（ZhiDa Engine）—— 限流中间件

基于已有 rate_limiter 服务，对 API 请求进行多层限流防护。

限流策略分层：
- 管理后台 API（/api/v1/admin/）：不限流
- 健康检查 + 静态文件：不限流
- 问答 API（/api/v1/qa/）：全量限流（令牌桶+滑动窗口+问题冷却+静默时段）
- 其他 API（配置/Agent/知识库）：仅令牌桶限流
"""

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from loguru import logger

from app.core.config import settings
from app.services.cache.rate_limiter import rate_limiter, RateLimitResult


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    API 限流中间件 —— 按 API 类型分层限流

    复用已有的 rate_limiter 全局实例（令牌桶+滑动窗口+问题冷却+静默时段）。
    """

    async def dispatch(self, request: Request, call_next):
        # 模块开关关闭时跳过限流
        if not settings.ENABLE_RATE_LIMIT:
            return await call_next(request)

        path = request.url.path

        # 管理后台 API 不限流
        if path.startswith("/api/v1/admin/"):
            return await call_next(request)

        # 健康检查不限流
        if path == "/health":
            return await call_next(request)

        # 静态文件不限流
        if path.startswith("/assets/") or path.startswith("/static/"):
            return await call_next(request)

        # 获取客户端 IP
        client_ip = request.client.host if request.client else "unknown"

        # 问答 API：全量限流（令牌桶 + 滑动窗口 + 问题冷却 + 静默时段）
        if path.startswith("/api/v1/qa/"):
            chat_id = request.headers.get("X-Chat-Id", client_ip)
            question_hash = request.headers.get("X-Question-Hash", "")

            result = rate_limiter.check(
                chat_id=chat_id,
                question_hash=question_hash,
                is_private=False,
            )

            if result == RateLimitResult.RATE_LIMITED:
                logger.warning(f"限流拒绝: IP={client_ip}, path={path}")
                return JSONResponse(
                    status_code=429,
                    content={"detail": "请求过于频繁，请稍后再试", "retry_after": 60},
                )

            if result == RateLimitResult.SILENT_PERIOD:
                logger.info(f"静默时段: IP={client_ip}, path={path}")
                return JSONResponse(
                    status_code=429,
                    content={"detail": "夜间静默时段，请白天再试", "retry_after": 3600},
                )

            if result == RateLimitResult.COOLDOWN:
                logger.info(f"问题冷却: IP={client_ip}, path={path}")
                return JSONResponse(
                    status_code=429,
                    content={"detail": "相同问题刚回答过，请稍后再问", "retry_after": 300},
                )

            # 允许请求，记录限流
            response = await call_next(request)
            rate_limiter.record(chat_id, question_hash)
            return response

        # 其他 API（配置/Agent/知识库）：仅令牌桶限流
        # 使用不同的 chat_id 避免与 QA 限流混淆
        result = rate_limiter.check(
            chat_id=f"api:{client_ip}:{path}",
            question_hash="",  # 不使用问题冷却
            is_private=True,   # 管理类 API 按私聊放宽限制
        )

        if result == RateLimitResult.RATE_LIMITED:
            logger.warning(f"API 限流: IP={client_ip}, path={path}")
            return JSONResponse(
                status_code=429,
                content={"detail": "请求过于频繁，请稍后再试", "retry_after": 30},
            )

        # 允许请求
        response = await call_next(request)
        return response