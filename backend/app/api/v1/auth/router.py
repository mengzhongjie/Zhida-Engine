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
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.agent import Agent
from app.models.auth import AccessCode, AccessCodeAgent, AdminUser, AuthSession, CaptchaChallenge, WebUser

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


async def _issue_session(response: Response, db: AsyncSession, role: str, principal_id: int) -> None:
    token = secrets.token_urlsafe(32)
    expires = datetime.utcnow() + (timedelta(hours=settings.AUTH_ADMIN_SESSION_HOURS) if role == "admin" else timedelta(days=settings.AUTH_USER_SESSION_DAYS))
    db.add(AuthSession(
        token_hash=_hash_token(token), role=role, expires_at=expires,
        admin_id=principal_id if role == "admin" else None,
        user_id=principal_id if role == "user" else None,
    ))
    response.set_cookie(
        key=f"zhida_{role}_session", value=token, httponly=True,
        secure=not settings.DEBUG, samesite="lax", max_age=int((expires - datetime.utcnow()).total_seconds()), path="/",
    )


async def _principal(request: Request, db: AsyncSession, role: str):
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
    return principal


async def require_admin(request: Request, db: AsyncSession = Depends(get_db)) -> AdminUser:
    _require_session_secret()
    return await _principal(request, db, "admin")


async def require_user(request: Request, db: AsyncSession = Depends(get_db)) -> WebUser:
    _require_session_secret()
    return await _principal(request, db, "user")


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
        code = (await db.execute(select(AccessCode).where(AccessCode.code_hash == _hash_access_code(payload.access_code)))).scalar_one_or_none()
        if code is None or code.status != "active" or (code.expires_at and code.expires_at < datetime.utcnow()):
            raise HTTPException(status_code=401, detail="兑换码或验证码错误")
        user = (await db.execute(select(WebUser).where(WebUser.access_code_id == code.id))).scalar_one_or_none()
        if user is None:
            user = WebUser(access_code_id=code.id)
            db.add(user)
            await db.flush()
        user.last_login_at = datetime.utcnow()
        await _issue_session(response, db, "user", user.id)
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
        await _issue_session(response, db, "admin", admin.id)
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
async def get_me(request: Request, db: AsyncSession = Depends(get_db)):
    _require_session_secret()
    for role in ("admin", "user"):
        try:
            principal = await _principal(request, db, role)
            return {"role": role, "id": principal.id, "username": getattr(principal, "username", None)}
        except HTTPException:
            continue
    raise HTTPException(status_code=401, detail="请先登录")


@router.post("/admin/access-codes")
async def create_access_code(payload: AccessCodeCreateIn, response: Response, db: AsyncSession = Depends(get_db), _: AdminUser = Depends(require_admin)):
    agents = (await db.execute(select(Agent.id).where(Agent.id.in_(payload.agent_ids)))).scalars().all()
    if len(set(agents)) != len(set(payload.agent_ids)):
        raise HTTPException(status_code=422, detail="包含不存在的 Agent")
    created = []
    for _ in range(payload.count):
        code_text = _new_access_code()
        code = AccessCode(
            code_hash=_hash_access_code(code_text), code_hint=code_text[-8:], note=payload.note,
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
    if code.status == "active" and code.expires_at and code.expires_at < datetime.utcnow():
        code.status = "expired"
    agent_rows = (await db.execute(
        select(Agent.id, Agent.name).join(AccessCodeAgent, AccessCodeAgent.agent_id == Agent.id)
        .where(AccessCodeAgent.access_code_id == code.id).order_by(Agent.name)
    )).all()
    usage = await db.get(AccessCodeDailyUsage, (code.id, datetime.utcnow().date().isoformat()))
    return {
        "id": code.id, "code_hint": code.code_hint, "status": code.status,
        "daily_question_limit": code.daily_question_limit, "usage_today": usage.question_count if usage else 0,
        "expires_at": code.expires_at, "note": code.note, "created_at": code.created_at,
        "agents": [{"id": agent_id, "name": name} for agent_id, name in agent_rows],
    }


@router.get("/admin/access-codes")
async def list_access_codes(db: AsyncSession = Depends(get_db), _: AdminUser = Depends(require_admin)):
    codes = (await db.execute(select(AccessCode).order_by(AccessCode.created_at.desc()))).scalars().all()
    return {"items": [await _access_code_out(code, db) for code in codes]}


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
    return {"success": True, "id": code.id}


@router.delete("/admin/access-codes/{code_id}")
async def delete_access_code(code_id: int, db: AsyncSession = Depends(get_db), _: AdminUser = Depends(require_admin)):
    code = await db.get(AccessCode, code_id)
    if code is None:
        raise HTTPException(status_code=404, detail="兑换码不存在")
    # 兑换码是网页用户的唯一登录凭据。删除时一并清理对应用户与会话，
    # 以满足外键约束并立即撤销已登录设备的访问权限。
    await db.execute(delete(WebUser).where(WebUser.access_code_id == code.id))
    await db.delete(code)
    return {"success": True, "id": code_id}


@router.post("/admin/access-codes/batch/delete")
async def batch_delete_access_codes(payload: AccessCodeBatchIn, db: AsyncSession = Depends(get_db), _: AdminUser = Depends(require_admin)):
    ids = list(set(payload.ids))
    existing = (await db.execute(select(AccessCode.id).where(AccessCode.id.in_(ids)))).scalars().all()
    if not existing:
        raise HTTPException(status_code=404, detail="未找到可删除的兑换码")
    await db.execute(delete(WebUser).where(WebUser.access_code_id.in_(existing)))
    await db.execute(delete(AccessCode).where(AccessCode.id.in_(existing)))
    return {"success": True, "deleted": len(existing)}
