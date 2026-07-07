"""
智答引擎（ZhiDa Engine）—— 统一消息协议 + 适配器基类

定义渠道无关的消息协议，所有渠道适配器（微信/QQ/其他）都实现此接口。
新渠道只需实现 ChannelAdapter 抽象类即可接入。

设计原则：
- 统一消息格式：所有渠道的消息转为标准 ChatMessage
- 统一发送接口：发送消息时自动适配渠道格式
- 插件化：新增渠道只需实现适配器，无需修改核心逻辑
"""

from abc import ABC, abstractmethod
from typing import Optional, Callable, Awaitable, Any
from dataclasses import dataclass, field
from enum import Enum

from loguru import logger


# ============================================================
# 统一消息协议
# ============================================================

class MessageType(str, Enum):
    """消息类型"""
    TEXT = "text"           # 文本消息
    IMAGE = "image"         # 图片消息
    FILE = "file"           # 文件消息
    VOICE = "voice"         # 语音消息
    VIDEO = "video"         # 视频消息
    SYSTEM = "system"       # 系统消息（入群/退群等）
    UNKNOWN = "unknown"     # 未知类型


class ChatType(str, Enum):
    """聊天类型"""
    PRIVATE = "private"     # 私聊
    GROUP = "group"         # 群聊
    CHANNEL = "channel"     # 频道


@dataclass
class UnifiedMessage:
    """
    统一消息格式 —— 所有渠道的消息都转为此格式

    渠道适配器负责将原始消息转换为此格式，
    核心业务逻辑只处理此格式。
    """
    # 消息标识
    message_id: str                          # 消息唯一 ID
    channel_type: str                        # 渠道类型: wechat/qq
    chat_type: ChatType                      # 聊天类型: private/group

    # 会话信息
    chat_id: str                             # 群聊/私聊 ID

    # 发送者信息
    sender_id: str                           # 发送者 ID（必须在有默认值字段之前）

    # 以下是有默认值的字段
    chat_name: str = ""                      # 群聊/私聊名称
    sender_name: str = ""                    # 发送者名称
    sender_avatar: str = ""                  # 发送者头像

    # 消息内容
    message_type: MessageType = MessageType.TEXT
    content: str = ""                        # 文本内容
    image_url: str = ""                      # 图片 URL
    file_url: str = ""                       # 文件 URL
    file_name: str = ""                      # 文件名

    # 引用/回复
    reply_to_message_id: str = ""            # 被回复的消息 ID
    reply_to_content: str = ""               # 被回复的消息内容

    # 提及
    mentioned_ids: list[str] = field(default_factory=list)  # 被 @ 的用户 ID 列表
    is_mentioned: bool = False               # 机器人是否被 @

    # 时间戳
    timestamp: float = 0.0                   # 消息时间戳

    # 原始消息（调试用）
    raw_data: dict = field(default_factory=dict)


@dataclass
class SendMessageRequest:
    """发送消息请求"""
    chat_id: str                             # 目标群聊/私聊 ID
    chat_type: ChatType                      # 聊天类型
    content: str                             # 消息内容
    reply_to_message_id: str = ""            # 回复的消息 ID
    mention_ids: list[str] = field(default_factory=list)  # 要 @ 的用户 ID 列表
    image_url: str = ""                      # 图片 URL
    file_url: str = ""                       # 文件 URL


@dataclass
class SendMessageResult:
    """发送消息结果"""
    success: bool
    message_id: str = ""
    error_message: str = ""


# ============================================================
# 渠道适配器基类
# ============================================================

class ChannelAdapter(ABC):
    """
    渠道适配器基类 —— 所有渠道适配器的抽象接口

    子类必须实现：
    - _do_start(): 启动渠道连接
    - _do_stop(): 停止渠道连接
    - _do_send(): 发送消息
    - _parse_message(): 将原始消息转为 UnifiedMessage

    子类可选实现：
    - get_channel_info(): 获取渠道信息
    - get_group_members(): 获取群成员列表
    """

    def __init__(self):
        self._running = False
        self._message_handler: Optional[Callable[[UnifiedMessage], Awaitable[None]]] = None

    # ================================================================
    # 公共接口
    # ================================================================

    async def start(self, message_handler: Callable[[UnifiedMessage], Awaitable[None]]):
        """
        启动渠道适配器

        Args:
            message_handler: 消息处理回调，收到消息后调用
        """
        if self._running:
            logger.warning(f"{self.channel_name} 适配器已在运行")
            return

        self._message_handler = message_handler
        await self._do_start()
        self._running = True
        logger.info(f"{self.channel_name} 适配器已启动")

    async def stop(self):
        """停止渠道适配器"""
        if not self._running:
            return

        await self._do_stop()
        self._running = False
        self._message_handler = None
        logger.info(f"{self.channel_name} 适配器已停止")

    async def send(self, request: SendMessageRequest) -> SendMessageResult:
        """
        发送消息

        Args:
            request: 发送消息请求

        Returns:
            发送结果
        """
        if not self._running:
            return SendMessageResult(success=False, error_message="适配器未启动")

        try:
            return await self._do_send(request)
        except Exception as e:
            logger.error(f"{self.channel_name} 发送消息失败: {e}")
            return SendMessageResult(success=False, error_message=str(e))

    async def handle_raw_message(self, raw_message: dict):
        """
        处理原始消息 —— 由渠道 SDK 回调触发

        流程：
        1. 解析原始消息为 UnifiedMessage
        2. 调用 message_handler 回调

        Args:
            raw_message: 渠道 SDK 的原始消息
        """
        try:
            # 解析消息
            unified = await self._parse_message(raw_message)
            if unified is None:
                return

            # 调用回调
            if self._message_handler:
                await self._message_handler(unified)

        except Exception as e:
            logger.error(f"{self.channel_name} 消息处理异常: {e}")

    # ================================================================
    # 子类必须实现的方法
    # ================================================================

    @abstractmethod
    async def _do_start(self):
        """启动渠道连接 —— 子类实现"""
        ...

    @abstractmethod
    async def _do_stop(self):
        """停止渠道连接 —— 子类实现"""
        ...

    @abstractmethod
    async def _do_send(self, request: SendMessageRequest) -> SendMessageResult:
        """发送消息 —— 子类实现"""
        ...

    @abstractmethod
    async def _parse_message(self, raw_message: dict) -> Optional[UnifiedMessage]:
        """将原始消息转为 UnifiedMessage —— 子类实现"""
        ...

    # ================================================================
    # 属性
    # ================================================================

    @property
    @abstractmethod
    def channel_name(self) -> str:
        """渠道名称"""
        ...

    @property
    def is_running(self) -> bool:
        """是否正在运行"""
        return self._running

    # ================================================================
    # 可选实现
    # ================================================================

    async def get_channel_info(self) -> dict:
        """获取渠道信息（可选实现）"""
        return {"channel": self.channel_name, "status": "running" if self._running else "stopped"}

    async def get_group_members(self, chat_id: str) -> list[dict]:
        """获取群成员列表（可选实现）"""
        logger.warning(f"{self.channel_name} 不支持获取群成员列表")
        return []

    async def generate_qrcode(self) -> dict:
        """
        生成登录二维码（可选实现）

        Returns:
            {
                "login_id": "登录会话ID",
                "qrcode_url": "二维码图片URL或base64",
                "qrcode_content": "二维码内容",
                "expires_at": 过期时间戳
            }
        """
        logger.warning(f"{self.channel_name} 不支持扫码登录")
        return {}

    async def check_login_status(self, login_id: str) -> dict:
        """
        查询登录状态（可选实现）

        Args:
            login_id: 登录会话ID

        Returns:
            {
                "status": "waiting" | "scanned" | "confirmed" | "expired" | "success",
                "user_info": {
                    "id": "用户ID",
                    "nickname": "昵称",
                    "avatar": "头像URL"
                },
                "message": "状态说明"
            }
        """
        logger.warning(f"{self.channel_name} 不支持查询登录状态")
        return {"status": "unsupported", "message": "渠道不支持登录状态查询"}

    async def get_contact_list(self) -> dict:
        """
        获取联系人列表（群聊 + 好友）（可选实现）

        Returns:
            {
                "groups": [
                    {"id": "群ID", "name": "群名称", "member_count": 成员数, "avatar": "头像"}
                ],
                "friends": [
                    {"id": "好友ID", "nickname": "昵称", "remark": "备注", "avatar": "头像"}
                ]
            }
        """
        logger.warning(f"{self.channel_name} 不支持获取联系人列表")
        return {"groups": [], "friends": []}

    async def get_group_member_list(self, group_id: str) -> list[dict]:
        """
        获取群成员列表（可选实现，比 get_group_members 更详细）

        Args:
            group_id: 群ID

        Returns:
            [
                {
                    "user_id": "用户ID",
                    "nickname": "昵称",
                    "card": "群名片",
                    "role": "角色(owner/admin/member)",
                    "avatar": "头像",
                    "join_time": 加入时间
                }
            ]
        """
        logger.warning(f"{self.channel_name} 不支持获取群成员列表")
        return []


# ============================================================
# 适配器工厂
# ============================================================

class ChannelAdapterFactory:
    """
    渠道适配器工厂 —— 根据渠道类型创建适配器（单例模式）

    Usage:
        factory = ChannelAdapterFactory()

        # 注册适配器
        factory.register("wechat", WeChatAdapter)

        # 获取适配器（单例）
        adapter = factory.create("wechat")
    """

    def __init__(self):
        self._adapter_classes: dict[str, type[ChannelAdapter]] = {}
        self._instances: dict[str, ChannelAdapter] = {}

    def register(self, channel_type: str, adapter_class: type[ChannelAdapter]):
        """注册适配器类"""
        self._adapter_classes[channel_type] = adapter_class
        logger.info(f"注册渠道适配器: {channel_type}")

    def create(self, channel_type: str) -> Optional[ChannelAdapter]:
        """获取适配器实例（单例模式）"""
        if channel_type in self._instances:
            return self._instances[channel_type]

        adapter_class = self._adapter_classes.get(channel_type)
        if adapter_class is None:
            logger.error(f"未找到渠道适配器: {channel_type}")
            return None

        instance = adapter_class()
        self._instances[channel_type] = instance
        logger.info(f"创建渠道适配器实例: {channel_type}")
        return instance

    def get_supported_channels(self) -> list[str]:
        """获取支持的渠道列表"""
        return list(self._adapter_classes.keys())


# 全局适配器工厂
adapter_factory = ChannelAdapterFactory()

# 导入内置适配器，触发自动注册
from app.services.channel.wechat import WeChatAdapter
from app.services.channel.qq_group import QQAdapter