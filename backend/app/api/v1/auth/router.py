"""网页用户与管理员认证：图形验证码、兑换码、账号密码及安全会话。"""

import base64
import hashlib
import hmac
import html
import os
import secrets
import string
import time
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import Response as RawResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.agent import Agent
from app.models.auth import AccessCode, AccessCodeAgent, AccessCodeDailyUsage, AdminUser, AuthSession, CaptchaChallenge, Conversation, WebUser
from app.models.qa import QAHistory
from app.services.memory.memory_service import memory_service

router = APIRouter(prefix="/auth", tags=["认证"])
_attempts: dict[str, list[float]] = {}


class CaptchaVerifyIn(BaseModel):
    captcha_id: str
    captcha_answer: str = Field(min_length=1, max_length=12)


class UserLoginIn(CaptchaVerifyIn):
    access_code: str = Field(min_length=16, max_length=64)


class AdminLoginIn(CaptchaVerifyIn):
    username: str = Field(min_length=3, max_length=100)
    # 兼容首次本地部署密码；生产环境仍应使用强密码。
    password: str = Field(min_length=6, max_length=200)


class AccessCodeCreateIn(BaseModel):
    agent_ids: list[int] = Field(min_length=1)
    daily_question_limit: int = Field(50, ge=1, le=10000)
    note: str = Field("", max_length=500)
    expires_days: int | None = Field(None, ge=1, le=3650)
    count: int = Field(1, ge=1, le=100)


class AccessCodeLimitIn(BaseModel):
    daily_question_limit: int = Field(ge=1, le=10000)


class AccessCodeBatchIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=100)


def _pepper() -> str:
    return settings.AUTH_SESSION_SECRET


def _require_session_secret() -> None:
    """认证密钥必须由部署者提供，不能退回到可预测的默认值。"""
    if len(settings.AUTH_SESSION_SECRET) < 32:
        raise HTTPException(status_code=503, detail="认证尚未初始化：请配置至少 32 位的 ZHIDA_AUTH_SESSION_SECRET")


def _hash_access_code(code: str) -> str:
    normalized = "".join(code.upper().split())
    return hmac.new(_pepper().encode(), normalized.encode(), hashlib.sha256).hexdigest()


def _hash_token(token: str) -> str:
    return hmac.new(_pepper().encode(), token.encode(), hashlib.sha256).hexdigest()


def _encrypt_access_code(code: str) -> str:
    """用部署会话密钥加密兑换码，便于管理员以后重新复制。"""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = hashlib.sha256(f"{_pepper()}:access-code:v1".encode()).digest()
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, code.encode(), b"zhida-access-code-v1")
    return "v1:" + base64.b64encode(nonce + ciphertext).decode()


def _decrypt_access_code(ciphertext: str | None) -> str | None:
    if not ciphertext or not ciphertext.startswith("v1:"):
        return None
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        combined = base64.b64decode(ciphertext[3:])
        key = hashlib.sha256(f"{_pepper()}:access-code:v1".encode()).digest()
        return AESGCM(key).decrypt(combined[:12], combined[12:], b"zhida-access-code-v1").decode()
    except Exception:
        # 部署密钥改变后旧密文不可恢复，但哈希登录仍不受影响。
        return None


def _password_hash(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_b64, digest_b64 = stored.split("$", 2)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64), n=2**14, r=8, p=1)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def _new_access_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    raw = "".join(secrets.choice(alphabet) for _ in range(24))
    return "-".join(raw[index:index + 4] for index in range(0, 24, 4))


def _check_attempts(key: str, maximum: int) -> None:
    now = time.time()
    records = [stamp for stamp in _attempts.get(key, []) if stamp > now - 900]
    if len(records) >= maximum:
        raise HTTPException(status_code=429, detail="尝试次数过多，请 15 分钟后再试")
    _attempts[key] = records


def _record_failed_attempt(key: str) -> None:
    _attempts.setdefault(key, []).append(time.time())


def _captcha_svg(answer: str) -> str:
    chars = "".join(
        f'<text x="{22 + index * 29}" y="37" transform="rotate({secrets.choice(range(-14, 15))} {22 + index * 29} 37)">{html.escape(char)}</text>'
        for index, char in enumerate(answer)
    )
    lines = "".join(f'<line x1="0" y1="{secrets.randbelow(48)}" x2="180" y2="{secrets.randbelow(48)}" />' for _ in range(4))
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="180" height="54" viewBox="0 0 180 54"><rect width="100%" height="100%" fill="#f4f6fb"/><g stroke="#aab5cc" stroke-width="1" opacity=".55">{lines}</g><g fill="#31427f" font-size="29" font-family="monospace" font-weight="700">{chars}</g></svg>'


async def _verify_captcha(payload: CaptchaVerifyIn, purpose: str, db: AsyncSession) -> None:
    challenge = await db.get(CaptchaChallenge, payload.captcha_id)
    if challenge is None or challenge.purpose != purpose or challenge.expires_at < datetime.utcnow():
        raise HTTPException(status_code=422, detail="验证码已过期，请刷新")
    challenge.attempts += 1
    submitted = hashlib.sha256(f"{challenge.id}:{payload.captcha_answer.strip().upper()}".encode()).hexdigest()
    if challenge.attempts > 5 or not hmac.compare_digest(submitted, challenge.answer_hash):
        await db.delete(challenge)
        # get_db 会在 HTTPException 时回滚；这里显式提交，确保验证码不能被无限重试。
        await db.commit()
        raise HTTPException(status_code=422, detail="验证码错误，请刷新后重试")
    await db.delete(challenge)


async def _issue_session(request: Request, response: Response, db: AsyncSession, role: str, principal_id: int) -> None:
    # 登录时顺便回收历史过期记录；无需额外定时任务或 Redis。
    await db.execute(delete(AuthSession).where(AuthSession.expires_at <= datetime.utcnow()))
    token = secrets.token_urlsafe(32)
    expires = _session_expiry(role)
    db.add(AuthSession(
        token_hash=_hash_token(token), role=role, expires_at=expires,
        admin_id=principal_id if role == "admin" else None,
        user_id=principal_id if role == "user" else None,
    ))
    _set_session_cookie(request, response, role, token, expires)


def _session_expiry(role: str) -> datetime:
    """返回某类会话的滑动有效期终点。"""
    return datetime.utcnow() + (
        timedelta(hours=settings.AUTH_ADMIN_SESSION_HOURS)
        if role == "admin"
        else timedelta(days=settings.AUTH_USER_SESSION_DAYS)
    )


def _session_ttl(role: str) -> timedelta:
    return (
        timedelta(hours=settings.AUTH_ADMIN_SESSION_HOURS)
        if role == "admin"
        else timedelta(days=settings.AUTH_USER_SESSION_DAYS)
    )


def _request_is_https(request: Request) -> bool:
    forwarded = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip().lower()
    return request.url.scheme == "https" or forwarded == "https"


def _set_session_cookie(request: Request, response: Response, role: str, token: str, expires: datetime) -> None:
    """集中设置 Cookie，避免登录和续期的属性不一致。"""
    response.set_cookie(
        key=f"zhida_{role}_session",
        # Cookie 的值不会在续期时改变，只有 Max-Age 被刷新。
        value=token,
        httponly=True,
        # 本地回环调试允许 HTTP；公网由安全中间件强制 HTTPS，因此必须带 Secure。
        secure=_request_is_https(request),
        samesite="strict",
        max_age=max(0, int((expires - datetime.utcnow()).total_seconds())),
        path="/",
    )


async def _maybe_refresh_session(request: Request, response: Response, session: AuthSession, token: str, role: str) -> None:
    """在接近到期时延长会话，避免高频请求反复写入 SQLite。

    续期阈值是完整有效期的三分之一。管理员的 8 小时窗口与用户的
    7 天窗口都会在正常使用中滑动延长，但会话本身从不绕过账号或兑换码校验。
    """
    now = datetime.utcnow()
    if session.expires_at - now > _session_ttl(role) / 3:
        return
    expires = _session_expiry(role)
    session.expires_at = expires
    _set_session_cookie(request, response, role, token, expires)


async def _principal(request: Request, response: Response, db: AsyncSession, role: str):
    token = request.cookies.get(f"zhida_{role}_session")
    if not token:
        raise HTTPException(status_code=401, detail="请先登录")
    session = (await db.execute(select(AuthSession).where(
        AuthSession.token_hash == _hash_token(token), AuthSession.role == role,
        AuthSession.expires_at > datetime.utcnow(),
    ))).scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    principal = await db.get(AdminUser if role == "admin" else WebUser, session.admin_id if role == "admin" else session.user_id)
    if principal is None or not principal.is_active:
        raise HTTPException(status_code=401, detail="账号不可用")
    if role == "user":
        code = await db.get(AccessCode, principal.access_code_id)
        if code is None or code.status != "claimed" or (code.expires_at and code.expires_at < datetime.utcnow()):
            raise HTTPException(status_code=401, detail="访问资格已失效，请联系管理员")
    await _maybe_refresh_session(request, response, session, token, role)
    return principal


async def require_admin(request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> AdminUser:
    _require_session_secret()
    return await _principal(request, response, db, "admin")


async def require_user(request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> WebUser:
    _require_session_secret()
    return await _principal(request, response, db, "user")


async def ensure_bootstrap_admin(db: AsyncSession) -> None:
    if not settings.ADMIN_BOOTSTRAP_USERNAME or not settings.ADMIN_BOOTSTRAP_PASSWORD:
        return
    existing = (await db.execute(select(AdminUser.id).limit(1))).scalar_one_or_none()
    if existing is None:
        db.add(AdminUser(username=settings.ADMIN_BOOTSTRAP_USERNAME.strip(), password_hash=_password_hash(settings.ADMIN_BOOTSTRAP_PASSWORD)))
        await db.commit()


@router.get("/captcha")
async def get_captcha(purpose: str = "user", db: AsyncSession = Depends(get_db)):
    if purpose not in {"user", "admin"}:
        raise HTTPException(status_code=422, detail="无效验证码类型")
    answer = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(5))
    challenge_id = secrets.token_urlsafe(24)
    db.add(CaptchaChallenge(
        id=challenge_id, purpose=purpose,
        answer_hash=hashlib.sha256(f"{challenge_id}:{answer}".encode()).hexdigest(),
        image_svg=_captcha_svg(answer),
        expires_at=datetime.utcnow() + timedelta(minutes=5),
    ))
    return {"captcha_id": challenge_id, "image_url": f"/api/v1/auth/captcha/{challenge_id}/image", "expires_in": 300}


@router.get("/captcha/{captcha_id}/image")
async def get_captcha_image(captcha_id: str, db: AsyncSession = Depends(get_db)):
    challenge = await db.get(CaptchaChallenge, captcha_id)
    if challenge is None or challenge.expires_at < datetime.utcnow() or not challenge.image_svg:
        raise HTTPException(status_code=404, detail="验证码已过期，请刷新")
    return RawResponse(challenge.image_svg, media_type="image/svg+xml", headers={"Cache-Control": "no-store"})


@router.post("/user/login")
async def user_login(payload: UserLoginIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    _require_session_secret()
    key = f"user:{request.client.host if request.client else 'unknown'}"
    _check_attempts(key, 10)
    try:
        await _verify_captcha(payload, "user", db)
        # 验证码与登录凭证各只使用一次，即使兑换码失效也不允许复用验证码。
        await db.commit()
        code_hash = _hash_access_code(payload.access_code)
        code = (await db.execute(select(AccessCode).where(AccessCode.code_hash == code_hash))).scalar_one_or_none()
        if code is None or code.status != "active" or (code.expires_at and code.expires_at < datetime.utcnow()):
            raise HTTPException(status_code=401, detail="激活码无效、已使用或已过期")
        # 条件更新确保并发请求中只有一个能完成领取。领取后立即销毁可恢复明文，
        # 管理员只能重置资格，不能再读取用户已经使用过的凭据。
        claimed_at = datetime.utcnow()
        claimed = await db.execute(
            update(AccessCode).where(
                AccessCode.id == code.id,
                AccessCode.code_hash == code_hash,
                AccessCode.status == "active",
            ).values(status="claimed", claimed_at=claimed_at, code_ciphertext=None)
        )
        if claimed.rowcount != 1:
            raise HTTPException(status_code=409, detail="激活码已被使用，请联系管理员")
        user = (await db.execute(select(WebUser).where(WebUser.access_code_id == code.id))).scalar_one_or_none()
        if user is None:
            user = WebUser(access_code_id=code.id)
            db.add(user)
            await db.flush()
        user.last_login_at = datetime.utcnow()
        # 用户端与管理端使用不同 Cookie 名称。两种身份可在本机开发环境并存，
        # 不能因用户激活而清除管理端会话（Cookie 不区分 5173/5174 端口）。
        await _issue_session(request, response, db, "user", user.id)
        return {"role": "user", "user_id": user.id}
    except HTTPException:
        _record_failed_attempt(key)
        raise


@router.post("/admin/login")
async def admin_login(payload: AdminLoginIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    _require_session_secret()
    key = f"admin:{request.client.host if request.client else 'unknown'}:{payload.username.lower()}"
    _check_attempts(key, 5)
    try:
        await _verify_captcha(payload, "admin", db)
        await db.commit()
        admin = (await db.execute(select(AdminUser).where(AdminUser.username == payload.username.strip()))).scalar_one_or_none()
        if admin is None or not admin.is_active or not _verify_password(payload.password, admin.password_hash):
            raise HTTPException(status_code=401, detail="账号、密码或验证码错误")
        admin.last_login_at = datetime.utcnow()
        # 不清除用户端会话；正式部署中两个站点由不同主机名隔离，开发环境可并行测试。
        await _issue_session(request, response, db, "admin", admin.id)
        return {"role": "admin", "username": admin.username}
    except HTTPException:
        _record_failed_attempt(key)
        raise


@router.post("/logout")
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    for role in ("admin", "user"):
        token = request.cookies.get(f"zhida_{role}_session")
        if token:
            session = await db.get(AuthSession, _hash_token(token))
            if session:
                await db.delete(session)
            response.delete_cookie(f"zhida_{role}_session", path="/")
    return {"success": True}


@router.get("/me")
async def get_me(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    _require_session_secret()
    for role in ("admin", "user"):
        try:
            principal = await _principal(request, response, db, role)
            return {"role": role, "id": principal.id, "username": getattr(principal, "username", None)}
        except HTTPException:
            continue
    raise HTTPException(status_code=401, detail="请先登录")


@router.post("/admin/access-codes")
async def create_access_code(payload: AccessCodeCreateIn, response: Response, db: AsyncSession = Depends(get_db), _: AdminUser = Depends(require_admin)):
    agents = (await db.execute(select(Agent.id).where(
        Agent.id.in_(payload.agent_ids), Agent.is_active == True,  # noqa: E712
    ))).scalars().all()
    if len(set(agents)) != len(set(payload.agent_ids)):
        raise HTTPException(status_code=422, detail="包含不存在或未启用的 Agent，请先在 Agent 管理中启动")
    created = []
    for _ in range(payload.count):
        code_text = _new_access_code()
        code = AccessCode(
            code_hash=_hash_access_code(code_text), code_hint=code_text[-8:],
            code_ciphertext=_encrypt_access_code(code_text), note=payload.note,
            daily_question_limit=payload.daily_question_limit,
            expires_at=datetime.utcnow() + timedelta(days=payload.expires_days) if payload.expires_days else None,
        )
        db.add(code)
        await db.flush()
        db.add_all([AccessCodeAgent(access_code_id=code.id, agent_id=agent_id) for agent_id in set(payload.agent_ids)])
        created.append({"id": code.id, "access_code": code_text, "code_hint": code.code_hint})
    # 保留单个创建时的旧字段，供外部调用方兼容。
    return {"items": created, **(created[0] if payload.count == 1 else {})}


async def _access_code_out(code: AccessCode, db: AsyncSession) -> dict:
    if code.status in {"active", "claimed"} and code.expires_at and code.expires_at < datetime.utcnow():
        code.status = "expired"
    agent_rows = (await db.execute(
        select(Agent.id, Agent.name).join(AccessCodeAgent, AccessCodeAgent.agent_id == Agent.id)
        .where(AccessCodeAgent.access_code_id == code.id).order_by(Agent.name)
    )).all()
    usage = await db.get(AccessCodeDailyUsage, (code.id, datetime.utcnow().date().isoformat()))
    return {
        "id": code.id, "code_hint": code.code_hint, "status": code.status,
        "daily_question_limit": code.daily_question_limit, "usage_today": usage.question_count if usage else 0,
        "expires_at": code.expires_at, "claimed_at": code.claimed_at,
        "note": code.note, "created_at": code.created_at,
        "agents": [{"id": agent_id, "name": name} for agent_id, name in agent_rows],
    }


@router.get("/admin/access-codes")
async def list_access_codes(db: AsyncSession = Depends(get_db), _: AdminUser = Depends(require_admin)):
    codes = (await db.execute(select(AccessCode).order_by(AccessCode.created_at.desc()))).scalars().all()
    return {"items": [await _access_code_out(code, db) for code in codes]}


async def _rotate_access_code_value(code: AccessCode, db: AsyncSession) -> str:
    """为不可恢复的历史记录换发新值，并撤销使用旧值建立的会话。"""
    code_text = _new_access_code()
    code.code_hash = _hash_access_code(code_text)
    code.code_hint = code_text[-8:]
    code.code_ciphertext = _encrypt_access_code(code_text)
    user_ids = select(WebUser.id).where(WebUser.access_code_id == code.id)
    await db.execute(delete(AuthSession).where(AuthSession.user_id.in_(user_ids)))
    return code_text


@router.post("/admin/access-codes/{code_id}/copy")
async def copy_access_code(code_id: int, db: AsyncSession = Depends(get_db), _: AdminUser = Depends(require_admin)):
    """仅返回尚未领取的激活码；领取后不再允许恢复明文。"""
    code = await db.get(AccessCode, code_id)
    if code is None:
        raise HTTPException(status_code=404, detail="兑换码不存在")
    if code.status != "active":
        raise HTTPException(status_code=409, detail="激活码已领取或失效，不能再次查看")
    code_text = _decrypt_access_code(code.code_ciphertext)
    rotated = code_text is None
    if rotated:
        code_text = await _rotate_access_code_value(code, db)
    return {"id": code.id, "access_code": code_text, "code_hint": code.code_hint, "rotated": rotated}


@router.post("/admin/access-codes/copy/batch")
async def copy_access_codes(payload: AccessCodeBatchIn, db: AsyncSession = Depends(get_db), _: AdminUser = Depends(require_admin)):
    codes = (await db.execute(
        select(AccessCode).where(AccessCode.id.in_(set(payload.ids))).order_by(AccessCode.created_at.desc())
    )).scalars().all()
    if not codes:
        raise HTTPException(status_code=404, detail="未找到可复制的兑换码")
    items, rotated_count, unavailable_count = [], 0, 0
    for code in codes:
        if code.status != "active":
            unavailable_count += 1
            continue
        code_text = _decrypt_access_code(code.code_ciphertext)
        if code_text is None:
            code_text = await _rotate_access_code_value(code, db)
            rotated_count += 1
        items.append({"id": code.id, "access_code": code_text})
    if not items:
        raise HTTPException(status_code=409, detail="所选激活码均已领取或失效")
    return {"items": items, "rotated_count": rotated_count, "unavailable_count": unavailable_count}


@router.post("/admin/access-codes/{code_id}/reset-activation")
async def reset_access_code_activation(code_id: int, db: AsyncSession = Depends(get_db), _: AdminUser = Depends(require_admin)):
    """用户丢失 Cookie 时换发新的一次性激活码，并撤销旧设备会话。"""
    code = await db.get(AccessCode, code_id)
    if code is None:
        raise HTTPException(status_code=404, detail="兑换码不存在")
    if code.status in {"revoked", "expired"} or (code.expires_at and code.expires_at <= datetime.utcnow()):
        raise HTTPException(status_code=409, detail="已停用或过期的访问资格不能重置")
    code_text = _new_access_code()
    code.code_hash = _hash_access_code(code_text)
    code.code_hint = code_text[-8:]
    code.code_ciphertext = _encrypt_access_code(code_text)
    code.status = "active"
    code.claimed_at = None
    user_ids = select(WebUser.id).where(WebUser.access_code_id == code.id)
    await db.execute(delete(AuthSession).where(AuthSession.user_id.in_(user_ids)))
    return {"id": code.id, "access_code": code_text, "code_hint": code.code_hint}


@router.put("/admin/access-codes/{code_id}/daily-limit")
async def update_access_code_limit(code_id: int, payload: AccessCodeLimitIn, db: AsyncSession = Depends(get_db), _: AdminUser = Depends(require_admin)):
    code = await db.get(AccessCode, code_id)
    if code is None:
        raise HTTPException(status_code=404, detail="兑换码不存在")
    usage = await db.get(AccessCodeDailyUsage, (code.id, datetime.utcnow().date().isoformat()))
    if usage and payload.daily_question_limit < usage.question_count:
        raise HTTPException(status_code=422, detail=f"不能低于今日已使用的 {usage.question_count} 次")
    code.daily_question_limit = payload.daily_question_limit
    return await _access_code_out(code, db)


@router.post("/admin/access-codes/{code_id}/revoke")
async def revoke_access_code(code_id: int, db: AsyncSession = Depends(get_db), _: AdminUser = Depends(require_admin)):
    code = await db.get(AccessCode, code_id)
    if code is None:
        raise HTTPException(status_code=404, detail="兑换码不存在")
    code.status = "revoked"
    user_ids = select(WebUser.id).where(WebUser.access_code_id == code.id)
    await db.execute(delete(AuthSession).where(AuthSession.user_id.in_(user_ids)))
    return {"success": True, "id": code.id}


async def _delete_access_code_users(db: AsyncSession, code_ids: list[int]) -> None:
    user_ids = list((await db.execute(
        select(WebUser.id).where(WebUser.access_code_id.in_(code_ids))
    )).scalars().all())
    if not user_ids:
        return
    # 会话与问答历史属于用户隐私；删除访问资格时同步清理，避免留下孤儿数据。
    await db.execute(delete(AuthSession).where(AuthSession.user_id.in_(user_ids)))
    await db.execute(delete(QAHistory).where(QAHistory.owner_type == "user", QAHistory.owner_id.in_(user_ids)))
    await db.execute(delete(Conversation).where(Conversation.owner_type == "user", Conversation.owner_id.in_(user_ids)))
    await db.execute(delete(WebUser).where(WebUser.id.in_(user_ids)))
    # 长期记忆不在 SQLite；尽力按用户隔离键删除，失败不会阻止主库的隐私删除。
    for user_id in user_ids:
        try:
            await memory_service.delete_all(user_id=f"user:{user_id}")
        except Exception:
            pass


@router.delete("/admin/access-codes/{code_id}")
async def delete_access_code(code_id: int, db: AsyncSession = Depends(get_db), _: AdminUser = Depends(require_admin)):
    code = await db.get(AccessCode, code_id)
    if code is None:
        raise HTTPException(status_code=404, detail="兑换码不存在")
    # 兑换码是网页用户的唯一登录凭据。删除时一并清理对应用户与会话，
    # 以满足外键约束并立即撤销已登录设备的访问权限。
    await _delete_access_code_users(db, [code.id])
    await db.delete(code)
    return {"success": True, "id": code_id}


@router.post("/admin/access-codes/batch/delete")
async def batch_delete_access_codes(payload: AccessCodeBatchIn, db: AsyncSession = Depends(get_db), _: AdminUser = Depends(require_admin)):
    ids = list(set(payload.ids))
    existing = (await db.execute(select(AccessCode.id).where(AccessCode.id.in_(ids)))).scalars().all()
    if not existing:
        raise HTTPException(status_code=404, detail="未找到可删除的兑换码")
    await _delete_access_code_users(db, list(existing))
    await db.execute(delete(AccessCode).where(AccessCode.id.in_(existing)))
    return {"success": True, "deleted": len(existing)}
