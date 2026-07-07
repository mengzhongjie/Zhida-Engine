"""
智答引擎（ZhiDa Engine）—— LLM 统一网关

配置驱动的 LLM 调用层，支持：
- 多厂商模板自动填充（8 个内置厂商 + 自定义）
- 主模型 + 降级模型自动切换
- 测试连接功能
- 流式输出
- 完全从数据库配置读取，不使用硬编码模型列表
"""

import time
from typing import Optional, AsyncIterator, Any
from dataclasses import dataclass

from loguru import logger
from openai import AsyncOpenAI

from app.core.config import settings
from app.core.security import decrypt_api_key
from app.models.llm_config import LLMConfig
from app.services.llm.provider_templates import (
    ProviderTemplate,
    get_provider_by_id,
    ProviderCategory,
)


@dataclass
class ModelClient:
    """单个模型客户端 —— 封装 OpenAI 兼容的 API 调用"""
    config: LLMConfig
    client: AsyncOpenAI
    provider: Optional[ProviderTemplate] = None


class LLMGateway:
    """
    LLM 统一网关 —— 管理所有已配置的 LLM 模型

    配置驱动：从数据库读取模型配置，不使用硬编码列表。
    每个 Agent 可以配置独立的主模型和降级模型。

    Usage:
        gateway = LLMGateway()
        await gateway.initialize(agent_id=1)

        # 普通调用
        response = await gateway.chat("你好，请介绍一下自己")

        # 流式调用
        async for chunk in gateway.chat_stream("你好"):
            print(chunk, end="")
    """

    def __init__(self):
        # 当前 Agent 的模型客户端
        self._primary_client: Optional[ModelClient] = None     # 主模型
        self._fallback_clients: list[ModelClient] = []          # 降级模型列表
        self._agent_id: Optional[int] = None

    # ================================================================
    # 初始化
    # ================================================================

    async def initialize(self, agent_id: Optional[int] = None):
        """
        初始化网关 —— 从数据库加载 Agent 的 LLM 配置

        Args:
            agent_id: Agent ID，为 None 时使用全局配置
        """
        self._agent_id = agent_id
        self._primary_client = None
        self._fallback_clients = []

        # 从数据库加载配置
        configs = await self._load_configs(agent_id)

        # 构建模型客户端
        for config in configs:
            client = self._build_client(config)
            if config.is_primary:
                self._primary_client = client
            elif config.is_fallback:
                self._fallback_clients.append(client)

        # 如果没有配置主模型，记录警告
        if self._primary_client is None:
            logger.warning(f"Agent {agent_id}: 未配置主模型，LLM 功能不可用")

        logger.info(
            f"LLM 网关初始化完成: Agent={agent_id}, "
            f"主模型={self._primary_client.config.model_name if self._primary_client else '无'}, "
            f"降级模型={len(self._fallback_clients)} 个"
        )

    async def _load_configs(self, agent_id: Optional[int]) -> list[LLMConfig]:
        """从数据库加载 LLM 配置"""
        from app.core.database import async_session_factory
        from sqlalchemy import select

        async with async_session_factory() as session:
            query = select(LLMConfig).where(
                LLMConfig.is_active == True,  # noqa: E712
            )
            if agent_id is not None:
                query = query.where(LLMConfig.agent_id == agent_id)
            else:
                query = query.where(LLMConfig.agent_id.is_(None))

            query = query.order_by(LLMConfig.is_primary.desc())
            result = await session.execute(query)
            return list(result.scalars().all())

    def _build_client(self, config: LLMConfig) -> ModelClient:
        """根据配置构建 OpenAI 兼容客户端"""
        base_url = config.base_url
        # 解密 API Key 后使用（加密存储，运行时解密）
        api_key = decrypt_api_key(config.api_key) or "not-needed"  # Ollama 不需要真实 key

        client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=60.0,  # 60 秒超时
        )

        # 查找对应的厂商模板
        provider = get_provider_by_id(config.provider_id)

        return ModelClient(
            config=config,
            client=client,
            provider=provider,
        )

    # ================================================================
    # 对话接口
    # ================================================================

    async def chat(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str:
        """
        发送对话请求 —— 主模型失败时自动降级

        Args:
            prompt: 用户消息
            system_prompt: 系统提示词
            temperature: 温度参数
            max_tokens: 最大 token 数

        Returns:
            模型回复文本

        Raises:
            RuntimeError: 所有模型（主模型 + 降级模型）都不可用时
        """
        # 构建消息列表
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # 尝试主模型
        if self._primary_client:
            try:
                return await self._call_model(self._primary_client, messages, temperature, max_tokens)
            except Exception as e:
                logger.warning(f"主模型 {self._primary_client.config.model_name} 调用失败: {e}，尝试降级模型")

        # 降级：依次尝试降级模型
        for fallback in self._fallback_clients:
            try:
                logger.info(f"使用降级模型: {fallback.config.model_name}")
                return await self._call_model(fallback, messages, temperature, max_tokens)
            except Exception as e:
                logger.warning(f"降级模型 {fallback.config.model_name} 也失败: {e}")
                continue

        # 所有模型都不可用
        raise RuntimeError("所有 LLM 模型均不可用，请检查配置和网络连接")

    async def chat_stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> AsyncIterator[str]:
        """
        流式对话 —— 逐 token 返回模型回复

        Usage:
            async for chunk in gateway.chat_stream("你好"):
                yield chunk  # 每段是一个 token 或 token 片段
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # 优先使用主模型
        client = self._primary_client
        if client is None and self._fallback_clients:
            client = self._fallback_clients[0]

        if client is None:
            raise RuntimeError("没有可用的 LLM 模型")

        try:
            async for chunk in self._call_model_stream(client, messages, temperature, max_tokens):
                yield chunk
        except Exception as e:
            logger.error(f"流式调用失败: {e}")
            raise

    # ================================================================
    # 底层调用
    # ================================================================

    async def _call_model(
        self,
        model_client: ModelClient,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> str:
        """调用单个模型（非流式）"""
        start_time = time.time()

        response = await model_client.client.chat.completions.create(
            model=model_client.config.model_name,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        elapsed = (time.time() - start_time) * 1000
        content = response.choices[0].message.content or ""

        logger.debug(
            f"模型 {model_client.config.model_name} 响应: "
            f"{len(content)} 字符, {elapsed:.0f}ms"
        )

        return content

    async def _call_model_stream(
        self,
        model_client: ModelClient,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[str]:
        """调用单个模型（流式）"""
        stream = await model_client.client.chat.completions.create(
            model=model_client.config.model_name,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )

        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    # ================================================================
    # 测试连接
    # ================================================================

    async def test_connection(
        self,
        base_url: str,
        api_key: str,
        model_name: str,
    ) -> dict:
        """
        测试 LLM 连接 —— 发送测试消息验证连通性

        Args:
            base_url: API 基础地址
            api_key: API Key
            model_name: 模型名称

        Returns:
            {"success": True/False, "message": "...", "latency_ms": ...}
        """
        start_time = time.time()

        try:
            client = AsyncOpenAI(
                base_url=base_url,
                api_key=api_key or "not-needed",
                timeout=15.0,  # 测试连接用较短超时
            )

            response = await client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": "你好，请回复'连接测试成功'"}],
                max_tokens=20,
                temperature=0.0,
            )

            elapsed = (time.time() - start_time) * 1000
            reply = response.choices[0].message.content or ""

            return {
                "success": True,
                "message": f"连接成功！模型回复: {reply[:50]}",
                "latency_ms": round(elapsed, 0),
                "model": model_name,
            }

        except Exception as e:
            elapsed = (time.time() - start_time) * 1000
            logger.warning(f"连接测试失败: {model_name} @ {base_url}: {e}")

            return {
                "success": False,
                "message": f"连接失败: {str(e)[:200]}",
                "latency_ms": round(elapsed, 0),
                "model": model_name,
            }

    async def test_configured_model(self, config: LLMConfig) -> dict:
        """测试已配置的模型连接"""
        return await self.test_connection(
            base_url=config.base_url,
            api_key=config.api_key,
            model_name=config.model_name,
        )

    # ================================================================
    # 状态查询
    # ================================================================

    @property
    def is_ready(self) -> bool:
        """网关是否就绪（至少有一个可用模型）"""
        return self._primary_client is not None or len(self._fallback_clients) > 0

    @property
    def primary_model_name(self) -> Optional[str]:
        """获取主模型名称"""
        if self._primary_client:
            return self._primary_client.config.model_name
        return None

    def get_available_models(self) -> list[dict]:
        """获取所有可用模型信息"""
        models = []
        if self._primary_client:
            models.append({
                "role": "primary",
                "model": self._primary_client.config.model_name,
                "provider": self._primary_client.config.provider_name,
            })
        for client in self._fallback_clients:
            models.append({
                "role": "fallback",
                "model": client.config.model_name,
                "provider": client.config.provider_name,
            })
        return models


# 全局网关实例
# 注意：需要在 Agent 切换时重新初始化
llm_gateway = LLMGateway()