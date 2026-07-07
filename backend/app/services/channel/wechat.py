"""
智答引擎（ZhiDa Engine）—— 微信群机器人适配器

基于 Wechaty 实现微信消息收发。
支持普通个人微信（非企业微信）。

使用 Wechaty Puppet 协议接入：
- puppet-padlocal: 本地 Pad 协议
- puppet-wechat: 基于 UOS 微信
- puppet-xp: 基于 WeChatFerry

TODO: 需要用户安装 Wechaty 并配置 Puppet Token
"""

import time
from typing import Optional

from loguru import logger

from app.services.channel.base import (
    ChannelAdapter,
    UnifiedMessage,
    SendMessageRequest,
    SendMessageResult,
    MessageType,
    ChatType,
)


class WeChatAdapter(ChannelAdapter):
    """
    微信群机器人适配器

    基于 Wechaty 实现：
    - 接收群聊/私聊消息
    - 发送文本/图片消息
    - 支持 @ 群成员
    - 支持回复消息

    前置条件：
    1. 安装 Wechaty: npm install -g wechaty
    2. 获取 Puppet Token: https://wechaty.js.org/docs/puppet-services/
    3. 配置 PUPPET_TOKEN 环境变量
    """

    def __init__(self):
        super().__init__()
        self._bot = None
        self._puppet = None

    @property
    def channel_name(self) -> str:
        return "微信"

    async def _do_start(self):
        """启动微信机器人"""
        try:
            # Wechaty 是 Node.js 项目，Python 通过 gRPC 或 HTTP 调用
            # 这里使用 Python Wechaty SDK
            from wechaty import Wechaty, WechatyOptions
            from wechaty.user import Message, Contact, Room

            self._bot = Wechaty()

            # 注册消息处理
            async def on_message(msg: Message):
                """Wechaty 消息回调"""
                raw = {
                    "message_id": msg.message_id,
                    "chat_id": msg.room().room_id if msg.room() else msg.talker().contact_id,
                    "sender_id": msg.talker().contact_id,
                    "sender_name": msg.talker().name,
                    "content": msg.text(),
                    "timestamp": msg.timestamp.timestamp() if msg.timestamp else time.time(),
                    "is_group": msg.room() is not None,
                    "is_mentioned": await msg.mention_self(),
                    "raw_msg": msg,
                }
                await self.handle_raw_message(raw)

            self._bot.on("message", on_message)

            # 启动机器人
            await self._bot.start()

            logger.info("微信群机器人已启动")

        except ImportError:
            logger.warning(
                "Wechaty SDK 未安装，微信群适配器将以模拟模式运行。\n"
                "安装方法: pip install wechaty\n"
                "或使用 HTTP 模式: pip install wechaty[http]"
            )
            self._running = True  # 模拟模式

        except Exception as e:
            logger.error(f"微信群机器人启动失败: {e}")
            raise

    async def _do_stop(self):
        """停止微信机器人"""
        if self._bot:
            try:
                await self._bot.stop()
            except Exception as e:
                logger.warning(f"停止微信机器人异常: {e}")

    async def _do_send(self, request: SendMessageRequest) -> SendMessageResult:
        """发送微信消息"""
        if self._bot is None:
            return SendMessageResult(
                success=False,
                error_message="微信机器人未连接，请确认已启动",
            )

        try:
            from wechaty.user import Contact, Room

            # 构建消息文本
            text = request.content

            # 添加 @ 提及
            if request.mention_ids and request.chat_type == ChatType.GROUP:
                room = await self._bot.Room.find(request.chat_id)
                if room:
                    for uid in request.mention_ids:
                        try:
                            contact = await self._bot.Contact.find(uid)
                            if contact:
                                text = f"@{contact.name} {text}"
                        except Exception:
                            pass

            # 发送消息
            if request.chat_type == ChatType.GROUP:
                room = await self._bot.Room.find(request.chat_id)
                if room:
                    await room.say(text)
                    return SendMessageResult(success=True, message_id="")
            else:
                contact = await self._bot.Contact.find(request.chat_id)
                if contact:
                    await contact.say(text)
                    return SendMessageResult(success=True, message_id="")

            return SendMessageResult(success=False, error_message="未找到会话")

        except Exception as e:
            logger.error(f"发送微信消息失败: {e}")
            return SendMessageResult(success=False, error_message=str(e))

    async def _parse_message(self, raw_message: dict) -> Optional[UnifiedMessage]:
        """将 Wechaty 消息转为统一格式"""
        try:
            is_group = raw_message.get("is_group", False)

            return UnifiedMessage(
                message_id=str(raw_message.get("message_id", "")),
                channel_type="wechat",
                chat_type=ChatType.GROUP if is_group else ChatType.PRIVATE,
                chat_id=str(raw_message.get("chat_id", "")),
                sender_id=str(raw_message.get("sender_id", "")),
                sender_name=str(raw_message.get("sender_name", "未知")),
                content=str(raw_message.get("content", "")),
                message_type=MessageType.TEXT,
                is_mentioned=bool(raw_message.get("is_mentioned", False)),
                timestamp=float(raw_message.get("timestamp", time.time())),
                raw_data=raw_message,
            )
        except Exception as e:
            logger.warning(f"解析微信消息失败: {e}")
            return None


# 注册到适配器工厂
from app.services.channel.base import adapter_factory
try:
    adapter_factory.register("wechat", WeChatAdapter)
except Exception:
    pass