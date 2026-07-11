from datetime import datetime

from app.schemas.miniapp import InvitationCreate


def test_expiry_with_iso_timezone_is_normalized_for_sqlite_comparison():
    invitation = InvitationCreate(
        daily_question_limit=2,
        expires_at="2026-07-12T20:00:00+08:00",
    )

    assert invitation.expires_at == datetime(2026, 7, 12, 12, 0, 0)
    assert invitation.expires_at.tzinfo is None
