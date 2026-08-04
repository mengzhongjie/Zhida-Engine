"""
智答引擎（ZhiDa Engine）—— 记忆层服务

基于 Mem0 的长期记忆层，提供以下核心能力：
1. 从对话中自动提取事实、偏好、关系（记忆抽取）
2. 向量化存储记忆，支持语义检索
3. 自动更新/合并/删除矛盾记忆（记忆维护）
4. 按 user_id / agent_id / run_id 多级隔离
"""

import os
from pathlib import Path
from typing import Optional, Any

from loguru import logger

from app.core.config import settings


class MemoryService:
    """
    记忆层服务 —— 封装 Mem0，提供长期记忆能力

    使用项目已有的 ChromaDB 作为向量存储，
    LLM 和 Embedding 从数据库配置读取。

    Usage:
        memory = MemoryService()
        await memory.initialize(agent_id=1)

        # 添加对话记忆
        await memory.add([
            {"role": "user", "content": "我喜欢吃川菜"},
            {"role": "assistant", "content": "好的，我记住了"}
        ], user_id="user_1")

        # 搜索相关记忆
        results = await memory.search("用户的饮食偏好", user_id="user_1")
    """

    def __init__(self):
        self._memory = None
        self._agent_id: Optional[int] = None
        self._initialized = False

    # ================================================================
    # 初始化
    # ================================================================

    async def initialize(self, agent_id: Optional[int] = None):
        """
        初始化记忆层

        Args:
            agent_id: Agent ID，用于读取对应的 LLM 配置
        """
        if self._initialized and self._agent_id == agent_id:
            return

        self._agent_id = agent_id
        self._memory = None

        try:
            await self._init_mem0()
            self._initialized = True
            logger.info(f"[Memory] 记忆层初始化成功 agent_id={agent_id}")
        except Exception as e:
            logger.warning(f"[Memory] 记忆层初始化失败: {e}，将使用降级模式")
            self._initialized = False

    async def _init_mem0(self):
        """初始化 Mem0 实例"""
        try:
            from mem0 import Memory
        except ImportError:
            logger.warning("[Memory] 未安装 mem0ai，记忆层不可用")
            return

        # 构建记忆存储目录
        mem_dir = Path(settings.DATA_DIR) / "memory"
        mem_dir.mkdir(parents=True, exist_ok=True)

        history_db_path = str(mem_dir / "history.db")

        # 基础配置：使用 ChromaDB
        config_dict = {
            "vector_store": {
                "provider": "chroma",
                "config": {
                    "collection_name": "zhida_memory",
                    "path": str(mem_dir / "chroma"),
                },
            },
            "history_db_path": history_db_path,
            "version": "v1.1",
        }

        # 获取 LLM 配置
        llm_config = await self._get_llm_config()
        if llm_config:
            config_dict["llm"] = llm_config

        # 获取 Embedding 配置
        embedder_config = await self._get_embedder_config()
        if embedder_config:
            config_dict["embedder"] = embedder_config

        # 关闭遥测
        os.environ["MEM0_TELEMETRY"] = "false"

        try:
            self._memory = Memory.from_config(config_dict)
            logger.debug("[Memory] Mem0 实例创建成功")
        except Exception as e:
            logger.warning(f"[Memory] Mem0 实例创建失败: {e}，尝试使用最简配置")
            # 降级：只使用 Chroma，不配置 LLM（记忆需要手动添加）
            simple_config = {
                "vector_store": {
                    "provider": "chroma",
                    "config": {
                        "collection_name": "zhida_memory",
                        "path": str(mem_dir / "chroma"),
                    },
                },
                "history_db_path": history_db_path,
            }
            self._memory = Memory.from_config(simple_config)

    async def _get_llm_config(self) -> Optional[dict]:
        """
        从数据库获取 LLM 配置，转换为 Mem0 格式

        Returns:
            Mem0 LLM 配置字典，或 None（如果没有可用配置）
        """
        try:
            from app.models.llm_config import LLMConfig
            from app.core.database import async_session_factory
            from app.core.security import decrypt_api_key
            from sqlalchemy import select

            async with async_session_factory() as db:
                # 获取主模型配置
                query = select(LLMConfig).where(
                    LLMConfig.agent_id == self._agent_id,
                    LLMConfig.is_primary == True,
                    LLMConfig.is_active == True,
                )
                result = await db.execute(query)
                config = result.scalar_one_or_none()

                if not config:
                    # 尝试获取全局配置（agent_id 为 None）
                    query = select(LLMConfig).where(
                        LLMConfig.agent_id.is_(None),
                        LLMConfig.is_primary == True,
                        LLMConfig.is_active == True,
                    )
                    result = await db.execute(query)
                    config = result.scalar_one_or_none()

                if not config:
                    return None

                # 转换为 Mem0 配置
                api_key = decrypt_api_key(config.api_key) if config.api_key else ""

                # Mem0 使用 OpenAI 兼容格式承载当前云端模型。
                # 我们用 OpenAI 兼容格式
                provider = self._map_provider(config.provider)

                llm_config = {
                    "provider": provider,
                    "config": {
                        "model": config.model_name,
                        "temperature": 0.7,
                    },
                }

                if api_key:
                    llm_config["config"]["api_key"] = api_key

                if config.base_url:
                    llm_config["config"]["base_url"] = config.base_url

                return llm_config

        except Exception as e:
            logger.warning(f"[Memory] 获取 LLM 配置失败: {e}")
            return None

    async def _get_embedder_config(self) -> Optional[dict]:
        """
        获取 Embedding 配置，转换为 Mem0 格式

        Returns:
            Mem0 embedder 配置字典，或 None
        """
        try:
            if settings.EMBEDDING_CLOUD_BASE_URL:
                # 使用云端 OpenAI 兼容接口。
                return {
                    "provider": "openai",
                    "config": {
                        "model": settings.EMBEDDING_CLOUD_MODEL,
                        "base_url": settings.EMBEDDING_CLOUD_BASE_URL,
                        "api_key": settings.EMBEDDING_CLOUD_API_KEY or "sk-xxx",
                    },
                }
            logger.warning("[Memory] 未配置云端 Embedding，记忆层暂不可用")
            return None

        except Exception as e:
            logger.warning(f"[Memory] 获取 Embedding 配置失败: {e}")
            return None

    def _map_provider(self, provider_name: str) -> str:
        """
        将项目的 provider 名称映射到 Mem0 支持的 provider

        Args:
            provider_name: 项目中的 provider 标识

        Returns:
            Mem0 支持的 provider 名称
        """
        provider_map = {
            "openai": "openai",
            "deepseek": "openai",  # OpenAI 兼容
            "zhipu": "openai",     # OpenAI 兼容
            "moonshot": "openai",  # OpenAI 兼容
            "doubao": "openai",    # OpenAI 兼容
            "qwen": "openai",      # OpenAI 兼容
            "siliconflow": "openai",  # OpenAI 兼容
            "custom": "openai",    # 自定义，OpenAI 兼容
        }
        return provider_map.get(provider_name.lower(), "openai")

    # ================================================================
    # 记忆操作
    # ================================================================

    async def add(
        self,
        messages: list[dict],
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        run_id: Optional[str] = None,
        metadata: Optional[dict] = None,
        infer: bool = True,
    ) -> dict:
        """
        添加记忆 —— 从对话中自动提取并存储

        Args:
            messages: 对话消息列表，格式：[{"role": "user", "content": "..."}, ...]
            user_id: 用户 ID
            agent_id: Agent ID（字符串形式）
            run_id: 运行 ID（用于会话隔离）
            metadata: 额外元数据
            infer: 是否使用 LLM 抽取记忆（False 则直接存储原文）

        Returns:
            添加结果，包含 memory_id 等信息
        """
        if not self._memory:
            logger.debug("[Memory] 记忆层未初始化，跳过添加")
            return {"results": []}

        try:
            kwargs = {}
            if user_id:
                kwargs["user_id"] = user_id
            if agent_id:
                kwargs["agent_id"] = agent_id
            if run_id:
                kwargs["run_id"] = run_id
            if metadata:
                kwargs["metadata"] = metadata
            if not infer:
                kwargs["infer"] = False

            result = self._memory.add(messages, **kwargs)
            logger.debug(f"[Memory] 添加记忆成功: {len(result.get('results', []))} 条")
            return result
        except Exception as e:
            logger.warning(f"[Memory] 添加记忆失败: {e}")
            return {"results": [], "error": str(e)}

    async def search(
        self,
        query: str,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        run_id: Optional[str] = None,
        limit: int = 10,
        filters: Optional[dict] = None,
    ) -> list[dict]:
        """
        搜索相关记忆

        Args:
            query: 查询文本
            user_id: 用户 ID 过滤
            agent_id: Agent ID 过滤
            run_id: 运行 ID 过滤
            limit: 返回结果数量
            filters: 额外过滤条件

        Returns:
            记忆结果列表，每项包含 id, memory, score, metadata 等
        """
        if not self._memory:
            logger.debug("[Memory] 记忆层未初始化，返回空结果")
            return []

        try:
            kwargs = {"limit": limit}
            if user_id:
                kwargs["user_id"] = user_id
            if agent_id:
                kwargs["agent_id"] = agent_id
            if run_id:
                kwargs["run_id"] = run_id
            if filters:
                kwargs["filters"] = filters
            result = self._memory.search(query, **kwargs)
            return result.get("results", [])
        except Exception as e:
            logger.warning(f"[Memory] 搜索记忆失败: {e}")
            return []

    async def get(self, memory_id: str) -> Optional[dict]:
        """
        根据 ID 获取单条记忆

        Args:
            memory_id: 记忆 ID

        Returns:
            记忆详情，或 None
        """
        if not self._memory:
            return None

        try:
            result = self._memory.get(memory_id)
            return result
        except Exception as e:
            logger.warning(f"[Memory] 获取记忆失败: {e}")
            return None

    async def get_all(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        run_id: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        """
        获取所有记忆（可过滤）

        Args:
            user_id: 用户 ID 过滤
            agent_id: Agent ID 过滤
            run_id: 运行 ID 过滤
            limit: 返回数量限制

        Returns:
            记忆列表
        """
        if not self._memory:
            return []

        try:
            kwargs = {"limit": limit}
            if user_id:
                kwargs["user_id"] = user_id
            if agent_id:
                kwargs["agent_id"] = agent_id
            if run_id:
                kwargs["run_id"] = run_id

            result = self._memory.get_all(**kwargs)
            return result.get("results", [])
        except Exception as e:
            logger.warning(f"[Memory] 获取所有记忆失败: {e}")
            return []

    async def update(self, memory_id: str, data: str) -> bool:
        """
        更新记忆内容

        Args:
            memory_id: 记忆 ID
            data: 新的记忆内容

        Returns:
            是否成功
        """
        if not self._memory:
            return False

        try:
            self._memory.update(memory_id, data)
            return True
        except Exception as e:
            logger.warning(f"[Memory] 更新记忆失败: {e}")
            return False

    async def delete(self, memory_id: str) -> bool:
        """
        删除单条记忆

        Args:
            memory_id: 记忆 ID

        Returns:
            是否成功
        """
        if not self._memory:
            return False

        try:
            self._memory.delete(memory_id)
            return True
        except Exception as e:
            logger.warning(f"[Memory] 删除记忆失败: {e}")
            return False

    async def delete_all(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> bool:
        """
        删除所有记忆（可过滤）

        Args:
            user_id: 用户 ID 过滤
            agent_id: Agent ID 过滤
            run_id: 运行 ID 过滤

        Returns:
            是否成功
        """
        if not self._memory:
            return False

        try:
            kwargs = {}
            if user_id:
                kwargs["user_id"] = user_id
            if agent_id:
                kwargs["agent_id"] = agent_id
            if run_id:
                kwargs["run_id"] = run_id

            self._memory.delete_all(**kwargs)
            return True
        except Exception as e:
            logger.warning(f"[Memory] 删除所有记忆失败: {e}")
            return False

    async def history(
        self,
        memory_id: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        """
        获取记忆历史记录

        Args:
            memory_id: 记忆 ID（可选，不传则返回所有历史）
            limit: 返回数量限制

        Returns:
            历史记录列表
        """
        if not self._memory:
            return []

        try:
            kwargs = {"limit": limit}
            if memory_id:
                kwargs["memory_id"] = memory_id

            result = self._memory.history(**kwargs)
            return result.get("results", [])
        except Exception as e:
            logger.warning(f"[Memory] 获取历史记录失败: {e}")
            return []

    # ================================================================
    # 便捷方法
    # ================================================================

    async def add_text(
        self,
        text: str,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        """
        直接添加一段文本作为记忆（不经过 LLM 抽取）

        Args:
            text: 记忆文本
            user_id: 用户 ID
            agent_id: Agent ID
            metadata: 元数据

        Returns:
            添加结果
        """
        messages = [{"role": "user", "content": text}]
        return await self.add(
            messages,
            user_id=user_id,
            agent_id=agent_id,
            metadata=metadata,
            infer=False,
        )

    async def get_relevant_memories(
        self,
        query: str,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        limit: int = 5,
    ) -> str:
        """
        获取与查询相关的记忆，格式化为字符串（用于注入 Prompt）

        Args:
            query: 查询文本
            user_id: 用户 ID
            agent_id: Agent ID
            limit: 返回记忆数量

        Returns:
            格式化后的记忆文本
        """
        memories = await self.search(
            query,
            user_id=user_id,
            agent_id=agent_id,
            limit=limit,
        )

        if not memories:
            return ""

        lines = []
        for i, mem in enumerate(memories, 1):
            content = mem.get("memory", "")
            if content:
                lines.append(f"{i}. {content}")

        return "\n".join(lines)

    @property
    def is_available(self) -> bool:
        """记忆层是否可用"""
        return self._memory is not None and self._initialized


# 全局单例
memory_service = MemoryService()
