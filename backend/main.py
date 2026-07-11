"""
智答引擎（ZhiDa Engine）—— 应用入口

基于 RAG 架构的个人 AI 知识助手，以 Windows 桌面应用形式运行。
启动 FastAPI 后端服务，通过 PyWebView 嵌入 React 前端提供原生窗口体验。

启动流程：
1. 进程单实例锁 → 防止多开
2. 数据目录权限加固 → 仅当前用户可读写
3. 端口自动选择 → 避免端口冲突
4. 日志系统初始化
5. 数据库初始化 → 异步
6. 安全中间件注册 → 请求来源校验 + 限流
7. API 路由注册
8. 前端静态文件挂载
9. 启动 uvicorn 服务器
"""

import sys
import os
import signal
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
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """应用生命周期 —— 启动时初始化数据库, 关闭时释放资源"""
        logger.info("正在初始化数据库...")
        from app.core.database import init_db
        await init_db()
        logger.info("数据库初始化完成")

        # 初始化向量化配置（从数据库加载）
        from app.core.database import async_session_factory
        from app.api.v1.embedding.router import init_embedding_config
        async with async_session_factory() as db:
            await init_embedding_config(db)

        # 后台异步加载重模块（不阻塞启动）
        import asyncio
        asyncio.create_task(_lazy_load_heavy_modules())

        yield  # 应用运行中

        # 关闭时释放资源
        from app.core.security import release_instance_lock
        release_instance_lock()
        logger.info("应用关闭，资源已释放")

    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="基于 RAG 架构的个人 AI 知识助手",
        docs_url="/api/docs" if settings.DEBUG else None,  # 生产环境关闭文档
        redoc_url=None,
        lifespan=lifespan,
    )

    # CORS 中间件 —— 允许前端跨域请求(本地应用安全)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # 本地应用，允许所有来源
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 安全中间件 —— 请求来源校验 + 安全响应头 + 请求大小限制
    from app.api.middleware.security import SecurityMiddleware
    app.add_middleware(SecurityMiddleware)

    # 限流中间件 —— 令牌桶 + 滑动窗口 + 问题冷却 + 静默时段
    from app.api.middleware.rate_limit import RateLimitMiddleware
    app.add_middleware(RateLimitMiddleware)

    # 云端部署可开启二维码管理员认证；桌面版默认保持本地免登录体验。
    from app.api.middleware.admin_auth import AdminAuthMiddleware
    app.add_middleware(AdminAuthMiddleware)

    # ================================================================
    # 注册 API 路由
    # ================================================================

    # LLM 配置
    from app.api.v1.config.router import router as llm_config_router
    app.include_router(llm_config_router, prefix="/api/v1")

    # Agent 管理
    from app.api.v1.agent.router import router as agent_router
    app.include_router(agent_router, prefix="/api/v1")

    # 知识库管理
    from app.api.v1.knowledge.router import router as knowledge_router
    app.include_router(knowledge_router, prefix="/api/v1")

    # 问答
    from app.api.v1.qa.router import router as qa_router
    app.include_router(qa_router, prefix="/api/v1")

    # 管理后台
    from app.api.v1.admin.router import router as admin_router
    app.include_router(admin_router, prefix="/api/v1")

    # 向量化配置
    from app.api.v1.embedding.router import router as embedding_router
    app.include_router(embedding_router, prefix="/api/v1")

    # 小程序邀请制问答接口（仅接受 CloudBase 网关签名请求）
    from app.api.v1.miniapp.router import router as miniapp_router
    app.include_router(miniapp_router, prefix="/api/v1")

    # ================================================================
    # 前端静态文件服务（生产环境：前端构建产物嵌入 .exe）
    # ================================================================
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    if os.path.isdir(static_dir) and os.path.exists(os.path.join(static_dir, "index.html")):
        # 挂载静态资源（JS/CSS/图片等）
        app.mount("/assets", StaticFiles(directory=os.path.join(static_dir, "assets")), name="assets")

        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str = ""):
            """
            SPA 回退路由 —— 所有非 API 路径返回 index.html

            前端使用 HashRouter，浏览器直接访问 /#/agents/1 时，
            需要先加载 index.html，再由前端路由接管。
            """
            # API 路径不处理（让 FastAPI 路由处理）
            if full_path.startswith("api/") or full_path == "health":
                from fastapi.responses import JSONResponse
                return JSONResponse({"detail": "Not Found"}, status_code=404)

            index_path = os.path.join(static_dir, "index.html")
            return FileResponse(index_path)

        logger.info(f"前端静态文件已挂载: {static_dir}")
    else:
        logger.info("未找到前端静态文件，跳过挂载（开发模式请使用 npm run dev）")

    # 健康检查端点
    @app.get("/health")
    async def health_check():
        return {
            "status": "ok",
            "app": settings.APP_NAME,
            "version": settings.APP_VERSION,
        }

    return app


async def _lazy_load_heavy_modules():
    """
    后台异步加载重模块 —— 不阻塞 UI 启动

    这些模块加载耗时较长，在后台异步完成：
    - Embedding 模型（sentence-transformers，~2-5s）
    - ChromaDB 初始化（~1-2s）
    - jieba 词典（~0.5s）
    """
    import asyncio

    try:
        # 延迟加载 Embedding 模型
        logger.info("后台加载 Embedding 模型...")
        from app.services.knowledge.embedder import embedding_service
        await asyncio.to_thread(lambda: embedding_service)  # 触发懒加载
        logger.info("Embedding 模型加载完成")
    except Exception as e:
        logger.warning(f"Embedding 模型加载失败（不影响基础功能）: {e}")

    try:
        # 预加载 jieba 分词
        logger.info("后台加载 jieba 分词...")
        import jieba
        jieba.initialize()
        logger.info("jieba 分词加载完成")
    except Exception as e:
        logger.warning(f"jieba 分词加载失败: {e}")


def main():
    """应用主入口 —— 启动 FastAPI 服务"""
    # 1. 进程单实例锁
    from app.core.security import acquire_instance_lock
    if not acquire_instance_lock():
        logger.error("已有实例在运行，退出")
        sys.exit(1)

    # 2. 数据目录权限加固
    from app.core.security import secure_data_directory
    secure_data_directory()

    # 3. 端口自动选择
    from app.core.security import find_available_port
    actual_port = find_available_port(start_port=settings.API_PORT)
    if actual_port != settings.API_PORT:
        logger.info(f"端口已自动调整为: {actual_port} (原端口 {settings.API_PORT} 被占用)")
        settings.API_PORT = actual_port

    # 4. 日志系统初始化
    setup_logging()

    # 5. 创建 FastAPI 应用
    app = create_app()

    logger.info(f"API 服务启动: http://{settings.API_HOST}:{settings.API_PORT}")

    # 注册优雅退出信号处理
    def graceful_shutdown(signum, frame):
        logger.info(f"收到信号 {signum}，正在优雅退出...")
        from app.core.security import release_instance_lock
        release_instance_lock()
        sys.exit(0)

    signal.signal(signal.SIGINT, graceful_shutdown)
    signal.signal(signal.SIGTERM, graceful_shutdown)

    # 6. 启动 uvicorn 服务器
    uvicorn.run(
        app,
        host=settings.API_HOST,
        port=settings.API_PORT,
        log_level=settings.LOG_LEVEL.lower(),
        access_log=settings.DEBUG,
    )


if __name__ == "__main__":
    main()
