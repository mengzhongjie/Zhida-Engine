"""
智答引擎（ZhiDa Engine）—— 数据库连接管理

使用 SQLite + SQLAlchemy 异步引擎，零配置、零维护。
所有数据存储在用户本地目录，支持 Windows .exe 打包后运行。
"""

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

# 创建异步数据库引擎
# SQLite 不支持多线程写入，使用 check_same_thread=False 绕过
engine = create_async_engine(
    settings.db_url,
    echo=settings.DEBUG,  # DEBUG 模式下打印 SQL 日志
    connect_args={"check_same_thread": False} if "sqlite" in settings.db_url else {},
)

# 异步会话工厂
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # 提交后不过期对象，避免 lazy load 问题
)


# SQLAlchemy 声明式基类
class Base(DeclarativeBase):
    """所有数据库模型的基类"""
    pass


async def get_db() -> AsyncSession:
    """
    获取数据库会话（用于 FastAPI 依赖注入）

    Usage:
        @app.get("/items")
        async def get_items(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db():
    """
    初始化数据库 —— 创建所有表

    在应用启动时调用，确保所有模型表存在。
    使用 create_all 而非 Alembic 迁移，因为单用户桌面应用无需版本管理。
    """
    async with engine.begin() as conn:
        # 导入所有模型，确保它们注册到 Base.metadata
        import app.models.llm_config  # noqa: F401
        import app.models.knowledge   # noqa: F401
        import app.models.qa          # noqa: F401
        import app.models.channel     # noqa: F401
        import app.models.agent       # noqa: F401

        await conn.run_sync(Base.metadata.create_all)