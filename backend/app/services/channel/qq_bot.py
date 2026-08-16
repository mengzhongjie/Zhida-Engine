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
from app.models.qa import QAHistory
from app.services.cache.rate_limiter import rate_limiter, RateLimitResult
from app.services.channel.utils import plain_text as _qq_plain_text
from app.services.qa.generator import answer_generator

class QQBotService:
    def __init__(self): self._task=None; self._seen={}; self._send_lock=asyncio.Semaphore(4); self._handle_sem=asyncio.Semaphore(8); self._capture_until=0.0; self._captured_groups=[]
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
                body=r.json()
                if not body.get("access_token"):
                    return False, f"QQ 未返回 access_token：code={body.get('code')} message={body.get('message') or body.get('msg') or body}"
            return True, "ok"
        except Exception as exc: return False, f"QQ 凭据测试失败：{str(exc)[:180]}"
    async def _credentials(self):
        async with async_session_factory() as db:
            c=await db.get(QQBotConfig,1)
            return (c.app_id, decrypt_api_key(c.app_secret)) if c and c.enabled and c.app_id and c.app_secret else None
    async def _token(self, app_id, secret):
        async with httpx.AsyncClient(timeout=15) as c:
            r=await c.post("https://bots.qq.com/app/getAppAccessToken",json={"appId":app_id,"clientSecret":secret}); r.raise_for_status()
            body=r.json()
            if "access_token" not in body:
                raise RuntimeError(f"QQ token 获取失败：code={body.get('code')} message={body.get('message') or body.get('msg')}")
            return body["access_token"]
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
                            # GROUP_AT_MESSAGE_CREATE（群@）与 C2C_MESSAGE_CREATE（单聊）共用 1<<25 intent。
                            if event.get("op")==0 and event.get("t") in ("GROUP_AT_MESSAGE_CREATE","C2C_MESSAGE_CREATE"): asyncio.create_task(self._dispatch(event.get("d") or {},event.get("t"),token,app_id))
                    finally: heartbeat.cancel()
            except asyncio.CancelledError: raise
            except Exception as exc: logger.warning("QQ Gateway 断开：{}",str(exc)[:180]); await asyncio.sleep(5)
    async def _heartbeat(self,ws,interval):
        while True: await asyncio.sleep(interval); await ws.send(json.dumps({"op":1,"d":None}))
    async def _dispatch(self,event,etype,token,app_id):
        """限制同时处理的消息数（P4：避免高峰创建无限 task）。"""
        async with self._handle_sem:
            await self._handle(event,etype,token,app_id)
    async def _handle(self,event,etype,token,app_id):
        if etype=="C2C_MESSAGE_CREATE":
            await self._handle_c2c(event,token,app_id)
        else:
            await self._handle_group(event,token,app_id)
    async def _handle_c2c(self,event,token,app_id):
        """单聊（私聊）消息：用户直接私聊机器人，由配置的私聊默认 Agent 回答。"""
        event_id=str(event.get("id") or ""); user_openid=(event.get("author") or {}).get("user_openid") or ""
        if not event_id or not user_openid or event_id in self._seen: return
        self._seen[event_id]=time.monotonic()
        if len(self._seen) > 2000:
            self._seen={k:v for k,v in self._seen.items() if time.monotonic()-v<3600}
        question=str(event.get("content") or "").strip()
        if not question or len(question)>4000: return
        async with async_session_factory() as db:
            config=await db.get(QQBotConfig,1)
            # 私聊安全边界：开关默认关闭；权限模式 all/allowlist/blocklist
            if config is None or not config.p2p_enabled:
                logger.info("QQ 私聊消息已忽略：私聊未启用，user_openid={}", user_openid)
                return
            mode = config.p2p_access_mode or "all"
            openids = [x.strip() for x in (config.p2p_allow_openids or "").split(",") if x.strip()]
            if mode == "allowlist" and (not openids or user_openid not in openids):
                logger.info("QQ 私聊消息已忽略：用户不在私聊白名单，user_openid={}", user_openid)
                return
            if mode == "blocklist" and user_openid in openids:
                logger.info("QQ 私聊消息已忽略：用户在私聊黑名单，user_openid={}", user_openid)
                return
            agent=await db.get(Agent,config.p2p_agent_id) if config.p2p_agent_id else None
            if agent is None or not agent.is_active:
                logger.info("QQ 私聊消息已忽略：未配置私聊默认 Agent，user_openid={}", user_openid)
                return
            ids=[str(x) for x in (await db.execute(select(KnowledgeBase.id).join(AgentKnowledgeBase,AgentKnowledgeBase.knowledge_base_id==KnowledgeBase.id).where(AgentKnowledgeBase.agent_id==agent.id,KnowledgeBase.is_active.is_(True)))).scalars()]
            response_detail=(config.response_detail if config else "") or "concise"
        if rate_limiter.check(f"qq:c2c:{user_openid}", "", is_private=True) != RateLimitResult.ALLOW:
            logger.info("QQ 私聊消息已限流忽略: user={}", user_openid)
            return
        async with self._send_lock:
            try:
                qq_user_id=f"qq:c2c:{user_openid}"
                result=await answer_generator.generate(knowledge_base_ids=ids,question=question,agent_id=agent.id,user_id=qq_user_id,enable_memory=False,allow_web_search=False,reply_mode=agent.reply_mode,persona_preset=agent.persona_preset,persona_custom_instruction=agent.persona_custom_instruction or "",response_detail=response_detail)
                try:
                    async with async_session_factory() as db:
                        db.add(QAHistory(
                            agent_id=agent.id, question=question, answer=result.answer,
                            sources=json.dumps(result.sources, ensure_ascii=False),
                            total_time_ms=result.retrieval_time_ms + result.generation_time_ms,
                            channel="qq", chat_id=user_openid, user_id=qq_user_id,
                            input_tokens=result.input_tokens, cached_input_tokens=result.cached_input_tokens,
                            output_tokens=result.output_tokens, is_degraded=result.degraded,
                            web_search_count=result.web_search_count,
                        ))
                        await db.commit()
                except Exception:
                    logger.exception("QQ 私聊问答历史写入失败: user={}", user_openid)
                await self._reply_c2c(user_openid,event_id,_qq_plain_text(result.answer),token,app_id)
            except Exception: logger.exception("QQ 私聊消息处理失败: user={}",user_openid)
    async def _handle_group(self,event,token,app_id):
        event_id=str(event.get("id") or ""); group=str(event.get("group_openid") or "")
        if not event_id or not group or event_id in self._seen: return
        self._seen[event_id]=time.monotonic()
        if len(self._seen) > 2000:
            # 仅在超过容量上限时做一次清理（去掉超 1 小时的旧 ID），避免每条消息全量重建。
            self._seen={k:v for k,v in self._seen.items() if time.monotonic()-v<3600}
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
            config=await db.get(QQBotConfig,1)
            response_detail=(config.response_detail if config else "") or "concise"
        # P1 限流：按"群+成员"令牌桶/滑动窗口控制，防群成员刷消息导致 LLM 调用风暴。
        member_openid=(event.get('author') or {}).get('member_openid','unknown')
        if rate_limiter.check(f"qq:{group}:{member_openid}", "", is_private=True) != RateLimitResult.ALLOW:
            logger.info("QQ 群消息已限流忽略: group={} member={}", group, member_openid)
            return
        async with self._send_lock:
            try:
                qq_user_id=f"qq:{group}:{member_openid}"
                result=await answer_generator.generate(knowledge_base_ids=ids,question=question,agent_id=agent.id,user_id=qq_user_id,enable_memory=False,allow_web_search=False,reply_mode=agent.reply_mode,persona_preset=agent.persona_preset,persona_custom_instruction=agent.persona_custom_instruction or "",response_detail=response_detail)
                # 写入本地问答历史，进入管理台观测/评测链路（失败不影响回复）
                try:
                    async with async_session_factory() as db:
                        db.add(QAHistory(
                            agent_id=agent.id, question=question, answer=result.answer,
                            sources=json.dumps(result.sources, ensure_ascii=False),
                            total_time_ms=result.retrieval_time_ms + result.generation_time_ms,
                            channel="qq", chat_id=group, user_id=qq_user_id,
                            input_tokens=result.input_tokens, cached_input_tokens=result.cached_input_tokens,
                            output_tokens=result.output_tokens, is_degraded=result.degraded,
                            web_search_count=result.web_search_count,
                        ))
                        await db.commit()
                except Exception:
                    logger.exception("QQ 问答历史写入失败: group={}", group)
                await self._reply(group,event_id,_qq_plain_text(result.answer),token,app_id)
            except Exception: logger.exception("QQ 消息处理失败: group={}",group)
    async def _reply_c2c(self,user_openid,event_id,content,token,app_id):
        # P5：发送失败不抛出。
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r=await c.post(f"https://api.sgroup.qq.com/v2/users/{user_openid}/messages",headers={"Authorization":f"QQBot {token}","X-Union-Appid":app_id},json={"content":content or "暂时无法生成回答，请稍后再试。","msg_type":0,"msg_id":event_id}); r.raise_for_status()
        except Exception:
            logger.warning("QQ 私聊消息发送失败: user={} msg={}", user_openid, event_id)
    async def _reply(self,group,event_id,content,token,app_id):
        # P5：回复失败不抛出，避免把"已生成但发送失败"误判为整体失败。
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r=await c.post(f"https://api.sgroup.qq.com/v2/groups/{group}/messages",headers={"Authorization":f"QQBot {token}","X-Union-Appid":app_id},json={"content":content or "暂时无法生成回答，请稍后再试。","msg_type":0,"msg_id":event_id}); r.raise_for_status()
        except Exception:
            logger.warning("QQ 消息发送失败: group={} msg={}", group, event_id)
qq_bot_service=QQBotService()
