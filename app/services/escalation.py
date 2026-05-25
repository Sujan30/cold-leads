import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.linq import linq
from app.config import settings
from app.models.lead import Lead

logger = logging.getLogger(__name__)


async def escalate_to_agent(lead: Lead, reason: str, db: AsyncSession | None = None) -> None:
    if not settings.agents_phone:
        logger.warning("AGENTS_PHONE not configured — escalation skipped for lead %s", lead.id)
        return

    recent_snippet = ""
    if db is not None:
        try:
            from sqlalchemy import select
            from app.models.message import Message
            result = await db.execute(
                select(Message)
                .where(Message.lead_id == lead.id)
                .order_by(Message.sent_at.desc())
                .limit(3)
            )
            msgs = list(reversed(result.scalars().all()))
            if msgs:
                lines = []
                for m in msgs:
                    role = "Lead" if m.direction.value == "inbound" else "Agent"
                    lines.append(f"{role}: {m.body[:120]}")
                recent_snippet = "\nRecent chat:\n" + "\n".join(lines)
        except Exception:
            pass

    msg = (
        f"Lead alert — {lead.name}\n"
        f"Looking for: {lead.property_interest or 'N/A'}\n"
        f"Phone: {lead.phone or 'N/A'} | Email: {lead.email or 'N/A'}\n"
        f"Status: {lead.state.value}{recent_snippet}\n"
        f"Why flagged: {reason}"
    )
    try:
        await linq.send(settings.agents_phone, msg)
        logger.info("Escalated lead %s to %s", lead.id, settings.agents_name)
    except Exception as e:
        logger.error("Failed to escalate lead %s: %s", lead.id, e)
