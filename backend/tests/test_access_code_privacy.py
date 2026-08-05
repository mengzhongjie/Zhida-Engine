"""一次性激活码与用户会话隐私边界回归测试。"""

import hashlib
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.v1.auth.router import UserLoginIn, _hash_access_code, user_login  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.database import Base  # noqa: E402
from app.models.auth import AccessCode, AdminUser, AuthSession, CaptchaChallenge, WebUser  # noqa: E402,F401
# 注册全部 ORM 关系，避免仅加载认证路由时 SQLAlchemy 无法解析 Agent 的关联模型。
import app.models.agent_knowledge_base  # noqa: E402,F401
import app.models.embedding_config  # noqa: E402,F401
import app.models.embedding_profile  # noqa: E402,F401
import app.models.feishu_config  # noqa: E402,F401
import app.models.import_job  # noqa: E402,F401
import app.models.knowledge  # noqa: E402,F401
import app.models.llm_config  # noqa: E402,F401
import app.models.persona_preset  # noqa: E402,F401
import app.models.vision_config  # noqa: E402,F401
import app.models.web_search_config  # noqa: E402,F401


def _request() -> Request:
    return Request({
        "type": "http", "method": "POST", "scheme": "https", "path": "/api/v1/auth/user/login",
        "headers": [(b"host", b"app.example.com"), (b"x-forwarded-proto", b"https")],
        "client": ("203.0.113.10", 12345),
    })


async def _captcha(db, challenge_id: str, answer: str = "ABCDE") -> None:
    db.add(CaptchaChallenge(
        id=challenge_id, purpose="user",
        answer_hash=hashlib.sha256(f"{challenge_id}:{answer}".encode()).hexdigest(),
        image_svg="<svg/>", expires_at=datetime.utcnow() + timedelta(minutes=5),
    ))
    await db.commit()


@pytest.mark.asyncio
async def test_access_code_can_only_activate_one_private_user(tmp_path):
    """激活后销毁可复制明文，第二次登录不能看到同一用户历史。"""
    original_secret = settings.AUTH_SESSION_SECRET
    settings.AUTH_SESSION_SECRET = "test-secret-which-is-at-least-thirty-two-characters"
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'auth.db'}")
    Session = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            # 认证路由只依赖以下几张表；避免测试进程只导入部分业务模型时
            # Base.metadata 的无关外键干扰此安全回归测试。
            for table in (AdminUser.__table__, AccessCode.__table__, WebUser.__table__, CaptchaChallenge.__table__, AuthSession.__table__):
                await connection.run_sync(table.create)
        code_text = "ABCD-EFGH-JKLM-NPQR-STUV-WXYZ"
        async with Session() as db:
            db.add(AccessCode(
                code_hash=_hash_access_code(code_text), code_hint=code_text[-8:], code_ciphertext="encrypted",
            ))
            await db.commit()
            await _captcha(db, "first")

            response = Response()
            result = await user_login(
                UserLoginIn(access_code=code_text, captcha_id="first", captcha_answer="ABCDE"),
                _request(), response, db,
            )
            await db.commit()
            assert result["role"] == "user"
            cookie = next(value for value in response.headers.getlist("set-cookie") if value.startswith("zhida_user_session="))
            assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie

            code = (await db.execute(select(AccessCode))).scalar_one()
            assert code.status == "claimed"
            assert code.code_ciphertext is None
            assert len((await db.execute(select(WebUser))).scalars().all()) == 1

            await _captcha(db, "second")
            with pytest.raises(HTTPException) as exc:
                await user_login(
                    UserLoginIn(access_code=code_text, captcha_id="second", captcha_answer="ABCDE"),
                    _request(), Response(), db,
                )
            assert exc.value.status_code == 401
            assert len((await db.execute(select(WebUser))).scalars().all()) == 1
    finally:
        settings.AUTH_SESSION_SECRET = original_secret
        await engine.dispose()
