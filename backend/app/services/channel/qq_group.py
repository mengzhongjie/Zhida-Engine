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
        # 模拟模式下的登录状态跟踪
        self._mock_login_step = 0
        self._mock_logged_in = False

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

    async def generate_qrcode(self) -> dict:
        """
        生成 QQ 登录二维码

        使用 NapCat 的 QRCode 登录接口
        """
        import uuid

        login_id = str(uuid.uuid4())
        result = {
            "login_id": login_id,
            "qrcode_url": "",
            "qrcode_content": "",
            "expires_at": time.time() + 300,  # 5分钟过期
        }

        if self._client is None:
            # 模拟模式 - 生成演示用二维码
            self._mock_login_step = 0  # 重置模拟登录步骤
            self._mock_logged_in = False
            result["qrcode_content"] = f"napcat://login?login_id={login_id}"
            result["message"] = "模拟模式：点击确定后将模拟登录成功（演示用）"
            return result

        try:
            # 调用 NapCat 的 QRCode 登录接口
            resp = await self._client.get(f"{self._napcat_url}/get_qrcode")
            if resp.status_code == 200:
                data = resp.json()
                if data.get("retcode") == 0:
                    qr_data = data.get("data", {})
                    result["qrcode_url"] = qr_data.get("qrcode_url", "")
                    result["qrcode_content"] = qr_data.get("qrcode", "")
                    logger.info(f"已生成 QQ 登录二维码: {login_id}")
                else:
                    result["message"] = data.get("msg", "生成二维码失败")
            else:
                result["message"] = f"HTTP {resp.status_code}"
        except Exception as e:
            logger.warning(f"生成 QQ 二维码失败: {e}")
            result["qrcode_content"] = f"napcat://login?login_id={login_id}"
            result["message"] = f"NapCat 未连接: {e}，请确认 NapCat 已启动"

        return result

    async def check_login_status(self, login_id: str) -> dict:
        """
        查询 QQ 登录状态

        NapCat 登录状态：
        - 0: 等待扫码
        - 1: 等待确认
        - 2: 登录成功
        - 3: 二维码过期
        """
        result = {
            "status": "waiting",
            "user_info": {},
            "message": "等待扫码",
        }

        if self._client is None:
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
                    "id": "123456789",
                    "nickname": "模拟QQ用户",
                    "avatar": "",
                }
                self._mock_logged_in = True
            return result

        try:
            resp = await self._client.get(f"{self._napcat_url}/check_qrcode")
            if resp.status_code == 200:
                data = resp.json()
                retcode = data.get("retcode", -1)

                if retcode == 0:
                    qr_data = data.get("data", {})
                    qr_status = qr_data.get("status", 0)

                    if qr_status == 0:
                        result["status"] = "waiting"
                        result["message"] = "等待扫码"
                    elif qr_status == 1:
                        result["status"] = "scanned"
                        result["message"] = "已扫码，请在手机上确认"
                    elif qr_status == 2:
                        result["status"] = "success"
                        result["message"] = "登录成功"
                        # 获取登录信息
                        login_info = await self._get_login_info()
                        result["user_info"] = login_info
                        self._mock_logged_in = True
                    elif qr_status == 3:
                        result["status"] = "expired"
                        result["message"] = "二维码已过期"
                    else:
                        result["status"] = "waiting"
                        result["message"] = f"未知状态: {qr_status}"
                else:
                    result["message"] = data.get("msg", "查询失败")
            else:
                result["message"] = f"HTTP {resp.status_code}"
        except Exception as e:
            logger.warning(f"查询 QQ 登录状态失败: {e}")
            result["status"] = "waiting"
            result["message"] = f"查询失败: {e}"

        return result

    async def _get_login_info(self) -> dict:
        """获取当前登录用户信息"""
        if self._client is None:
            return {}

        try:
            resp = await self._client.get(f"{self._napcat_url}/get_login_info")
            if resp.status_code == 200:
                data = resp.json()
                if data.get("retcode") == 0:
                    user_data = data.get("data", {})
                    return {
                        "id": str(user_data.get("user_id", "")),
                        "nickname": user_data.get("nickname", ""),
                        "avatar": f"http://q1.qlogo.cn/g?b=qq&nk={user_data.get('user_id', '')}&s=100",
                    }
        except Exception as e:
            logger.warning(f"获取登录信息失败: {e}")

        return {}

    async def get_contact_list(self) -> dict:
        """
        获取 QQ 群聊和好友列表

        使用 NapCat API:
        - get_group_list: 获取群列表
        - get_friend_list: 获取好友列表
        """
        result = {"groups": [], "friends": []}

        if self._client is None:
            # 模拟模式 - 返回模拟数据
            result["groups"] = [
                {"id": "10001", "name": "技术交流群", "member_count": 256, "avatar": ""},
                {"id": "10002", "name": "产品讨论组", "member_count": 48, "avatar": ""},
                {"id": "10003", "name": "AI 学习群", "member_count": 512, "avatar": ""},
            ]
            result["friends"] = [
                {"id": "20001", "nickname": "张三", "remark": "产品经理", "avatar": ""},
                {"id": "20002", "nickname": "李四", "remark": "开发同学", "avatar": ""},
                {"id": "20003", "nickname": "王五", "remark": "", "avatar": ""},
            ]
            return result

        try:
            # 获取群列表
            resp = await self._client.get(f"{self._napcat_url}/get_group_list")
            if resp.status_code == 200:
                data = resp.json()
                if data.get("retcode") == 0:
                    groups = data.get("data", [])
                    result["groups"] = [
                        {
                            "id": str(g.get("group_id", "")),
                            "name": g.get("group_name", ""),
                            "member_count": g.get("member_count", 0),
                            "avatar": f"https://p.qlogo.cn/gh/{g.get('group_id', '')}/{g.get('group_id', '')}/100",
                        }
                        for g in groups
                    ]

            # 获取好友列表
            resp = await self._client.get(f"{self._napcat_url}/get_friend_list")
            if resp.status_code == 200:
                data = resp.json()
                if data.get("retcode") == 0:
                    friends = data.get("data", [])
                    result["friends"] = [
                        {
                            "id": str(f.get("user_id", "")),
                            "nickname": f.get("nickname", ""),
                            "remark": f.get("remark", ""),
                            "avatar": f"http://q1.qlogo.cn/g?b=qq&nk={f.get('user_id', '')}&s=100",
                        }
                        for f in friends
                    ]

            logger.info(f"获取 QQ 联系人列表: {len(result['groups'])} 个群, {len(result['friends'])} 个好友")
        except Exception as e:
            logger.error(f"获取 QQ 联系人列表失败: {e}")

        return result

    async def get_group_member_list(self, group_id: str) -> list[dict]:
        """
        获取 QQ 群成员列表

        使用 NapCat API: get_group_member_list
        """
        if self._client is None:
            # 模拟模式
            return [
                {"user_id": "10001", "nickname": "群主大人", "card": "群主", "role": "owner", "avatar": "", "join_time": 0},
                {"user_id": "10002", "nickname": "管理员A", "card": "管理员", "role": "admin", "avatar": "", "join_time": 0},
                {"user_id": "10003", "nickname": "成员甲", "card": "小甲", "role": "member", "avatar": "", "join_time": 0},
                {"user_id": "10004", "nickname": "成员乙", "card": "小乙", "role": "member", "avatar": "", "join_time": 0},
                {"user_id": "10005", "nickname": "成员丙", "card": "", "role": "member", "avatar": "", "join_time": 0},
            ]

        try:
            resp = await self._client.post(
                f"{self._napcat_url}/get_group_member_list",
                json={"group_id": int(group_id) if group_id.isdigit() else group_id},
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("retcode") == 0:
                    members = data.get("data", [])
                    return [
                        {
                            "user_id": str(m.get("user_id", "")),
                            "nickname": m.get("nickname", ""),
                            "card": m.get("card", ""),
                            "role": m.get("role", "member"),
                            "avatar": f"http://q1.qlogo.cn/g?b=qq&nk={m.get('user_id', '')}&s=100",
                            "join_time": m.get("join_time", 0),
                        }
                        for m in members
                    ]
        except Exception as e:
            logger.error(f"获取群成员列表失败: {e}")

        return []


# 注册到适配器工厂
from app.services.channel.base import adapter_factory
try:
    adapter_factory.register("qq", QQAdapter)
except Exception:
    pass