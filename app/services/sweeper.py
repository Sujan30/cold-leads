import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.lead import Lead

logger = logging.getLogger(__name__)

_work_available = asyncio.Event()


def signal_work() -> None:
    """Called by handle_inbound after setting reply_due_at. Non-blocking."""
    _work_available.set()


async def _tick() -> bool:
    """One sweep pass. Returns True if any pending leads still exist (ready or not yet due).
    Returns False only when there is nothing left to wait for — safe to go dormant."""
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        # Process any leads whose timer has expired
        ready_result = await db.execute(
            select(Lead).where(
                Lead.reply_due_at.is_not(None),
                Lead.reply_due_at <= now,
            )
        )
        for lead in ready_result.scalars().all():
            try:
                from app.services.state_machine import process_pending_reply
                await process_pending_reply(lead, db)
            except Exception:
                logger.exception("[SWEEPER] Error processing lead %d", lead.id)

        # Keep the inner loop alive if any lead still has a pending timer
        still_pending = await db.execute(
            select(Lead.id).where(Lead.reply_due_at.is_not(None)).limit(1)
        )
        return still_pending.scalar_one_or_none() is not None


async def run_sweeper() -> None:
    """Long-running asyncio task. Dormant when no replies are pending."""
    logger.info("[SWEEPER] Started — waiting for work")
    while True:
        await _work_available.wait()
        _work_available.clear()
        logger.debug("[SWEEPER] Woke — processing pending replies")
        while True:
            had_work = await _tick()
            if not had_work:
                break
            await asyncio.sleep(1)
        logger.debug("[SWEEPER] Idle — no pending replies")
