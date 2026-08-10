"""
智答引擎（ZhiDa Engine）—— 数据库连接管理

使用 SQLite + SQLAlchemy 异步引擎，零配置、零维护。
所有数据存储在用户本地目录，支持 Windows .exe 打包后运行。

性能优化：
- WAL 模式：读写并发，写入不阻塞读取
- 连接池：复用连接，减少创建开销
- 索引优化：自动创建常用查询索引
- 外键约束：数据完整性保证
"""

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import event, text

from app.core.config import settings


# SQLite 性能优化参数
# WAL 模式 + 合理缓存 + 同步策略
# 注意：aiosqlite 使用 NullPool，不支持 pool_size/max_overflow 参数
_SQLITE_ENGINE_KWARGS = {
    "echo": settings.DEBUG,  # DEBUG 模式下打印 SQL 日志
}

# SQLite 连接参数
_SQLITE_CONNECT_ARGS = {
    "check_same_thread": False,  # 允许跨线程访问
    "timeout": 10,               # 锁等待超时（秒）
    # 性能优化 pragma 在连接后通过事件设置
}


def _set_sqlite_pragma(dbapi_connection, connection_record):
    """
    设置 SQLite 性能优化参数 —— 每次新连接时执行

    WAL 模式优势：
    - 读写不互斥：读操作不会阻塞写操作
    - 更好的并发：多个读操作可同时进行
    - 崩溃恢复：WAL 文件提供更好的崩溃恢复能力
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")          # WAL 模式，读写并发
    cursor.execute("PRAGMA synchronous=NORMAL")         # 平衡安全和性能
    cursor.execute("PRAGMA cache_size=-8000")           # 8MB 缓存
    cursor.execute("PRAGMA temp_store=MEMORY")          # 临时表存储在内存
    cursor.execute("PRAGMA mmap_size=268435456")        # 256MB 内存映射
    cursor.execute("PRAGMA foreign_keys=ON")            # 启用外键约束
    cursor.execute("PRAGMA busy_timeout=5000")          # 忙等待超时 5 秒
    cursor.close()


# 创建异步数据库引擎
engine = create_async_engine(
    settings.db_url,
    connect_args=_SQLITE_CONNECT_ARGS if "sqlite" in settings.db_url else {},
    **_SQLITE_ENGINE_KWARGS,
)

# 注册 SQLite 连接事件 —— 设置性能优化 pragma
if "sqlite" in settings.db_url:
    event.listen(engine.sync_engine, "connect", _set_sqlite_pragma)

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
    初始化数据库 —— 创建所有表 + 性能索引

    在应用启动时调用，确保所有模型表存在。
    使用 create_all 而非 Alembic 迁移，因为单用户桌面应用无需版本管理。
    """
    async with engine.begin() as conn:
        # 导入所有模型，确保它们注册到 Base.metadata
        import app.models.llm_config        # noqa: F401
        import app.models.knowledge         # noqa: F401
        import app.models.qa                # noqa: F401
        import app.models.agent             # noqa: F401
        import app.models.embedding_config  # noqa: F401
        import app.models.embedding_profile # noqa: F401
        import app.models.web_search_config # noqa: F401
        import app.models.observability_config  # noqa: F401
        import app.models.feishu_config   # noqa: F401
        import app.models.import_job      # noqa: F401
        import app.models.vision_config   # noqa: F401
        import app.models.agent_knowledge_base  # noqa: F401
        import app.models.auth              # noqa: F401
        import app.models.persona_preset    # noqa: F401

        # 创建所有表
        await conn.run_sync(Base.metadata.create_all)

        # create_all 不会为既有 SQLite 表添加新列；此处保持桌面版向后兼容。
        await _run_compatible_migrations(conn)

        from app.models.persona_preset import DEFAULT_PERSONA_PRESETS
        for key, value in DEFAULT_PERSONA_PRESETS.items():
            await conn.execute(text(
                "INSERT OR IGNORE INTO persona_presets (key, name, instruction) VALUES (:key, :name, :instruction)"
            ), {"key": key, "name": value["name"], "instruction": value["instruction"]})

        # 创建性能优化索引（如果不存在）
        await _create_indexes(conn)


async def _run_compatible_migrations(conn):
    migrations = [
        "ALTER TABLE agents ADD COLUMN is_public BOOLEAN NOT NULL DEFAULT 0",
        "ALTER TABLE documents ADD COLUMN content_hash VARCHAR(64)",
        "ALTER TABLE documents ADD COLUMN split_time_ms FLOAT NOT NULL DEFAULT 0",
        "ALTER TABLE documents ADD COLUMN embedding_time_ms FLOAT NOT NULL DEFAULT 0",
        "ALTER TABLE documents ADD COLUMN total_time_ms FLOAT NOT NULL DEFAULT 0",
        "ALTER TABLE documents ADD COLUMN processing_stage VARCHAR(30)",
        "ALTER TABLE documents ADD COLUMN failed_stage VARCHAR(30)",
        "ALTER TABLE documents ADD COLUMN processing_attempts INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE documents ADD COLUMN source_url VARCHAR(1500)",
        "ALTER TABLE documents ADD COLUMN source_type VARCHAR(30) NOT NULL DEFAULT 'file'",
        "ALTER TABLE documents ADD COLUMN source_key VARCHAR(500)",
        "ALTER TABLE documents ADD COLUMN character_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE documents ADD COLUMN web_image_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE documents ADD COLUMN vision_image_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE documents ADD COLUMN vision_time_ms FLOAT NOT NULL DEFAULT 0",
        "ALTER TABLE knowledge_bases ADD COLUMN total_characters INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE knowledge_bases ADD COLUMN embedding_model VARCHAR(300)",
        "ALTER TABLE knowledge_bases ADD COLUMN embedding_dimension INTEGER",
        "ALTER TABLE knowledge_bases ADD COLUMN index_space VARCHAR(20)",
        "ALTER TABLE knowledge_bases ADD COLUMN index_version VARCHAR(40)",
        "ALTER TABLE knowledge_bases ADD COLUMN index_status VARCHAR(30) NOT NULL DEFAULT 'ready'",
        "ALTER TABLE qa_history ADD COLUMN input_tokens INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE qa_history ADD COLUMN output_tokens INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE qa_history ADD COLUMN is_degraded BOOLEAN NOT NULL DEFAULT 0",
        "ALTER TABLE qa_history ADD COLUMN web_search_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE qa_history ADD COLUMN request_id VARCHAR(80)",
        "ALTER TABLE qa_history ADD COLUMN conversation_id VARCHAR(48)",
        "ALTER TABLE qa_history ADD COLUMN owner_type VARCHAR(20)",
        "ALTER TABLE qa_history ADD COLUMN owner_id INTEGER",
        "ALTER TABLE web_search_configs ADD COLUMN tavily_api_key TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE web_search_configs ADD COLUMN exa_api_key TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE vision_configs ADD COLUMN name VARCHAR(100) NOT NULL DEFAULT '视觉模型'",
        "ALTER TABLE vision_configs ADD COLUMN is_primary BOOLEAN NOT NULL DEFAULT 0",
        "ALTER TABLE vision_configs ADD COLUMN is_fallback BOOLEAN NOT NULL DEFAULT 0",
        "ALTER TABLE captcha_challenges ADD COLUMN image_svg TEXT",
        "ALTER TABLE access_codes ADD COLUMN code_ciphertext TEXT",
        "ALTER TABLE access_codes ADD COLUMN claimed_at DATETIME",
        "ALTER TABLE agents ADD COLUMN persona_preset VARCHAR(30) NOT NULL DEFAULT 'professional'",
        "ALTER TABLE agents ADD COLUMN response_detail VARCHAR(20) NOT NULL DEFAULT 'concise'",
        "ALTER TABLE agents ADD COLUMN persona_custom_instruction TEXT",
        "ALTER TABLE agents ADD COLUMN context_window_k INTEGER NOT NULL DEFAULT 64",
        "ALTER TABLE llm_configs ADD COLUMN is_context_model BOOLEAN NOT NULL DEFAULT 0",
        "ALTER TABLE llm_configs ADD COLUMN context_rewrite_timeout_seconds INTEGER NOT NULL DEFAULT 10",
        "ALTER TABLE llm_configs ADD COLUMN context_compaction_timeout_seconds INTEGER NOT NULL DEFAULT 25",
        "ALTER TABLE conversations ADD COLUMN context_summary TEXT",
        "ALTER TABLE conversations ADD COLUMN summarized_through_history_id INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE conversations ADD COLUMN summary_updated_at DATETIME",
        "ALTER TABLE observability_configs ADD COLUMN online_evaluation_enabled BOOLEAN NOT NULL DEFAULT 0",
        "ALTER TABLE observability_configs ADD COLUMN last_test_success BOOLEAN",
        "ALTER TABLE observability_configs ADD COLUMN last_test_at DATETIME",
        "ALTER TABLE observability_configs ADD COLUMN last_test_message VARCHAR(500)",
    ]
    for sql in migrations:
        try:
            await conn.execute(text(sql))
        except Exception:
            # 新库已由 create_all 建列；旧库重复执行会报错，均可安全忽略。
            pass

    # 将旧版单一搜索密钥只迁移到其当时选中的供应商，避免把同一密钥误用到 Exa/Tavily。
    try:
        await conn.execute(text(
            "UPDATE web_search_configs SET tavily_api_key = api_key "
            "WHERE provider = 'tavily' AND tavily_api_key = '' AND api_key != ''"
        ))
        await conn.execute(text(
            "UPDATE web_search_configs SET exa_api_key = api_key "
            "WHERE provider = 'exa' AND exa_api_key = '' AND api_key != ''"
        ))
    except Exception:
        pass

    try:
        await conn.execute(text("INSERT OR IGNORE INTO agent_knowledge_bases (agent_id, knowledge_base_id) SELECT agent_id, id FROM knowledge_bases WHERE agent_id IS NOT NULL"))
    except Exception:
        pass

    # 旧版本允许同一兑换码重复登录。升级时把已经产生用户的兑换码视为已激活，
    # 并销毁可恢复明文，防止管理员或第二个持码人再次冒充该用户。
    try:
        duplicate_codes = (await conn.execute(text(
            "SELECT access_code_id FROM web_users GROUP BY access_code_id HAVING COUNT(*) > 1"
        ))).scalars().all()
        for access_code_id in duplicate_codes:
            user_ids = (await conn.execute(text(
                "SELECT id FROM web_users WHERE access_code_id = :code_id ORDER BY id"
            ), {"code_id": access_code_id})).scalars().all()
            keeper, duplicates = user_ids[0], user_ids[1:]
            for duplicate in duplicates:
                await conn.execute(text(
                    "UPDATE conversations SET owner_id = :keeper WHERE owner_type = 'user' AND owner_id = :duplicate"
                ), {"keeper": keeper, "duplicate": duplicate})
                await conn.execute(text(
                    "UPDATE qa_history SET owner_id = :keeper, user_id = :keeper_key "
                    "WHERE owner_type = 'user' AND owner_id = :duplicate"
                ), {"keeper": keeper, "keeper_key": f"user:{keeper}", "duplicate": duplicate})
                await conn.execute(text(
                    "UPDATE auth_sessions SET user_id = :keeper WHERE user_id = :duplicate"
                ), {"keeper": keeper, "duplicate": duplicate})
                await conn.execute(text("DELETE FROM web_users WHERE id = :duplicate"), {"duplicate": duplicate})
        await conn.execute(text(
            "UPDATE access_codes SET status = 'claimed', claimed_at = COALESCE(claimed_at, created_at), "
            "code_ciphertext = NULL WHERE id IN (SELECT access_code_id FROM web_users) "
            "AND status IN ('active', 'claimed')"
        ))
    except Exception:
        pass


async def _create_indexes(conn):
    """
    创建常用查询的性能索引

    索引覆盖：
    - Agent 状态查询（仪表盘）
    - LLM 配置查询（按 agent_id + is_primary）
    - 知识库查询（按 agent_id）
    - 问答历史查询（按 agent_id + created_at）
    """
    indexes = [
        # Agent 索引
        "CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status)",
        "CREATE INDEX IF NOT EXISTS idx_agents_is_active ON agents(is_active)",
        "CREATE INDEX IF NOT EXISTS idx_agents_public_active ON agents(is_public, is_active)",
        "CREATE INDEX IF NOT EXISTS idx_agents_created_at ON agents(created_at)",

        # LLM 配置索引
        "CREATE INDEX IF NOT EXISTS idx_llm_configs_agent_primary ON llm_configs(agent_id, is_primary)",
        "CREATE INDEX IF NOT EXISTS idx_llm_configs_is_active ON llm_configs(is_active)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_llm_configs_context_scope ON llm_configs(COALESCE(agent_id, -1)) WHERE is_context_model = 1",

        # 知识库索引
        "CREATE INDEX IF NOT EXISTS idx_knowledge_bases_agent ON knowledge_bases(agent_id)",
        "CREATE INDEX IF NOT EXISTS idx_documents_kb ON documents(knowledge_base_id)",
        "CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status)",
        "CREATE INDEX IF NOT EXISTS idx_documents_kb_content_hash ON documents(knowledge_base_id, content_hash)",
        "CREATE INDEX IF NOT EXISTS idx_documents_kb_source_key ON documents(knowledge_base_id, source_key)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_documents_kb_content_hash ON documents(knowledge_base_id, content_hash) WHERE content_hash IS NOT NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_document_chunks_document_parent ON document_chunks(document_id, parent_id)",
        "CREATE INDEX IF NOT EXISTS idx_document_chunks_kb_parent ON document_chunks(knowledge_base_id, parent_id)",

        # 问答历史索引
        "CREATE INDEX IF NOT EXISTS idx_qa_history_agent_time ON qa_history(agent_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_qa_history_user_request ON qa_history(user_id, request_id)",
        "CREATE INDEX IF NOT EXISTS idx_qa_history_conversation ON qa_history(conversation_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_access_code_agents_code_agent ON access_code_agents(access_code_id, agent_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_web_users_access_code ON web_users(access_code_id)",
        "CREATE INDEX IF NOT EXISTS idx_access_code_daily_usage_date ON access_code_daily_usage(usage_date)",
        "CREATE INDEX IF NOT EXISTS idx_conversations_owner_time ON conversations(owner_type, owner_id, updated_at)",
        "CREATE INDEX IF NOT EXISTS idx_qa_pairs_agent ON qa_pairs(agent_id)",

        "CREATE INDEX IF NOT EXISTS idx_admin_sessions_expires ON admin_sessions(expires_at)",
    ]

    for idx_sql in indexes:
        try:
            await conn.execute(text(idx_sql))
        except Exception as e:
            # 表可能不存在（首次启动），跳过
            pass

    await conn.commit()
