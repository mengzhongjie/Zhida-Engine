"""
智答引擎（ZhiDa Engine）—— 应用入口

基于 RAG 架构的个人 AI 知识助手，以 Windows 桌面应用形式运行。
启动 FastAPI 后端服务，通过 PyWebView 嵌入 React 前端提供原生窗口体验。
"""

import sys
import uvicorn
from loguru import logger

from app.core.config import settings


def setup_logging():
    """配置日志系统 —— 同时输出到控制台和文件"""
    logger.remove()  # 移除默认 handler

    # 控制台输出（彩色）
    logger.add(
        sys.stdout,
        level=settings.LOG_LEVEL,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan> | <level>{message}</level>",
        colorize=True,
    )

    # 文件输出（按天轮转）
    log_file = f"{settings.log_dir}/zhida_{{time:YYYY-MM-DD}}.log"
    logger.add(
        log_file,
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
        rotation="00:00",  # 每天午夜轮转
        retention="30 days",  # 保留 30 天
        encoding="utf-8",
    )

    logger.info(f"启动 {settings.APP_NAME} v{settings.APP_VERSION}")
    logger.info(f"数据目录: {settings.DATA_DIR}")
    logger.info(f"数据库: {settings.db_url}")


def create_app():
    """创建 FastAPI 应用实例"""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="基于 RAG 架构的个人 AI 知识助手",
        docs_url="/api/docs" if settings.DEBUG else None,  # 生产环境关闭文档
        redoc_url=None,
    )

    # CORS 中间件 —— 允许前端跨域请求
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # 本地应用，允许所有来源
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册路由
    # from app.api.v1 import api_router
    # app.include_router(api_router, prefix="/api/v1")

    # 健康检查端点
    @app.get("/health")
    async def health_check():
        return {
            "status": "ok",
            "app": settings.APP_NAME,
            "version": settings.APP_VERSION,
        }

    return app


def main():
    """应用主入口 —— 启动 FastAPI 服务"""
    setup_logging()

    app = create_app()

    logger.info(f"API 服务启动: http://{settings.API_HOST}:{settings.API_PORT}")

    # 启动 uvicorn 服务器
    uvicorn.run(
        app,
        host=settings.API_HOST,
        port=settings.API_PORT,
        log_level=settings.LOG_LEVEL.lower(),
        access_log=settings.DEBUG,
    )


if __name__ == "__main__":
    main()