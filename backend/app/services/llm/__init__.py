"""
智答引擎（ZhiDa Engine）—— LLM 厂商模板定义

内置 8 个主流厂商模板 + 1 个自定义模板。
用户选择厂商后自动填充 base_url、默认模型列表等字段，只需手动填入 API Key。
同时支持完全自定义配置，所有字段均可手动输入。
"""

from enum import Enum
from typing import Optional
from dataclasses import dataclass, field


# ============================================================
# 厂商类型枚举
# ============================================================

class ProviderCategory(str, Enum):
    """厂商分类 —— 云端 API 或 本地部署"""
    CLOUD = "cloud"      # 云端 API（需要 API Key）
    LOCAL = "local"      # 本地部署（Ollama 等，无需 API Key）
    CUSTOM = "custom"    # 自定义（用户自行填写所有字段）


# ============================================================
# 厂商模板数据结构
# ============================================================

@dataclass
class ProviderTemplate:
    """
    厂商模板 —— 定义每个 LLM 厂商的默认配置

    Attributes:
        provider_id: 厂商唯一标识（如 "deepseek"、"openai"）
        name: 厂商显示名称（如 "DeepSeek"）
        category: 厂商分类（云端/本地/自定义）
        base_url: API 基础地址（OpenAI 兼容格式）
        default_model: 默认推荐模型
        available_models: 可用模型列表
        requires_api_key: 是否需要 API Key
        api_key_label: API Key 字段标签（如 "DeepSeek API Key"）
        icon: 厂商图标（emoji 或图标名称）
        description: 厂商简介
        docs_url: 官方文档/获取 API Key 的链接
    """
    provider_id: str
    name: str
    category: ProviderCategory
    base_url: str
    default_model: str
    available_models: list[str] = field(default_factory=list)
    requires_api_key: bool = True
    api_key_label: str = "API Key"
    icon: str = "🔧"
    description: str = ""
    docs_url: str = ""


# ============================================================
# 内置厂商模板列表
# 模型版本更新至 2026 年 7 月最新
# ============================================================

BUILTIN_PROVIDER_TEMPLATES: list[ProviderTemplate] = [
    # ---- 云端厂商 ----

    ProviderTemplate(
        provider_id="deepseek",
        name="DeepSeek",
        category=ProviderCategory.CLOUD,
        base_url="https://api.deepseek.com/v1",
        default_model="deepseek-v4-pro",
        available_models=[
            "deepseek-v4-pro",      # 旗舰模型，最强推理能力
            "deepseek-v4-turbo",    # 速度优化版
            "deepseek-v4-lite",     # 轻量版，成本最低
            "deepseek-reasoner",    # 深度推理模型（R1 系列）
        ],
        requires_api_key=True,
        api_key_label="DeepSeek API Key",
        icon="🐳",
        description="国产最强开源模型，性价比极高，中文能力出色",
        docs_url="https://platform.deepseek.com/api_keys",
    ),

    ProviderTemplate(
        provider_id="aliyun_bailian",
        name="阿里云百炼",
        category=ProviderCategory.CLOUD,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        default_model="qwen3.7-max",
        available_models=[
            "qwen3.7-max",          # 旗舰模型，综合能力最强
            "qwen3.7-plus",         # 增强版，高性价比
            "qwen3.7-turbo",        # 速度优化版
            "qwen3.7-coder",        # 代码专用模型
            "qwen-vl-max",          # 多模态视觉模型
            "deepseek-v4-pro",      # 百炼平台也提供 DeepSeek 模型
        ],
        requires_api_key=True,
        api_key_label="百炼 API Key",
        icon="☁️",
        description="阿里云旗下大模型平台，通义千问 Qwen3 系列，中文场景表现优异",
        docs_url="https://bailian.console.aliyun.com/",
    ),

    ProviderTemplate(
        provider_id="openai",
        name="OpenAI",
        category=ProviderCategory.CLOUD,
        base_url="https://api.openai.com/v1",
        default_model="gpt-5.5",
        available_models=[
            "gpt-5.5",              # 最新旗舰模型
            "gpt-5.5-mini",         # 轻量快速版
            "gpt-5",                # 上代旗舰
            "gpt-5-mini",           # 上代轻量版
            "o4-pro",               # 深度推理模型
            "o4-mini",              # 轻量推理模型
        ],
        requires_api_key=True,
        api_key_label="OpenAI API Key",
        icon="🤖",
        description="全球领先的 AI 模型，英文和多语言能力最强",
        docs_url="https://platform.openai.com/api-keys",
    ),

    ProviderTemplate(
        provider_id="anthropic",
        name="Anthropic",
        category=ProviderCategory.CLOUD,
        base_url="https://api.anthropic.com/v1",
        default_model="claude-opus-4.8",
        available_models=[
            "claude-opus-4.8",      # 旗舰模型，最强推理
            "claude-sonnet-4.8",    # 性能均衡版
            "claude-haiku-4.5",     # 最快响应
        ],
        requires_api_key=True,
        api_key_label="Anthropic API Key",
        icon="🧠",
        description="Claude 系列模型，长文本处理和安全性业界领先",
        docs_url="https://console.anthropic.com/",
    ),

    ProviderTemplate(
        provider_id="zhipu",
        name="智谱 GLM",
        category=ProviderCategory.CLOUD,
        base_url="https://open.bigmodel.cn/api/paas/v4",
        default_model="glm-5.2",
        available_models=[
            "glm-5.2",              # 最新旗舰模型
            "glm-5.2-flash",        # 快速响应版
            "glm-5.2-code",         # 代码专用
            "glm-4v-plus",          # 多模态模型
        ],
        requires_api_key=True,
        api_key_label="智谱 API Key",
        icon="🎓",
        description="清华系大模型，GLM-5 系列，中文理解深入，支持多模态",
        docs_url="https://open.bigmodel.cn/",
    ),

    ProviderTemplate(
        provider_id="moonshot",
        name="月之暗面",
        category=ProviderCategory.CLOUD,
        base_url="https://api.moonshot.cn/v1",
        default_model="kimi-k2.7",
        available_models=[
            "kimi-k2.7",            # 最新旗舰模型
            "kimi-k2.7-turbo",      # 速度优化版
            "kimi-k2.5",            # 上代旗舰
        ],
        requires_api_key=True,
        api_key_label="Kimi API Key",
        icon="🌙",
        description="月之暗面 Kimi K2 系列，超长上下文（200K tokens），擅长长文档分析",
        docs_url="https://platform.moonshot.cn/",
    ),

    ProviderTemplate(
        provider_id="bytedance",
        name="字节豆包",
        category=ProviderCategory.CLOUD,
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        default_model="doubao-seed-2-pro",
        available_models=[
            "doubao-seed-2-pro",    # 旗舰模型
            "doubao-seed-2-lite",   # 轻量版
            "doubao-seed-2-vision", # 视觉模型
            "doubao-pro-256k",      # 长上下文版
        ],
        requires_api_key=True,
        api_key_label="豆包 API Key",
        icon="🫘",
        description="字节跳动旗下豆包大模型，性价比高，中文场景优化",
        docs_url="https://console.volcengine.com/ark/",
    ),

    # ---- 本地厂商 ----

    ProviderTemplate(
        provider_id="ollama",
        name="Ollama（本地）",
        category=ProviderCategory.LOCAL,
        base_url="http://localhost:11434/v1",
        default_model="qwen3:14b",
        available_models=[
            "qwen3:14b",            # 通义千问 3 14B 参数，推荐
            "qwen3:7b",             # 7B 参数，轻量快速
            "deepseek-r2:8b",       # DeepSeek R2 8B
            "deepseek-r2:14b",      # DeepSeek R2 14B
            "llama4:8b",            # Meta Llama 4
            "mistral:7b",           # Mistral 7B
            "phi4:14b",             # Microsoft Phi-4
            "gemma3:12b",           # Google Gemma 3
        ],
        requires_api_key=False,
        api_key_label="",
        icon="🖥️",
        description="本地大模型运行平台，完全免费，数据不出机器，需先安装 Ollama",
        docs_url="https://ollama.com/download",
    ),

    # ---- 自定义 ----

    ProviderTemplate(
        provider_id="custom",
        name="自定义",
        category=ProviderCategory.CUSTOM,
        base_url="",  # 用户自行填写
        default_model="",  # 用户自行填写
        available_models=[],  # 用户自行填写
        requires_api_key=True,  # 用户决定
        api_key_label="API Key",
        icon="⚙️",
        description="完全自定义配置，可接入任何兼容 OpenAI API 格式的服务",
        docs_url="",
    ),
]


# ============================================================
# 厂商模板查询工具函数
# ============================================================

def get_provider_by_id(provider_id: str) -> Optional[ProviderTemplate]:
    """根据厂商 ID 获取模板"""
    for template in BUILTIN_PROVIDER_TEMPLATES:
        if template.provider_id == provider_id:
            return template
    return None


def get_providers_by_category(category: ProviderCategory) -> list[ProviderTemplate]:
    """按分类获取厂商模板列表"""
    return [t for t in BUILTIN_PROVIDER_TEMPLATES if t.category == category]


def get_cloud_providers() -> list[ProviderTemplate]:
    """获取所有云端厂商"""
    return get_providers_by_category(ProviderCategory.CLOUD)


def get_local_providers() -> list[ProviderTemplate]:
    """获取所有本地厂商"""
    return get_providers_by_category(ProviderCategory.LOCAL)


def get_all_provider_ids() -> list[str]:
    """获取所有厂商 ID 列表"""
    return [t.provider_id for t in BUILTIN_PROVIDER_TEMPLATES]