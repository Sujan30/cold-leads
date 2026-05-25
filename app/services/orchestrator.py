import logging
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.follow_up import FollowUp
from app.models.lead import Lead, LeadState
from app.services.state_machine import process_lead

logger = logging.getLogger(__name__)

# States the orchestrator acts on during its scan
ACTIONABLE_STATES = {LeadState.new}


async def run_orchestrator() -> None:
    """Scan for NEW leads and kick off their first touch."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Lead).where(
                Lead.state.in_(ACTIONABLE_STATES),
                Lead.consent_verified == True,  # noqa: E712
            )
        )
        leads = result.scalars().all()
        logger.info("Orchestrator: %d actionable leads", len(leads))
        for lead in leads:
            try:
                await process_lead(lead, db)
            except Exception as e:
                logger.exception("Error processing lead %s", lead.id)


async def run_follow_ups() -> None:
    """Fire any follow-ups whose scheduled_for has passed."""
    from app.channels.linq import linq
    from app.channels.sendgrid import sendgrid
    from app.models.message import Message, MessageChannel, MessageDirection
    from app.services import drafter

    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(FollowUp, Lead)
            .join(Lead, FollowUp.lead_id == Lead.id)
            .where(
                FollowUp.sent == False,  # noqa: E712
                FollowUp.scheduled_for <= now,
                Lead.state.in_([LeadState.contacted, LeadState.no_reply]),
            )
        )
        rows = result.all()
        logger.info("Follow-up runner: %d due", len(rows))

        for fu, lead in rows:
            try:
                if lead.channel.value == "text" and lead.phone and fu.touch_number <= 2:
                    text = await drafter.draft_first_touch_text(
                        lead.name, lead.property_interest or ""
                    )
                    await linq.send(lead.phone, text)
                    db.add(
                        Message(
                            lead_id=lead.id,
                            direction=MessageDirection.outbound,
                            channel=MessageChannel.text,
                            body=text,
                            ai_model="claude-haiku-4-5-20251001",
                        )
                    )
                elif lead.email:
                    subject, body = await drafter.draft_first_touch_email(
                        lead.name, lead.property_interest or ""
                    )
                    await sendgrid.send(lead.email, body, subject=subject)
                    db.add(
                        Message(
                            lead_id=lead.id,
                            direction=MessageDirection.outbound,
                            channel=MessageChannel.email,
                            body=body,
                            ai_model="claude-haiku-4-5-20251001",
                        )
                    )

                fu.sent = True
                if lead.state == LeadState.contacted:
                    lead.state = LeadState.no_reply

            except Exception as e:
                logger.error("Follow-up failed for lead %s (fu %s): %s", lead.id, fu.id, e)

        await db.commit()
