from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.follow_up import FollowUp

# Email cadence: touch days after initial contact
EMAIL_DAYS = [2, 5, 9, 16]

# Text: at most 2 gentle touches, spaced further apart
TEXT_DAYS = [3, 8]
TEXT_MAX_TOUCHES = 2


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def schedule_email_cadence(lead_id: int, db: AsyncSession) -> None:
    for i, days in enumerate(EMAIL_DAYS, start=1):
        fu = FollowUp(
            lead_id=lead_id,
            scheduled_for=_now() + timedelta(days=days),
            touch_number=i,
            sent=False,
        )
        db.add(fu)
    await db.commit()


async def schedule_text_cadence(lead_id: int, db: AsyncSession) -> None:
    for i, days in enumerate(TEXT_DAYS, start=1):
        fu = FollowUp(
            lead_id=lead_id,
            scheduled_for=_now() + timedelta(days=days),
            touch_number=i,
            sent=False,
        )
        db.add(fu)
    await db.commit()


async def cancel_cadence(lead_id: int, db: AsyncSession) -> None:
    """Mark all pending follow-ups as sent (effectively cancels them)."""
    from sqlalchemy import update
    from app.models.follow_up import FollowUp

    await db.execute(
        update(FollowUp)
        .where(FollowUp.lead_id == lead_id, FollowUp.sent == False)  # noqa: E712
        .values(sent=True)
    )
    await db.commit()
