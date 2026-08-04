"""
智答引擎（ZhiDa Engine）—— 限流中间件

基于已有 rate_limiter 服务，对 API 请求进行多层限流防护。

限流策略分层：
- 管理台与所有只读 API：不限流
- 健康检查 + 静态文件：不限流
- 问答提交（POST /api/v1/qa/ask）：按会话的私聊令牌桶限流
- 其他写操作：仅令牌桶限流
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

        # 管理台的仪表盘、Agent 列表、配置、知识库详情都会同时发起多个只读请求。
        # 它们不触发模型或写入，不能和上传/问答共享令牌桶。
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return await call_next(request)

        # 健康检查不限流
        if path == "/health":
            return await call_next(request)

        # 静态文件不限流
        if path.startswith("/assets/") or path.startswith("/static/"):
            return await call_next(request)

        # 获取客户端 IP
        client_ip = request.client.host if request.client else "unknown"

        # 问答提交：管理台和外部 API 都通过显式 chat_id 隔离令牌桶。
        # 这里不启用群聊问题冷却；同一用户的正常追问与重试不能被误判为刷屏。
        if request.method == "POST" and path in {"/api/v1/qa/ask", "/api/v1/qa/stream"}:
            chat_id = request.headers.get("X-Chat-Id", client_ip)

            result = rate_limiter.check(
                chat_id=chat_id,
                question_hash="",
                is_private=True,
            )

            if result == RateLimitResult.RATE_LIMITED:
                logger.warning(f"限流拒绝: IP={client_ip}, path={path}")
                return JSONResponse(
                    status_code=429,
                    content={"detail": "请求过于频繁，请稍后再试", "retry_after": 60},
                )

            # 私聊会话仅做频率限制，不记录全局问题冷却。
            response = await call_next(request)
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
