"""
智答引擎（ZhiDa Engine）—— 向量化（Embedding）厂商模板定义

内置主流云端 Embedding 厂商模板，用户选择厂商后自动填充 base_url、默认模型等字段，
只需手动填入 API Key。同时支持完全自定义配置。
"""

from enum import Enum
from typing import Optional
from dataclasses import dataclass, field


# ============================================================
# 厂商类型枚举
# ============================================================

class EmbeddingProviderCategory(str, Enum):
    """向量化厂商分类"""
    CLOUD = "cloud"      # 云端 API
    CUSTOM = "custom"    # 自定义


# ============================================================
# 厂商模板数据结构
# ============================================================

@dataclass
class EmbeddingProviderTemplate:
    """
    向量化厂商模板

    Attributes:
        provider_id: 厂商唯一标识
        name: 厂商显示名称
        category: 厂商分类（云端/自定义）
        base_url: API 基础地址（OpenAI 兼容格式）
        default_model: 默认推荐模型
        default_dimension: 默认向量维度
        available_models: 可用模型列表 [(model_name, dimension)]
        requires_api_key: 是否需要 API Key
        api_key_label: API Key 字段标签
        icon: 厂商图标（emoji）
        description: 厂商简介
        docs_url: 官方文档链接
    """
    provider_id: str
    name: str
    category: EmbeddingProviderCategory
    base_url: str
    default_model: str
    default_dimension: int = 1536
    available_models: list[tuple[str, int]] = field(default_factory=list)
    requires_api_key: bool = True
    api_key_label: str = "API Key"
    icon: str = "🔧"
    description: str = ""
    docs_url: str = ""


# ============================================================
# 内置厂商模板列表
# ============================================================

BUILTIN_EMBEDDING_PROVIDERS: list[EmbeddingProviderTemplate] = [
    # ---- 云端厂商 ----

    EmbeddingProviderTemplate(
        provider_id="openai",
        name="OpenAI",
        category=EmbeddingProviderCategory.CLOUD,
        base_url="https://api.openai.com/v1",
        default_model="text-embedding-3-small",
        default_dimension=1536,
        available_models=[
            ("text-embedding-3-small", 1536),     # 轻量快速，性价比高
            ("text-embedding-3-large", 3072),     # 大维度，精度更高
            ("text-embedding-ada-002", 1536),     # 经典模型
        ],
        requires_api_key=True,
        api_key_label="OpenAI API Key",
        icon="🤖",
        description="OpenAI 官方 Embedding 服务，英文和多语言场景效果好",
        docs_url="https://platform.openai.com/docs/guides/embeddings",
    ),

    EmbeddingProviderTemplate(
        provider_id="aliyun_bailian",
        name="阿里云百炼",
        category=EmbeddingProviderCategory.CLOUD,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        default_model="text-embedding-v3",
        default_dimension=1024,
        available_models=[
            ("text-embedding-v3", 1024),          # 最新 v3 版本，中文优化
            ("text-embedding-v2", 1536),          # v2 版本
            ("qwen2.5-embedding-instruct", 1024),  # Qwen2.5 指令微调版
        ],
        requires_api_key=True,
        api_key_label="百炼 API Key",
        icon="☁️",
        description="通义千问 Embedding 服务，中文语义理解出色，性价比高",
        docs_url="https://help.aliyun.com/zh/model-studio/getting-started/embeddings",
    ),

    EmbeddingProviderTemplate(
        provider_id="zhipu",
        name="智谱 GLM",
        category=EmbeddingProviderCategory.CLOUD,
        base_url="https://open.bigmodel.cn/api/paas/v4",
        default_model="embedding-3",
        default_dimension=1024,
        available_models=[
            ("embedding-3", 1024),                 # 最新 v3 版本
            ("embedding-2", 1024),                 # v2 版本
        ],
        requires_api_key=True,
        api_key_label="智谱 API Key",
        icon="🎓",
        description="智谱 AI Embedding 服务，GLM 系列，中文场景效果优异",
        docs_url="https://open.bigmodel.cn/dev/api/vector/embedding",
    ),

    EmbeddingProviderTemplate(
        provider_id="moonshot",
        name="月之暗面",
        category=EmbeddingProviderCategory.CLOUD,
        base_url="https://api.moonshot.cn/v1",
        default_model="moonshot-embedding-v1",
        default_dimension=1536,
        available_models=[
            ("moonshot-embedding-v1", 1536),       # Kimi 官方 Embedding
        ],
        requires_api_key=True,
        api_key_label="Kimi API Key",
        icon="🌙",
        description="月之暗面 Kimi Embedding 服务，适合中文长文本场景",
        docs_url="https://platform.moonshot.cn/docs/api/embeddings",
    ),

    EmbeddingProviderTemplate(
        provider_id="bytedance",
        name="字节豆包",
        category=EmbeddingProviderCategory.CLOUD,
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        default_model="doubao-embedding-text-240815",
        default_dimension=1024,
        available_models=[
            ("doubao-embedding-text-240815", 1024), # 豆包 Embedding
        ],
        requires_api_key=True,
        api_key_label="豆包 API Key",
        icon="🫘",
        description="字节跳动豆包 Embedding 服务，中文语义理解出色",
        docs_url="https://www.volcengine.com/docs/82379/1302008",
    ),

    EmbeddingProviderTemplate(
        provider_id="deepseek",
        name="DeepSeek",
        category=EmbeddingProviderCategory.CLOUD,
        base_url="https://api.deepseek.com/v1",
        default_model="deepseek-embedding-v3",
        default_dimension=1024,
        available_models=[
            ("deepseek-embedding-v3", 1024),       # DeepSeek Embedding
        ],
        requires_api_key=True,
        api_key_label="DeepSeek API Key",
        icon="🐳",
        description="DeepSeek 官方 Embedding 服务，开源模型，性价比高",
        docs_url="https://platform.deepseek.com/api-docs/zh-cn/api/embedding",
    ),

    EmbeddingProviderTemplate(
        provider_id="siliconflow",
        name="硅基流动",
        category=EmbeddingProviderCategory.CLOUD,
        base_url="https://api.siliconflow.cn/v1",
        default_model="BAAI/bge-large-zh-v1.5",
        default_dimension=1024,
        available_models=[
            ("BAAI/bge-large-zh-v1.5", 1024),      # BGE 中文大模型
            ("BAAI/bge-m3", 1024),                  # BGE M3 多语言
            ("text-embedding-3-small", 1536),       # OpenAI 同款
        ],
        requires_api_key=True,
        api_key_label="硅基流动 API Key",
        icon="🧪",
        description="硅基流动 AI 推理平台，支持多种开源 Embedding 模型",
        docs_url="https://docs.siliconflow.cn/api-reference/embeddings/create-embeddings",
    ),

    # ---- 自定义 ----

    EmbeddingProviderTemplate(
        provider_id="custom",
        name="自定义",
        category=EmbeddingProviderCategory.CUSTOM,
        base_url="",
        default_model="",
        default_dimension=1536,
        available_models=[],
        requires_api_key=True,
        api_key_label="API Key",
        icon="⚙️",
        description="完全自定义配置，可接入任何兼容 OpenAI Embedding API 格式的服务",
        docs_url="",
    ),
]


# ============================================================
# 厂商模板查询工具函数
# ============================================================

def get_embedding_provider_by_id(provider_id: str) -> Optional[EmbeddingProviderTemplate]:
    """根据厂商 ID 获取模板"""
    for template in BUILTIN_EMBEDDING_PROVIDERS:
        if template.provider_id == provider_id:
            return template
    return None


def get_embedding_providers_by_category(
    category: EmbeddingProviderCategory,
) -> list[EmbeddingProviderTemplate]:
    """按分类获取厂商模板列表"""
    return [t for t in BUILTIN_EMBEDDING_PROVIDERS if t.category == category]


def get_cloud_embedding_providers() -> list[EmbeddingProviderTemplate]:
    """获取所有云端厂商"""
    return get_embedding_providers_by_category(EmbeddingProviderCategory.CLOUD)
