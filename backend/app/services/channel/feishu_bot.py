"""飞书官方机器人渠道：长连接接收群消息 → Agent 问答 → 引用回复。

设计要点（与 QQ 机器人 Gateway 同构）：
- 使用飞书官方 WebSocket 长连接（lark-oapi SDK），无需公网回调地址；
- SDK 在线程内运行，事件回调把消息调度到该线程事件循环处理；
- 配置存 feishu_bot_configs，群绑定存 feishu_chat_bindings（chat_id ↔ agent_id）。
"""
import asyncio
import json
import re
import threading
import time

import httpx
from loguru import logger
from sqlalchemy import select

from app.core.database import async_session_factory
from app.core.security import decrypt_api_key
from app.models.agent import Agent
from app.models.agent_knowledge_base import AgentKnowledgeBase
from app.models.feishu_bot import FeishuBotConfig, FeishuChatBinding
from app.models.knowledge import KnowledgeBase
from app.models.qa import QAHistory
from app.services.cache.rate_limiter import rate_limiter, RateLimitResult
from app.services.channel.utils import plain_text
from app.services.qa.generator import answer_generator

_FEISHU_API = "https://open.feishu.cn/open-apis"
_TOKEN_URL = f"{_FEISHU_API}/auth/v3/tenant_access_token/internal"
_BOT_INFO_URL = f"{_FEISHU_API}/bot/v3/info"
_CHAT_LIST_URL = f"{_FEISHU_API}/im/v1/chats"

_AT_RE = re.compile(r"@_user_?\d+")
_AT_XML_RE = re.compile(r"<at[^>]*>.*?</at>")


def _clean_mention(content: str) -> str:
    """去掉消息文本中的 @ 占位（@_user_1 或 <at>..</at>）。"""
    text = _AT_RE.sub("", content or "")
    text = _AT_XML_RE.sub("", text)
    return text.strip()


class FeishuBotService:
    def __init__(self):
        self._thread: threading.Thread | None = None
        self._ws = None
        self._stopping = False
        self._app_id = ""
        self._app_secret = ""
        self._bot_open_id = ""
        self._seen: dict[str, float] = {}
        self._token_cache: dict[str, tuple[str, float]] = {}
        self._send_lock = asyncio.Semaphore(4)
        self._handle_sem = asyncio.Semaphore(8)

    # ---------------------------------------------------------------- 凭据
    async def _credentials(self):
        """机器人凭据：优先独立配置（feishu_bot_configs），未配置时复用云文档导入的飞书应用（feishu_configs）。"""
        async with async_session_factory() as db:
            bot = await db.get(FeishuBotConfig, 1)
            if bot and bot.app_id and bot.app_secret:
                return bot.app_id, decrypt_api_key(bot.app_secret), "bot"
            from app.models.feishu_config import FeishuConfig
            cloud = await db.get(FeishuConfig, 1)
            if cloud and cloud.app_id and cloud.app_secret:
                return cloud.app_id, decrypt_api_key(cloud.app_secret), "cloud"
            return None

    async def config_status(self) -> dict:
        """管理台展示用：机器人独立配置 + 实际生效凭据来源。"""
        async with async_session_factory() as db:
            bot = await db.get(FeishuBotConfig, 1)
            bot_enabled = bool(bot and bot.enabled)
            bot_app_id = (bot.app_id if bot else "") or ""
            bot_configured = bool(bot and bot.app_id and bot.app_secret)
            from app.models.feishu_config import FeishuConfig
            cloud = await db.get(FeishuConfig, 1)
            cloud_configured = bool(cloud and cloud.app_id and cloud.app_secret)
        creds = await self._credentials()
        return {
            "enabled": bot_enabled,
            "app_id": bot_app_id,
            "effective_app_id": creds[0] if creds else "",
            "use_cloud_config": bool(not bot_configured and cloud_configured),
        }

    async def _tenant_token(self, app_id: str, secret: str) -> str:
        cached = self._token_cache.get(app_id)
        if cached and time.time() < cached[1] - 60:
            return cached[0]
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(_TOKEN_URL, json={"app_id": app_id, "app_secret": secret})
            r.raise_for_status()
            body = r.json()
            if body.get("code") != 0 or not body.get("tenant_access_token"):
                raise RuntimeError(f"飞书 tenant_access_token 获取失败: {body.get('msg') or body.get('code')}")
            token = body["tenant_access_token"]
            self._token_cache[app_id] = (token, time.time() + float(body.get("expire", 7200)))
            return token

    async def test_credentials(self, app_id: str, secret: str) -> tuple[bool, str]:
        try:
            token = await self._tenant_token(app_id, secret)
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(_BOT_INFO_URL, headers={"Authorization": f"Bearer {token}"})
                r.raise_for_status()
                body = r.json()
                if body.get("code") != 0:
                    return False, f"飞书返回错误：{body.get('msg') or body.get('code')}"
            return True, "ok"
        except Exception as exc:
            return False, f"飞书凭据测试失败：{str(exc)[:180]}"

    async def bot_info(self, app_id: str, secret: str) -> dict:
        """机器人基本信息（open_id / 名称），用于 @ 校验与展示。"""
        token = await self._tenant_token(app_id, secret)
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(_BOT_INFO_URL, headers={"Authorization": f"Bearer {token}"})
            r.raise_for_status()
            return r.json().get("data") or {}

    async def list_chats(self, app_id: str, secret: str) -> list[dict]:
        """机器人已加入的群列表（chat_id + 名称），供管理台绑定选择。"""
        token = await self._tenant_token(app_id, secret)
        chats: list[dict] = []
        page_token = ""
        while True:
            params: dict = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(_CHAT_LIST_URL, headers={"Authorization": f"Bearer {token}"}, params=params)
                r.raise_for_status()
                body = r.json()
                if body.get("code") != 0:
                    logger.warning("飞书群列表获取失败: code={} msg={} http={}", body.get("code"), body.get("msg"), r.status_code)
                    raise RuntimeError(f"群列表获取失败：{body.get('msg') or body.get('code')}")
                data = body.get("data") or {}
                items = data.get("items") or []
                logger.info("飞书群列表响应: items={} has_more={} first={}", len(items), data.get("has_more"), (items[0].get("chat_id") if items else None))
                for item in items:
                    chats.append({"chat_id": item.get("chat_id"), "name": item.get("name") or ""})
                page_token = data.get("page_token") or ""
                if not data.get("has_more"):
                    break
        return chats

    # ---------------------------------------------------------------- 生命周期
    async def start(self):
        if self._thread and self._thread.is_alive():
            return
        async with async_session_factory() as db:
            bot = await db.get(FeishuBotConfig, 1)
            if not (bot and bot.enabled):
                return
        creds = await self._credentials()
        if not creds:
            return
        self._app_id, self._app_secret, _ = creds
        self._stopping = False
        try:
            info = await self.bot_info(self._app_id, self._app_secret)
            self._bot_open_id = info.get("open_id") or ""
        except Exception as exc:
            logger.warning("获取飞书机器人信息失败（@ 校验降级为宽松模式）：{}", str(exc)[:150])
            self._bot_open_id = ""
        self._thread = threading.Thread(target=self._run_ws, name="feishu-bot-ws", daemon=True)
        self._thread.start()

    async def stop(self):
        self._stopping = True
        ws, self._ws = self._ws, None
        if ws is not None:
            try:
                import lark_oapi.ws.client as wsc
                conn = getattr(ws, "_conn", None)
                if conn is not None:
                    loop = wsc.loop
                    loop.call_soon_threadsafe(lambda: loop.create_task(conn.close()))
            except Exception:
                pass
        thread, self._thread = self._thread, None
        if thread is not None and thread.is_alive():
            thread.join(timeout=8)

    async def reload(self):
        await self.stop()
        await self.start()

    def _run_ws(self):
        # 在专用线程内导入 SDK，使 SDK 模块级事件循环绑定到本线程（避免与主线程 uvicorn loop 冲突）。
        from lark_oapi.core.enum import LogLevel
        from lark_oapi.event.dispatcher_handler import EventDispatcherHandler
        from lark_oapi.ws import Client as WsClient

        handler = (
            EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self._on_message)
            .build()
        )
        self._ws = WsClient(
            self._app_id,
            self._app_secret,
            event_handler=handler,
            log_level=LogLevel.ERROR,
            auto_reconnect=False,  # 由外层循环控制重连，保证 stop 后不再拉起
        )
        while not self._stopping:
            try:
                logger.info("飞书机器人长连接启动: app_id={}", self._app_id)
                self._ws.start()  # 阻塞运行；断开时抛异常返回
            except Exception as exc:
                logger.warning("飞书机器人长连接断开：{}", str(exc)[:180])
            finally:
                self._ws = None
            if not self._stopping:
                time.sleep(5)

    # ---------------------------------------------------------------- 消息处理
    def _on_message(self, data):
        """SDK 事件回调（SDK 线程内，同步）。把处理调度到该线程的事件循环。"""
        try:
            event = getattr(data, "event", None)
            message = getattr(event, "message", None)
            if message is None:
                return
            if (getattr(message, "message_type", "") or "") != "text":
                return
            chat_type = getattr(message, "chat_type", "") or ""
            if chat_type not in ("group", "p2p"):
                return  # 支持群聊与单聊（私聊）
            import lark_oapi.ws.client as wsc
            wsc.loop.create_task(self._dispatch(event, message))
        except Exception:
            logger.exception("飞书消息调度失败")

    async def _dispatch(self, event, message):
        """限制同时处理的消息数（P4：避免高峰创建无限 task）。"""
        async with self._handle_sem:
            await self._handle_message_async(event, message)

    async def _handle_message_async(self, event, message):
        message_id = getattr(message, "message_id", "") or ""
        chat_id = getattr(message, "chat_id", "") or ""
        chat_type = getattr(message, "chat_type", "") or ""
        if not message_id or not chat_id:
            return
        now = time.monotonic()
        if message_id in self._seen:
            return
        self._seen[message_id] = now
        if len(self._seen) > 2000:
            self._seen = {k: v for k, v in self._seen.items() if now - v < 3600}

        # 群消息必须 @ 机器人（宽松模式：拿不到机器人 open_id 时放行）；单聊无需 @。
        if chat_type == "group" and self._bot_open_id:
            mentions = getattr(message, "mentions", None) or []
            mentioned = any(
                (getattr(m, "id", None) is not None and getattr(m.id, "open_id", None) == self._bot_open_id)
                for m in mentions
            )
            if not mentioned:
                return

        question = _clean_mention(getattr(message, "content", "") or "")
        if not question or len(question) > 4000:
            return

        sender = getattr(event, "sender", None)
        sender_open_id = ""
        sender_id = getattr(sender, "sender_id", None)
        if sender_id is not None:
            sender_open_id = getattr(sender_id, "open_id", "") or ""

        # P1 限流：按"群+成员"令牌桶/滑动窗口控制，防刷消息导致 LLM 调用风暴。
        if rate_limiter.check(f"feishu:{chat_id}:{sender_open_id or 'unknown'}", "", is_private=True) != RateLimitResult.ALLOW:
            logger.info("飞书消息已限流忽略: chat={} member={}", chat_id, sender_open_id or 'unknown')
            return

        async with self._send_lock:
            try:
                result = await self._resolve_and_answer(chat_type, chat_id, question, sender_open_id)
                if result:
                    # 写入本地问答历史，进入管理台观测/评测链路（失败不影响回复）
                    try:
                        async with async_session_factory() as db:
                            db.add(QAHistory(
                                agent_id=result.agent_id, question=question, answer=result.answer,
                                sources=json.dumps(result.sources, ensure_ascii=False),
                                total_time_ms=result.retrieval_time_ms + result.generation_time_ms,
                                channel="feishu", chat_id=chat_id,
                                user_id=f"feishu:{chat_id}:{sender_open_id or 'unknown'}",
                                input_tokens=result.input_tokens, cached_input_tokens=result.cached_input_tokens,
                                output_tokens=result.output_tokens, is_degraded=result.degraded,
                                web_search_count=result.web_search_count,
                            ))
                            await db.commit()
                    except Exception:
                        logger.exception("飞书问答历史写入失败: chat={}", chat_id)
                    await self._reply(message_id, result.answer)
            except Exception:
                logger.exception("飞书消息处理失败: chat={} msg={}", chat_id, message_id)

    async def _resolve_and_answer(self, chat_type: str, chat_id: str, question: str, sender_open_id: str):
        async with async_session_factory() as db:
            config = await db.get(FeishuBotConfig, 1)
            response_detail = (config.response_detail if config else "") or "concise"
            if chat_type == "p2p":
                # 单聊：由配置的私聊默认 Agent 回答（开关 + 权限模式安全边界）
                if config is None or not config.p2p_enabled:
                    logger.info("飞书私聊消息已忽略：私聊未启用，user={}", sender_open_id)
                    return None
                mode = config.p2p_access_mode or "all"
                openids = [x.strip() for x in (config.p2p_allow_openids or "").split(",") if x.strip()]
                if mode == "allowlist" and (not openids or sender_open_id not in openids):
                    logger.info("飞书私聊消息已忽略：用户不在私聊白名单，user={}", sender_open_id)
                    return None
                if mode == "blocklist" and sender_open_id in openids:
                    logger.info("飞书私聊消息已忽略：用户在私聊黑名单，user={}", sender_open_id)
                    return None
                agent = await db.get(Agent, config.p2p_agent_id) if config.p2p_agent_id else None
                if agent is None or not agent.is_active:
                    logger.info("飞书私聊消息已忽略：未配置私聊默认 Agent，user={}", sender_open_id)
                    return None
            else:
                binding = (
                    await db.execute(
                        select(FeishuChatBinding).where(
                            FeishuChatBinding.chat_id == chat_id,
                            FeishuChatBinding.is_active.is_(True),
                        )
                    )
                ).scalar_one_or_none()
                if binding is None:
                    logger.info("飞书群消息已忽略：该群尚未绑定 Agent，chat_id={}", chat_id)
                    return None
                agent = await db.get(Agent, binding.agent_id)
                if not agent or not agent.is_active:
                    logger.warning("飞书群消息已忽略：绑定的 Agent 不可用，chat_id={}, agent_id={}", chat_id, binding.agent_id)
                    return None
            ids = [
                str(x)
                for x in (
                    await db.execute(
                        select(KnowledgeBase.id)
                        .join(AgentKnowledgeBase, AgentKnowledgeBase.knowledge_base_id == KnowledgeBase.id)
                        .where(
                            AgentKnowledgeBase.agent_id == agent.id,
                            KnowledgeBase.is_active.is_(True),
                        )
                    )
                ).scalars()
            ]
        result = await answer_generator.generate(
            knowledge_base_ids=ids,
            question=question,
            agent_id=agent.id,
            user_id=f"feishu:{chat_id}:{sender_open_id or 'unknown'}",
            enable_memory=False,
            allow_web_search=False,
            reply_mode=agent.reply_mode,
            persona_preset=agent.persona_preset,
            persona_custom_instruction=agent.persona_custom_instruction or "",
            response_detail=response_detail,
        )
        result.agent_id = agent.id
        return result

    async def _reply(self, message_id: str, content: str):
        """引用回复原消息；复用 QQ 渠道的 Markdown 降级清洗后以纯文本发送。"""
        text = plain_text(content or "暂时无法生成回答，请稍后再试。")
        token = await self._tenant_token(self._app_id, self._app_secret)
        payload = {"content": json.dumps({"text": text}, ensure_ascii=False), "msg_type": "text"}
        # P5：发送失败不抛出，避免把"已生成但发送失败"误判为整体失败。
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.post(
                    f"{_FEISHU_API}/im/v1/messages/{message_id}/reply",
                    headers={"Authorization": f"Bearer {token}"},
                    json=payload,
                )
                r.raise_for_status()
        except Exception:
            logger.warning("飞书消息发送失败: msg={}", message_id)


feishu_bot_service = FeishuBotService()
