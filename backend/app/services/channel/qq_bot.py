"""QQ 官方机器人 Gateway：仅处理 GROUP_AT_MESSAGE_CREATE。"""
import asyncio, json, re, time
import httpx
from loguru import logger
from sqlalchemy import select
from app.core.database import async_session_factory
from app.core.security import decrypt_api_key
from app.models.agent import Agent
from app.models.agent_knowledge_base import AgentKnowledgeBase
from app.models.knowledge import KnowledgeBase
from app.models.qq_bot import QQBotConfig, QQBotGroupBinding
from app.services.qa.generator import answer_generator

def _qq_plain_text(value: str, limit: int = 1900) -> str:
    """QQ 群消息不渲染 Markdown；保留语义并移除会原样显示的标记。"""
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"```(?:[A-Za-z0-9_+-]+)?\s*\n?", "", text)
    text = text.replace("```", "")
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^\s)]+)\)", r"\1（\2）", text)
    text = re.sub(r"(^|\n)\s{0,3}#{1,6}\s+", r"\1", text)
    text = re.sub(r"(^|\n)\s*>\s?", r"\1", text)
    text = re.sub(r"(^|\n)\s*[-*+]\s+", r"\1• ", text)
    text = re.sub(r"(^|\n)\s*\d+[.)]\s+", r"\1", text)
    text = re.sub(r"(?<!\*)\*{1,3}([^*]+)\*{1,3}", r"\1", text)
    text = re.sub(r"(?<!_)_{1,3}([^_]+)_{1,3}", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"(?m)^\s*[-*_]{3,}\s*$", "", text)
    # 简单表格降级为逐行文本，去掉分隔线与多余竖线。
    text = re.sub(r"(?m)^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$", "", text)
    text = re.sub(r"(?m)^\s*\|\s*", "", text)
    text = re.sub(r"\s*\|\s*(?=\S)", " · ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"

class QQBotService:
    def __init__(self): self._task=None; self._seen={}; self._send_lock=asyncio.Semaphore(4); self._capture_until=0.0; self._captured_groups=[]
    def start_group_openid_capture(self):
        self._captured_groups=[]; self._capture_until=time.monotonic()+300
        return 300
    def group_openid_capture_status(self):
        return {"active":time.monotonic()<self._capture_until,"remaining_seconds":max(0,int(self._capture_until-time.monotonic())),"group_openids":self._captured_groups.copy()}
    async def start(self):
        if self._task is None or self._task.done(): self._task=asyncio.create_task(self._run(), name="qq-bot-gateway")
    async def stop(self):
        if self._task: self._task.cancel(); self._task=None
    async def reload(self):
        await self.stop(); await self.start()
    async def test_credentials(self, app_id, secret):
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r=await c.post("https://bots.qq.com/app/getAppAccessToken", json={"appId":app_id,"clientSecret":secret}); r.raise_for_status()
                if not r.json().get("access_token"): return False, "QQ 未返回 access_token"
            return True, "ok"
        except Exception as exc: return False, f"QQ 凭据测试失败：{str(exc)[:180]}"
    async def _credentials(self):
        async with async_session_factory() as db:
            c=await db.get(QQBotConfig,1)
            return (c.app_id, decrypt_api_key(c.app_secret)) if c and c.enabled and c.app_id and c.app_secret else None
    async def _token(self, app_id, secret):
        async with httpx.AsyncClient(timeout=15) as c:
            r=await c.post("https://bots.qq.com/app/getAppAccessToken",json={"appId":app_id,"clientSecret":secret}); r.raise_for_status(); return r.json()["access_token"]
    async def _run(self):
        while True:
            try:
                credentials=await self._credentials()
                if not credentials: await asyncio.sleep(10); continue
                app_id,secret=credentials; token=await self._token(app_id,secret)
                async with httpx.AsyncClient(timeout=15) as c:
                    response = await c.get("https://api.sgroup.qq.com/gateway", headers={"Authorization":f"QQBot {token}","X-Union-Appid":app_id})
                    response.raise_for_status()
                    gateway = response.json()["url"]
                import websockets
                async with websockets.connect(gateway, ping_interval=None, max_size=1_000_000) as ws:
                    hello=json.loads(await ws.recv()); interval=hello["d"]["heartbeat_interval"]/1000
                    # QQ Gateway 的 Identify 与 HTTP Authorization 一样要求 QQBot 前缀；
                    # 发送裸 access_token 会被服务端以 4004 Authentication fail 关闭。
                    await ws.send(json.dumps({"op":2,"d":{"token":f"QQBot {token}","intents":1<<25,"shard":[0,1],"properties":{"os":"linux","browser":"zhida-engine","device":"zhida-engine"}}}))
                    logger.info("QQ Gateway 已连接并发送 Identify: app_id={}", app_id)
                    heartbeat=asyncio.create_task(self._heartbeat(ws,interval))
                    try:
                        async for raw in ws:
                            event=json.loads(raw)
                            if event.get("op")==0 and event.get("t")=="GROUP_AT_MESSAGE_CREATE": asyncio.create_task(self._handle(event.get("d") or {},token,app_id))
                    finally: heartbeat.cancel()
            except asyncio.CancelledError: raise
            except Exception as exc: logger.warning("QQ Gateway 断开：{}",str(exc)[:180]); await asyncio.sleep(5)
    async def _heartbeat(self,ws,interval):
        while True: await asyncio.sleep(interval); await ws.send(json.dumps({"op":1,"d":None}))
    async def _handle(self,event,token,app_id):
        event_id=str(event.get("id") or ""); group=str(event.get("group_openid") or "")
        if not event_id or not group or event_id in self._seen: return
        self._seen[event_id]=time.monotonic(); self._seen={k:v for k,v in self._seen.items() if time.monotonic()-v<3600}
        question=re.sub(r"<@!?.+?>","",str(event.get("content") or "")).strip()
        if not question or len(question)>4000: return
        if time.monotonic() < self._capture_until and group not in self._captured_groups:
            self._captured_groups.append(group)
            logger.info("QQ 群 OpenID 获取成功: group_openid={}", group)
        async with async_session_factory() as db:
            binding=(await db.execute(select(QQBotGroupBinding).where(QQBotGroupBinding.group_openid==group,QQBotGroupBinding.is_active.is_(True)))).scalar_one_or_none()
            agent=await db.get(Agent,binding.agent_id) if binding else None
            if binding is None:
                # 仅记录本地日志，帮助管理员首次取得 QQ 官方 group_openid；不回复未授权群。
                logger.info("QQ 群消息已忽略：该群尚未绑定 Agent，group_openid={}", group)
                return
            if not agent or not agent.is_active:
                logger.warning("QQ 群消息已忽略：绑定的 Agent 不可用，group_openid={}, agent_id={}", group, binding.agent_id)
                return
            ids=[str(x) for x in (await db.execute(select(KnowledgeBase.id).join(AgentKnowledgeBase,AgentKnowledgeBase.knowledge_base_id==KnowledgeBase.id).where(AgentKnowledgeBase.agent_id==agent.id,KnowledgeBase.is_active.is_(True)))).scalars()]
        async with self._send_lock:
            try:
                result=await answer_generator.generate(knowledge_base_ids=ids,question=question,agent_id=agent.id,user_id=f"qq:{group}:{(event.get('author') or {}).get('member_openid','unknown')}",enable_memory=False,allow_web_search=False,reply_mode=agent.reply_mode,persona_preset=agent.persona_preset,persona_custom_instruction=agent.persona_custom_instruction or "",response_detail="concise")
                await self._reply(group,event_id,_qq_plain_text(result.answer),token,app_id)
            except Exception: logger.exception("QQ 消息处理失败: group={}",group)
    async def _reply(self,group,event_id,content,token,app_id):
        async with httpx.AsyncClient(timeout=30) as c:
            r=await c.post(f"https://api.sgroup.qq.com/v2/groups/{group}/messages",headers={"Authorization":f"QQBot {token}","X-Union-Appid":app_id},json={"content":content or "暂时无法生成回答，请稍后再试。","msg_type":0,"msg_id":event_id}); r.raise_for_status()
qq_bot_service=QQBotService()
