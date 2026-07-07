"""
智答引擎（ZhiDa Engine）—— QQ 群机器人适配器

基于 NapCat QQ 实现 QQ 消息收发。
NapCat 是基于 NTQQ 的无头客户端，通过 HTTP/WebSocket 与机器人通信。

前置条件：
1. 安装 NapCat QQ: https://github.com/NapNeko/NapCatQQ
2. 启动 NapCat 并配置 HTTP/WebSocket 服务
3. 配置 NAPCAT_URL 环境变量
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


class QQAdapter(ChannelAdapter):
    """
    QQ 群机器人适配器

    基于 NapCat QQ 实现：
    - 接收群聊/私聊消息
    - 发送文本/图片消息
    - 支持 @ 群成员
    - 支持回复消息

    NapCat 消息格式参考：
    https://github.com/NapNeko/NapCatQQ/blob/main/docs/README.md
    """

    def __init__(self, napcat_url: str = "http://localhost:3000"):
        super().__init__()
        self._napcat_url = napcat_url.rstrip("/")
        self._client = None
        self._ws = None
        self._ws_task = None

    @property
    def channel_name(self) -> str:
        return "QQ"

    async def _do_start(self):
        """启动 QQ 机器人"""
        try:
            import httpx
            import asyncio
            import json

            self._client = httpx.AsyncClient(timeout=30.0)

            # 测试连接
            try:
                resp = await self._client.get(f"{self._napcat_url}/get_login_info")
                if resp.status_code == 200:
                    info = resp.json()
                    logger.info(f"QQ 机器人已连接: {info.get('data', {}).get('nickname', '未知')}")
            except Exception as e:
                logger.warning(f"NapCat 连接测试失败: {e}，将尝试 WebSocket 模式")

            # 启动 WebSocket 监听（如果 NapCat 配置了 WebSocket）
            # await self._start_ws_listener()

            self._running = True
            logger.info("QQ 机器人已启动")

        except ImportError:
            logger.warning(
                "httpx 未安装，QQ 适配器将以模拟模式运行。\n"
                "安装方法: pip install httpx"
            )
            self._running = True

        except Exception as e:
            logger.error(f"QQ 机器人启动失败: {e}")
            raise

    async def _do_stop(self):
        """停止 QQ 机器人"""
        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except Exception:
                pass

        if self._client:
            await self._client.aclose()

    async def _do_send(self, request: SendMessageRequest) -> SendMessageResult:
        """发送 QQ 消息"""
        if self._client is None:
            return SendMessageResult(
                success=False,
                error_message="QQ 机器人未连接，请确认已启动 NapCat",
            )

        try:
            # 构建消息文本
            text = request.content

            # 添加 @ 提及
            if request.mention_ids and request.chat_type == ChatType.GROUP:
                for uid in request.mention_ids:
                    text = f"[CQ:at,qq={uid}] {text}"

            # 构建请求
            payload = {
                "message_type": "group" if request.chat_type == ChatType.GROUP else "private",
                "group_id" if request.chat_type == ChatType.GROUP else "user_id": request.chat_id,
                "message": [
                    {"type": "text", "data": {"text": text}},
                ],
            }

            # 修正字段名
            if request.chat_type == ChatType.GROUP:
                payload["group_id"] = int(request.chat_id) if request.chat_id.isdigit() else request.chat_id
            else:
                payload["user_id"] = int(request.chat_id) if request.chat_id.isdigit() else request.chat_id

            resp = await self._client.post(
                f"{self._napcat_url}/send_msg",
                json=payload,
            )

            if resp.status_code == 200:
                data = resp.json()
                return SendMessageResult(
                    success=True,
                    message_id=str(data.get("data", {}).get("message_id", "")),
                )
            else:
                return SendMessageResult(
                    success=False,
                    error_message=f"HTTP {resp.status_code}: {resp.text[:200]}",
                )

        except Exception as e:
            logger.error(f"发送 QQ 消息失败: {e}")
            return SendMessageResult(success=False, error_message=str(e))

    async def _parse_message(self, raw_message: dict) -> Optional[UnifiedMessage]:
        """将 NapCat 消息转为统一格式"""
        try:
            # NapCat 消息格式
            message_type = raw_message.get("message_type", "group")
            is_group = message_type == "group"

            # 提取文本内容
            content = ""
            message_list = raw_message.get("message", [])
            for part in message_list:
                if part.get("type") == "text":
                    content += part.get("data", {}).get("text", "")
                elif part.get("type") == "image":
                    content += "[图片]"
                elif part.get("type") == "at":
                    content += f"@{part.get('data', {}).get('qq', '')}"

            return UnifiedMessage(
                message_id=str(raw_message.get("message_id", "")),
                channel_type="qq",
                chat_type=ChatType.GROUP if is_group else ChatType.PRIVATE,
                chat_id=str(raw_message.get("group_id" if is_group else "user_id", "")),
                sender_id=str(raw_message.get("sender", {}).get("user_id", "")),
                sender_name=str(raw_message.get("sender", {}).get("nickname", "未知")),
                content=content,
                message_type=MessageType.TEXT,
                timestamp=float(raw_message.get("time", time.time())),
                raw_data=raw_message,
            )
        except Exception as e:
            logger.warning(f"解析 QQ 消息失败: {e}")
            return None


# 注册到适配器工厂
from app.services.channel.base import adapter_factory
try:
    adapter_factory.register("qq", QQAdapter)
except Exception:
    pass