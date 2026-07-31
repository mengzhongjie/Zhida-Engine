import hashlib

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.v1.knowledge.router import _find_duplicate_document
from app.core.database import Base
from app.models.agent import Agent
from app.models.knowledge import Document, KnowledgeBase


@pytest.mark.asyncio
async def test_reupload_backfills_legacy_hash_and_returns_existing_document(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'knowledge.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    content = b"same knowledge document"
    upload_path = tmp_path / "guide.txt"
    upload_path.write_bytes(content)
    content_hash = hashlib.sha256(content).hexdigest()
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async with sessions() as db:
        db.add(Agent(name="test-agent"))
        await db.flush()
        kb = KnowledgeBase(name="test-kb")
        db.add(kb)
        await db.flush()
        document = Document(
            knowledge_base_id=kb.id,
            filename="guide.txt",
            file_type="txt",
            file_path=str(upload_path),
            file_size=len(content),
            status="completed",
        )
        db.add(document)
        await db.flush()

        duplicate = await _find_duplicate_document(
            db, kb.id, "guide.txt", len(content), content_hash
        )
        assert duplicate is not None
        assert duplicate.id == document.id
        assert duplicate.content_hash == content_hash
        await db.commit()

    await engine.dispose()


@pytest.mark.asyncio
async def test_database_rejects_same_hash_in_one_knowledge_base(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'unique.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async with sessions() as db:
        kb = KnowledgeBase(name="test-kb")
        db.add(kb)
        await db.flush()
        for path in ("/tmp/a.txt", "/tmp/b.txt"):
            db.add(Document(
                knowledge_base_id=kb.id,
                filename="guide.txt",
                file_type="txt",
                file_path=path,
                file_size=1,
                content_hash="a" * 64,
            ))
        with pytest.raises(IntegrityError):
            await db.flush()

    await engine.dispose()
