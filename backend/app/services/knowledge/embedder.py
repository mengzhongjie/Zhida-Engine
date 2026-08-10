"""
智答引擎（ZhiDa Engine）—— 向量化服务

使用云端 Embedding API（OpenAI 兼容）。

抽象 EmbeddingService 接口，方便切换不同实现。
"""

from abc import ABC, abstractmethod

from loguru import logger

from app.core.config import settings


BGE_QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："


def _prepare_query(model_name: str, query: str) -> str:
    """BGE v1.5 仅查询侧需要检索指令，文档侧保持原文。"""
    normalized_name = model_name.strip().lower()
    if normalized_name == "baai/bge-large-zh-v1.5" or normalized_name.endswith("/bge-large-zh-v1.5"):
        return f"{BGE_QUERY_INSTRUCTION}{query}"
    return query


class EmbeddingService(ABC):
    """
    Embedding 服务抽象接口。

    所有 Embedding 实现必须继承此接口。
    """

    @abstractmethod
    async def embed_text(self, text: str) -> list[float]:
        """将单段文本转为向量"""
        ...

    @abstractmethod
    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """批量将文本转为向量"""
        ...

    async def embed_query(self, query: str) -> list[float]:
        """向量化查询；特定模型可覆盖查询侧预处理。"""
        return await self.embed_text(_prepare_query(self.model_name, query))

    @abstractmethod
    async def is_ready(self) -> bool:
        """检查服务是否就绪"""
        ...

    @property
    @abstractmethod
    def dimension(self) -> int:
        """向量维度"""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """模型名称"""
        ...


class CloudEmbedding(EmbeddingService):
    """
    云端 Embedding 服务 —— 使用 OpenAI 兼容 API

    优点：
    - 无需本地 GPU
    - 速度快

    缺点：
    - 需要 API Key
    - 数据上传到云端
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model_name: str,
        dimension: int = 1536,
    ):
        self._base_url = base_url
        self._api_key = api_key
        self._model_name = model_name
        self._dimension = dimension
        self._client = None

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model_name(self) -> str:
        return self._model_name

    async def _get_client(self):
        """延迟初始化 OpenAI 客户端"""
        if self._client is not None:
            return self._client

        from openai import AsyncOpenAI
        self._client = AsyncOpenAI(
            base_url=self._base_url,
            api_key=self._api_key,
            timeout=30.0,
        )
        logger.info(f"CloudEmbedding 客户端初始化完成: base_url={self._base_url}, model={self._model_name}")
        return self._client

    async def is_ready(self) -> bool:
        """测试服务是否可用"""
        try:
            await self.embed_text("test")
            return True
        except Exception as e:
            logger.warning(f"CloudEmbedding 不可用: {e}")
            return False

    async def embed_text(self, text: str) -> list[float]:
        """
        向量化单个文本

        Raises:
            ValueError: API 配置错误或请求失败时抛出，包含详细错误信息
        """
        client = await self._get_client()

        try:
            response = await client.embeddings.create(
                model=self._model_name,
                input=text,
            )
            return response.data[0].embedding
        except Exception as e:
            error_msg = str(e)
            logger.error(
                f"CloudEmbedding 请求失败: base_url={self._base_url}, "
                f"model={self._model_name}, error={error_msg}"
            )
            raise ValueError(f"向量化请求失败: {self._format_error(e)}") from e

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """
        批量向量化文本

        Raises:
            ValueError: API 配置错误或请求失败时抛出，包含详细错误信息
        """
        if not texts:
            return []

        client = await self._get_client()

        try:
            response = await client.embeddings.create(
                model=self._model_name,
                input=texts,
            )

            embeddings = sorted(response.data, key=lambda x: x.index)
            return [e.embedding for e in embeddings]
        except Exception as e:
            error_msg = str(e)
            logger.error(
                f"CloudEmbedding 批量请求失败: base_url={self._base_url}, "
                f"model={self._model_name}, count={len(texts)}, error={error_msg}"
            )
            raise ValueError(f"向量化请求失败: {self._format_error(e)}") from e

    async def embed_query(self, query: str) -> list[float]:
        return await self.embed_text(_prepare_query(self.model_name, query))

    def _format_error(self, e: Exception) -> str:
        """
        格式化错误信息，提取用户友好的错误消息

        Args:
            e: 原始异常

        Returns:
            格式化后的错误消息
        """
        error_str = str(e)

        try:
            from openai import APIStatusError, APIConnectionError, AuthenticationError

            if isinstance(e, AuthenticationError):
                return "API Key 无效或已过期，请检查 API Key 是否正确"
            elif isinstance(e, APIStatusError):
                status_code = e.status_code
                if status_code == 404:
                    return f"API 地址不存在 (404)，请检查 Base URL 是否正确（应以 /v1 结尾）"
                elif status_code == 429:
                    return "请求过于频繁，请稍后重试 (429)"
                elif status_code >= 500:
                    return f"服务器错误 ({status_code})，请稍后重试或联系服务商"
                else:
                    # 尝试从错误响应中提取 message
                    try:
                        if hasattr(e, 'response') and e.response is not None:
                            body = e.response.json()
                            if 'error' in body and 'message' in body['error']:
                                return f"错误 {status_code}: {body['error']['message']}"
                    except Exception:
                        pass
                    return f"API 请求失败 (状态码 {status_code})"
            elif isinstance(e, APIConnectionError):
                return "无法连接到 API 服务器，请检查网络连接和 Base URL"
        except ImportError:
            pass

        # 默认返回原始错误消息
        if len(error_str) > 200:
            return error_str[:200] + "..."
        return error_str


class UnconfiguredEmbedding(EmbeddingService):
    """尚未选择有效向量配置时的显式占位实现。

    禁止把厂商示例模型当作实际运行配置，避免“页面配置 A、索引却使用 B”。
    """

    _MESSAGE = "未配置可用的云端 Embedding 模型，请先在管理台保存并启用向量化配置"

    @property
    def dimension(self) -> int:
        return 0

    @property
    def model_name(self) -> str:
        return "未配置"

    async def is_ready(self) -> bool:
        return False

    async def embed_text(self, text: str) -> list[float]:
        raise RuntimeError(self._MESSAGE)

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        raise RuntimeError(self._MESSAGE)


def create_embedding_service() -> EmbeddingService:
    """
    创建云端 Embedding 服务实例。

    缺少完整配置时使用不可用的占位实现；绝不回退到厂商示例模型。
    """
    settings.EMBEDDING_MODE = "cloud"
    base_url = getattr(settings, "EMBEDDING_CLOUD_BASE_URL", "")
    api_key = getattr(settings, "EMBEDDING_CLOUD_API_KEY", "")
    model = getattr(settings, "EMBEDDING_CLOUD_MODEL", "")
    dimension = getattr(settings, "EMBEDDING_CLOUD_DIMENSION", 0)
    if not base_url or not api_key or not model or not dimension:
        logger.warning("云端 Embedding 未配置完整，向量化服务保持不可用状态")
        return UnconfiguredEmbedding()
    logger.info(f"创建云端 Embedding 服务: {model} @ {base_url}")
    return CloudEmbedding(base_url=base_url, api_key=api_key, model_name=model, dimension=dimension)


class EmbeddingServiceProxy(EmbeddingService):
    """
    Embedding 服务代理 —— 支持运行时动态切换内部实现

    使用代理模式解决全局单例引用更新问题：
    - 所有模块导入的是同一个 Proxy 实例
    - 配置变更时只替换 Proxy 内部的 _impl
    - 所有已导入的地方自动使用新的实现

    这避免了 Python 中 from x import y 后重新赋值不生效的问题。
    """

    def __init__(self, initial_impl: EmbeddingService):
        self._impl = initial_impl
        logger.info(f"EmbeddingServiceProxy 初始化完成: {initial_impl.model_name}")

    def switch_to(self, new_impl: EmbeddingService):
        """
        切换到新的 Embedding 服务实现

        Args:
            new_impl: 新的 Embedding 服务实例
        """
        old_name = self._impl.model_name
        self._impl = new_impl
        logger.info(f"已切换 Embedding 服务: {old_name} -> {new_impl.model_name}")

    @property
    def impl(self) -> EmbeddingService:
        """获取当前内部实现（用于需要访问具体实现方法的场景）"""
        return self._impl

    async def embed_text(self, text: str) -> list[float]:
        """将单段文本转为向量"""
        return await self._impl.embed_text(text)

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """批量将文本转为向量"""
        return await self._impl.embed_texts(texts)

    async def embed_query(self, query: str) -> list[float]:
        """使用当前实现的查询向量化规则。"""
        return await self._impl.embed_query(query)

    async def is_ready(self) -> bool:
        """检查服务是否就绪"""
        return await self._impl.is_ready()

    @property
    def dimension(self) -> int:
        """向量维度"""
        return self._impl.dimension

    @property
    def model_name(self) -> str:
        """模型名称"""
        return self._impl.model_name


# 全局 Embedding 服务实例（使用代理模式，支持运行时切换）
embedding_service = EmbeddingServiceProxy(create_embedding_service())
