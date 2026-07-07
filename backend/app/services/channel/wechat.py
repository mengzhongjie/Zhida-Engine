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
        # 模拟模式下的登录状态跟踪
        self._mock_login_step = 0
        self._mock_logged_in = False

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

    async def generate_qrcode(self) -> dict:
        """
        生成微信登录二维码

        基于 Wechaty 的扫码登录机制
        """
        import uuid

        login_id = str(uuid.uuid4())
        result = {
            "login_id": login_id,
            "qrcode_url": "",
            "qrcode_content": "",
            "expires_at": time.time() + 300,  # 5分钟过期
        }

        if self._bot is None:
            # 模拟模式 - 生成演示用二维码
            self._mock_login_step = 0  # 重置模拟登录步骤
            self._mock_logged_in = False
            result["qrcode_content"] = f"wechat://login?login_id={login_id}"
            result["message"] = "模拟模式：将自动模拟登录成功（演示用）"
            return result

        try:
            # Wechaty 通过 scan 事件获取二维码
            # 这里返回登录入口，具体二维码由 Wechaty 内部管理
            result["message"] = "微信登录中，请在弹出的浏览器窗口中扫码"
            logger.info(f"已生成微信登录二维码: {login_id}")
        except Exception as e:
            logger.warning(f"生成微信二维码失败: {e}")
            result["message"] = f"登录失败: {e}"

        return result

    async def check_login_status(self, login_id: str) -> dict:
        """
        查询微信登录状态

        Wechaty 登录状态：
        - waiting: 等待扫码
        - scanned: 已扫码
        - confirmed: 已确认登录
        - success: 登录成功
        """
        result = {
            "status": "waiting",
            "user_info": {},
            "message": "等待扫码",
        }

        if self._bot is None:
            # 模拟模式 - 自动推进登录状态
            self._mock_login_step += 1
            if self._mock_login_step <= 2:
                result["status"] = "waiting"
                result["message"] = "模拟模式：等待扫码（演示用，自动推进）"
            elif self._mock_login_step <= 4:
                result["status"] = "scanned"
                result["message"] = "模拟模式：已扫码，等待确认（演示用）"
            elif self._mock_login_step == 5:
                result["status"] = "confirmed"
                result["message"] = "模拟模式：已确认登录（演示用）"
            else:
                result["status"] = "success"
                result["message"] = "模拟模式：登录成功（演示用）"
                result["user_info"] = {
                    "id": "wxid_abc123",
                    "nickname": "模拟微信用户",
                    "avatar": "",
                }
                self._mock_logged_in = True
            return result

        try:
            # 通过 Wechaty 实例状态判断
            if hasattr(self._bot, 'user') and self._bot.user:
                result["status"] = "success"
                result["message"] = "登录成功"
                result["user_info"] = {
                    "id": str(self._bot.user.contact_id),
                    "nickname": str(self._bot.user.name),
                    "avatar": "",
                }
                self._mock_logged_in = True
            else:
                result["status"] = "waiting"
                result["message"] = "等待扫码登录"
        except Exception as e:
            logger.warning(f"查询微信登录状态失败: {e}")
            result["message"] = f"查询失败: {e}"

        return result

    async def get_contact_list(self) -> dict:
        """
        获取微信群聊和好友列表

        使用 Wechaty API:
        - Room.find_all(): 获取群列表
        - Contact.find_all(): 获取好友列表
        """
        result = {"groups": [], "friends": []}

        if self._bot is None:
            # 模拟模式 - 返回模拟数据
            result["groups"] = [
                {"id": "wx_group_001", "name": "技术交流群", "member_count": 128, "avatar": ""},
                {"id": "wx_group_002", "name": "产品讨论组", "member_count": 36, "avatar": ""},
                {"id": "wx_group_003", "name": "AI 学习群", "member_count": 256, "avatar": ""},
            ]
            result["friends"] = [
                {"id": "wx_friend_001", "nickname": "张三", "remark": "产品经理", "avatar": ""},
                {"id": "wx_friend_002", "nickname": "李四", "remark": "开发同学", "avatar": ""},
                {"id": "wx_friend_003", "nickname": "王五", "remark": "", "avatar": ""},
            ]
            return result

        try:
            from wechaty.user import Contact, Room

            # 获取群列表
            rooms = await self._bot.Room.find_all()
            result["groups"] = []
            for room in rooms:
                try:
                    topic = await room.topic()
                    member_count = len(await room.member_list())
                    result["groups"].append({
                        "id": str(room.room_id),
                        "name": str(topic),
                        "member_count": member_count,
                        "avatar": "",
                    })
                except Exception:
                    pass

            # 获取好友列表
            contacts = await self._bot.Contact.find_all()
            result["friends"] = []
            for contact in contacts:
                try:
                    if contact.is_friend():
                        result["friends"].append({
                            "id": str(contact.contact_id),
                            "nickname": str(contact.name),
                            "remark": str(await contact.alias() or ""),
                            "avatar": "",
                        })
                except Exception:
                    pass

            logger.info(f"获取微信联系人列表: {len(result['groups'])} 个群, {len(result['friends'])} 个好友")
        except Exception as e:
            logger.error(f"获取微信联系人列表失败: {e}")

        return result

    async def get_group_member_list(self, group_id: str) -> list[dict]:
        """
        获取微信群成员列表

        使用 Wechaty API: Room.member_list()
        """
        if self._bot is None:
            # 模拟模式
            return [
                {"user_id": "wx_user_001", "nickname": "群主大人", "card": "群主", "role": "owner", "avatar": "", "join_time": 0},
                {"user_id": "wx_user_002", "nickname": "管理员A", "card": "管理员", "role": "admin", "avatar": "", "join_time": 0},
                {"user_id": "wx_user_003", "nickname": "成员甲", "card": "小甲", "role": "member", "avatar": "", "join_time": 0},
                {"user_id": "wx_user_004", "nickname": "成员乙", "card": "小乙", "role": "member", "avatar": "", "join_time": 0},
                {"user_id": "wx_user_005", "nickname": "成员丙", "card": "", "role": "member", "avatar": "", "join_time": 0},
            ]

        try:
            from wechaty.user import Room

            room = await self._bot.Room.find(group_id)
            if room:
                members = await room.member_list()
                result = []
                for member in members:
                    try:
                        # 判断角色（群主/管理员）
                        role = "member"
                        is_owner = await room.is_owner(member)
                        if is_owner:
                            role = "owner"
                        # Wechaty 没有直接的 admin 判断，需要根据实际情况

                        result.append({
                            "user_id": str(member.contact_id),
                            "nickname": str(member.name),
                            "card": str(await room.alias(member) or ""),
                            "role": role,
                            "avatar": "",
                            "join_time": 0,
                        })
                    except Exception:
                        pass
                return result
        except Exception as e:
            logger.error(f"获取微信群成员列表失败: {e}")

        return []


# 注册到适配器工厂
from app.services.channel.base import adapter_factory
try:
    adapter_factory.register("wechat", WeChatAdapter)
except Exception:
    pass