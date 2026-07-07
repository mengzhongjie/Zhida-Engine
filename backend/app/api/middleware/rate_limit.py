"""
智答引擎（ZhiDa Engine）—— 限流中间件

基于已有 rate_limiter 服务，对 API 请求进行多层限流防护。
"""

from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from loguru import logger

from app.core.config import settings
from app.services.cache.rate_limiter import rate_limiter, RateLimitResult


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    API 限流中间件 —— 对每个请求进行限流检查

    复用已有的 rate_limiter 全局实例（令牌桶+滑动窗口+问题冷却+静默时段）。

    限流策略：
    - 所有 API 请求按 IP 维度限流
    - 群聊场景额外按 chat_id 限流
    - 私聊放宽限制
    - 管理后台 API 不限制（/api/v1/admin/）
    """

    async def dispatch(self, request: Request, call_next):
        # 模块开关关闭时跳过限流
        if not settings.ENABLE_RATE_LIMIT:
            return await call_next(request)

        # 管理后台 API 不限流
        if request.url.path.startswith("/api/v1/admin/"):
            return await call_next(request)

        # 健康检查不限流
        if request.url.path == "/health":
            return await call_next(request)

        # 静态文件不限流
        if request.url.path.startswith("/assets/") or request.url.path.startswith("/static/"):
            return await call_next(request)

        # 获取客户端 IP
        client_ip = request.client.host if request.client else "unknown"

        # 限流检查
        # 使用 chat_id 作为群聊标识（从请求头或参数获取）
        chat_id = request.headers.get("X-Chat-Id", client_ip)
        question_hash = request.headers.get("X-Question-Hash", "")

        result = rate_limiter.check(
            chat_id=chat_id,
            question_hash=question_hash,
            is_private=False,  # API 请求默认按群聊处理
        )

        if result == RateLimitResult.DENY:
            logger.warning(f"限流拒绝: IP={client_ip}, path={request.url.path}")
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "请求过于频繁，请稍后再试",
                    "retry_after": 60,
                },
            )

        if result == RateLimitResult.QUIET:
            logger.info(f"静默时段: IP={client_ip}, path={request.url.path}")
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "夜间静默时段，请白天再试",
                    "retry_after": 3600,
                },
            )

        if result == RateLimitResult.COOLDOWN:
            logger.info(f"问题冷却: IP={client_ip}, path={request.url.path}")
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "相同问题刚回答过，请稍后再问",
                    "retry_after": 300,
                },
            )

        # 允许请求
        response = await call_next(request)

        # 记录限流
        rate_limiter.record(chat_id, question_hash)

        return response