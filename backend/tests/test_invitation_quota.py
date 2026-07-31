from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.v1.miniapp.router import _consume_invitation_quota


@pytest.mark.asyncio
async def test_invitation_quota_cannot_exceed_its_daily_limit(tmp_path):
    """单张邀请码的 2 次额度绝不能被重复请求写成 3 次。"""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'quota.db'}")
    async with engine.begin() as conn:
        await conn.execute(text(
            "CREATE TABLE invitation_daily_usage ("
            "id INTEGER PRIMARY KEY, claim_id INTEGER NOT NULL, usage_date DATE NOT NULL, "
            "question_count INTEGER NOT NULL DEFAULT 0, UNIQUE(claim_id, usage_date))"
        ))

    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        assert await _consume_invitation_quota(db, claim_id=7, daily_limit=2)
        assert await _consume_invitation_quota(db, claim_id=7, daily_limit=2)
        assert not await _consume_invitation_quota(db, claim_id=7, daily_limit=2)
        await db.commit()

    async with sessions() as db:
        count = (await db.execute(
            text("SELECT question_count FROM invitation_daily_usage WHERE claim_id = 7 AND usage_date = :today"),
            {"today": date.today()},
        )).scalar_one()
        assert count == 2

    await engine.dispose()
