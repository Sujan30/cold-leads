import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.base import InboundMessage
from app.channels.linq import linq
from app.channels.sendgrid import sendgrid
from app.config import settings
from app.models.lead import Lead, LeadChannel, LeadState, LeadTemperature
from app.models.message import Message, MessageChannel, MessageDirection
from app.services import cadence, classifier, drafter
from app.services.escalation import escalate_to_agent

logger = logging.getLogger(__name__)

DEBOUNCE_SECS = 10
MAX_WAIT_SECS = 20

# Per-lead locks prevent two simultaneous webhooks from racing on reply_first_pending_at
_lead_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

_INJECTION_PATTERNS = (
    "ignore previous instructions",
    "ignore all previous",
    "disregard previous",
    "forget your instructions",
    "you are now",
    "act as",
    "reveal your",
    "tell me your api key",
    "show me your .env",
    "what is your api key",
    "anthropic api key",
    "system prompt",
)


def _is_injection_attempt(body: str) -> bool:
    lowered = body.lower()
    return any(pattern in lowered for pattern in _INJECTION_PATTERNS)


async def _append_message(
    lead_id: int,
    direction: MessageDirection,
    channel: MessageChannel,
    body: str,
    db: AsyncSession,
    ai_model: str | None = None,
    intent: str | None = None,
) -> None:
    db.add(
        Message(
            lead_id=lead_id,
            direction=direction,
            channel=channel,
            body=body,
            ai_model=ai_model,
            intent=intent,
        )
    )


async def _get_history(lead_id: int, db: AsyncSession) -> list[dict]:
    result = await db.execute(
        select(Message)
        .where(Message.lead_id == lead_id)
        .order_by(Message.sent_at)
    )
    msgs = result.scalars().all()
    return [
        {
            "role": "user" if m.direction == MessageDirection.inbound else "assistant",
            "content": m.body,
        }
        for m in msgs
    ]


# ── Proactive outbound handlers ───────────────────────────────────────────────

async def _handle_new(lead: Lead, db: AsyncSession) -> None:
    from app.integrations import twenty
    logger.info("[STATE] handle_new — lead=%d name=%r temp=%s", lead.id, lead.name, lead.temperature)
    assert lead.consent_verified, f"Lead {lead.id} not consent-verified — blocking send"

    if lead.temperature == LeadTemperature.hot_inbound and lead.phone:
        text = await drafter.draft_first_touch_text(lead.name, lead.property_interest or "")
        result = await linq.send_first_touch(lead.phone, text)
        if result.get("_chat_id"):
            lead.linq_chat_id = result["_chat_id"]
        await _append_message(
            lead.id, MessageDirection.outbound, MessageChannel.text, text, db, ai_model="claude-haiku-4-5-20251001"
        )
        lead.channel = LeadChannel.text
        lead.state = LeadState.contacted
        await cadence.schedule_text_cadence(lead.id, db)
        await cadence.schedule_email_cadence(lead.id, db)
        logger.info("Hot lead %s (%s) — first text sent", lead.id, lead.name)

    elif lead.email:
        subject, body = await drafter.draft_first_touch_email(lead.name, lead.property_interest or "")
        await sendgrid.send(lead.email, body, subject=subject)
        await _append_message(
            lead.id, MessageDirection.outbound, MessageChannel.email, body, db, ai_model="claude-haiku-4-5-20251001"
        )
        lead.channel = LeadChannel.email
        lead.state = LeadState.contacted
        await cadence.schedule_email_cadence(lead.id, db)
        logger.info("Aged lead %s (%s) — first email sent", lead.id, lead.name)

    else:
        logger.warning("Lead %s has no phone or email — skipping", lead.id)

    await db.commit()
    await twenty.sync_lead(lead, db)


async def _handle_contacted(lead: Lead, db: AsyncSession) -> None:
    pass


async def _handle_engaged(lead: Lead, db: AsyncSession) -> None:
    pass


async def _handle_qualifying(lead: Lead, db: AsyncSession) -> None:
    pass


async def _handle_no_reply(lead: Lead, db: AsyncSession) -> None:
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    if lead.updated_at.replace(tzinfo=timezone.utc) < cutoff:
        lead.state = LeadState.dormant
        await db.commit()
        logger.info("Lead %s moved to DORMANT (30 days no reply)", lead.id)


async def _no_op(lead: Lead, db: AsyncSession) -> None:
    pass


DISPATCH = {
    LeadState.new: _handle_new,
    LeadState.contacted: _handle_contacted,
    LeadState.engaged: _handle_engaged,
    LeadState.qualifying: _handle_qualifying,
    LeadState.no_reply: _handle_no_reply,
    LeadState.dormant: _no_op,
    LeadState.handed_off: _no_op,
    LeadState.booked: _no_op,
}


async def process_lead(lead: Lead, db: AsyncSession) -> None:
    handler = DISPATCH.get(lead.state, _no_op)
    await handler(lead, db)


# ── Phase 1: inbound webhook entry point (fast — no AI calls) ─────────────────

async def handle_inbound(msg: InboundMessage, db: AsyncSession) -> None:
    """Saves the message and arms the debounce timer. Never calls AI."""
    from app.integrations import twenty
    logger.info("[INBOUND] channel=%s sender=%s body=%r", msg.channel, msg.sender, msg.body[:100])

    if msg.channel == "text":
        result = await db.execute(select(Lead).where(Lead.phone == msg.sender))
    else:
        result = await db.execute(select(Lead).where(Lead.email == msg.sender))

    lead = result.scalar_one_or_none()
    if not lead:
        logger.warning("[INBOUND] No lead found for sender %s — ignoring", msg.sender)
        return
    logger.info("[INBOUND] Matched lead=%d %r state=%s", lead.id, lead.name, lead.state)

    async with _lead_locks[lead.id]:
        if msg.chat_id and not lead.linq_chat_id:
            lead.linq_chat_id = msg.chat_id

        ch = MessageChannel.text if msg.channel == "text" else MessageChannel.email
        await _append_message(lead.id, MessageDirection.inbound, ch, msg.body, db)

        await cadence.cancel_cadence(lead.id, db)

        if lead.state in (LeadState.new, LeadState.contacted, LeadState.no_reply):
            lead.state = LeadState.engaged

        if _is_injection_attempt(msg.body):
            logger.warning("[INBOUND] Injection attempt from lead=%d — dropping", lead.id)
            await db.commit()
            return

        now = datetime.now(timezone.utc)
        if lead.reply_first_pending_at is None:
            lead.reply_first_pending_at = now

        cap = lead.reply_first_pending_at + timedelta(seconds=MAX_WAIT_SECS)
        lead.reply_due_at = min(now + timedelta(seconds=DEBOUNCE_SECS), cap)

        await db.commit()
        await twenty.sync_lead(lead, db)

    from app.services.sweeper import signal_work
    signal_work()
    logger.info("[INBOUND] reply_due_at set for lead=%d — sweeper signalled", lead.id)


# ── Phase 2: deferred reply processing (called by sweeper) ───────────────────

async def process_pending_reply(lead: Lead, db: AsyncSession) -> None:
    """Processes a lead whose debounce timer has expired. Called only by the sweeper."""
    from app.integrations import twenty

    # Skip terminal states — nothing to reply to
    if lead.state in (LeadState.dormant, LeadState.booked, LeadState.handed_off):
        lead.reply_due_at = None
        lead.reply_first_pending_at = None
        await db.commit()
        return

    # Atomic claim: clear the timer before any API calls so a crash can't double-process
    lead.reply_due_at = None
    lead.reply_first_pending_at = None
    await db.commit()
    logger.info("[SWEEPER] Processing pending reply for lead=%d %r", lead.id, lead.name)

    # Find the pending burst: all inbound messages since the last outbound
    last_out_result = await db.execute(
        select(Message)
        .where(Message.lead_id == lead.id, Message.direction == MessageDirection.outbound)
        .order_by(Message.sent_at.desc())
        .limit(1)
    )
    last_out = last_out_result.scalar_one_or_none()
    cutoff = last_out.sent_at if last_out else datetime.min.replace(tzinfo=timezone.utc)

    pending_result = await db.execute(
        select(Message)
        .where(
            Message.lead_id == lead.id,
            Message.direction == MessageDirection.inbound,
            Message.sent_at > cutoff,
        )
        .order_by(Message.sent_at)
    )
    pending_msgs = pending_result.scalars().all()

    if not pending_msgs:
        logger.info("[SWEEPER] No pending messages for lead=%d — nothing to reply to", lead.id)
        return

    combined_latest = "\n".join(m.body for m in pending_msgs)
    inbound_channel = pending_msgs[-1].channel  # use channel of the most recent message

    if len(pending_msgs) > 1:
        logger.info("[SWEEPER] Combining %d messages for lead=%d: %r", len(pending_msgs), lead.id, combined_latest[:120])

    if _is_injection_attempt(combined_latest):
        logger.warning("[SWEEPER] Injection attempt in combined messages for lead=%d — dropping", lead.id)
        return

    # Build history: full conversation excluding the pending burst
    full_history = await _get_history(lead.id, db)
    history_for_prompt = full_history[:-len(pending_msgs)] if len(pending_msgs) < len(full_history) else []
    recent_context = history_for_prompt[-4:]

    intent = await classifier.classify(combined_latest, context=recent_context)
    logger.info("[SWEEPER] lead=%d intent=%s", lead.id, intent)

    if intent == "not_interested":
        lead.state = LeadState.dormant
        await db.commit()
        await twenty.sync_lead(lead, db)
        return

    if intent == "wrong_number":
        lead.state = LeadState.dormant
        await db.commit()
        await twenty.sync_lead(lead, db)
        return

    if intent == "ready_to_book":
        from app.integrations import calcom
        from app.services import booking as booking_svc

        proposed = await booking_svc.extract_proposed_time(combined_latest)
        logger.info("[BOOKING] lead=%d proposed_time=%s email=%s", lead.id, proposed, lead.email)

        if proposed and lead.email:
            logger.info("[BOOKING] lead=%d checking Cal.com availability for %s", lead.id, proposed)
            available = await calcom.is_slot_available(proposed)
            logger.info("[BOOKING] lead=%d slot_available=%s", lead.id, available)
            if available:
                notes = f"Lead property interest: {lead.property_interest or 'not specified'}"
                logger.info("[BOOKING] lead=%d calling create_booking", lead.id)
                uid = await calcom.create_booking(lead.name, lead.email, proposed, notes=notes)
                logger.info("[BOOKING] lead=%d create_booking uid=%s", lead.id, uid)
                if uid:
                    lead.calcom_booking_id = uid
                    lead.state = LeadState.booked
                    slot_str = booking_svc.format_slot(proposed)
                    confirmation = (
                        f"You're all set! I've booked a 30-minute call with {settings.agents_name} "
                        f"for {slot_str}. You'll get a calendar invite at {lead.email}. Talk soon!"
                    )
                    await db.commit()
                    await twenty.sync_lead(lead, db)
                    await escalate_to_agent(
                        lead, f"Auto-booked via Cal.com — uid={uid} slot={slot_str}", db
                    )
                else:
                    lead.state = LeadState.booked
                    link = calcom.booking_link()
                    confirmation = (
                        f"Great! You can grab a time directly here: {link} — "
                        f"pick whatever works best for you and you'll get a confirmation right away."
                    )
                    await db.commit()
                    await escalate_to_agent(
                        lead, f"Lead wants to book — Cal.com create_booking failed, sent link", db
                    )
            else:
                logger.info("[BOOKING] lead=%d slot not available — fetching next slots", lead.id)
                next_slots = await calcom.get_next_slots(3)
                logger.info("[BOOKING] lead=%d next_slots=%s", lead.id, next_slots)
                if next_slots:
                    slot_strs = [booking_svc.format_slot(s) for s in next_slots]
                    confirmation = (
                        f"That time might not work — here are a few open slots with "
                        f"{settings.agents_name}: {slot_strs[0]}, {slot_strs[1]}, or {slot_strs[2]}. "
                        f"Do any of those work for you?"
                    )
                else:
                    link = calcom.booking_link()
                    confirmation = (
                        f"Let me have {settings.agents_name} confirm a time that works. "
                        f"You can also grab a slot directly: {link}"
                    )
                    lead.state = LeadState.booked
                    await db.commit()
                    await escalate_to_agent(
                        lead, f"Lead wants to book — no slots available, sent link", db
                    )
        elif proposed is None:
            # Lead wants to book but didn't mention a time — ask with available slots
            logger.info("[BOOKING] lead=%d no time in message — offering next slots", lead.id)
            next_slots = await calcom.get_next_slots(3)
            logger.info("[BOOKING] lead=%d next_slots=%s", lead.id, next_slots)
            if next_slots:
                slot_strs = [booking_svc.format_slot(s) for s in next_slots]
                slots_text = ", ".join(slot_strs[: len(next_slots)])
                confirmation = (
                    f"Great! Here are a few open times with {settings.agents_name}: "
                    f"{slots_text}. Do any of those work for you?"
                )
                # Stay in current state — lead needs to confirm a time
            else:
                logger.info("[BOOKING] lead=%d no slots available — sending link", lead.id)
                lead.state = LeadState.booked
                link = calcom.booking_link()
                confirmation = (
                    f"Perfect! Here's the link to book a 30-minute call with {settings.agents_name}: "
                    f"{link} — just pick a time that works and you'll get a confirmation instantly."
                )
                await db.commit()
                await escalate_to_agent(lead, f"Lead wants to book — no slots available, sent link", db)
        else:
            # Has a proposed time but no email — can't auto-book without email
            logger.info("[BOOKING] lead=%d has time but no email — sending link", lead.id)
            lead.state = LeadState.booked
            link = calcom.booking_link()
            confirmation = (
                f"Perfect! Here's the link to book a 30-minute call with {settings.agents_name}: "
                f"{link} — just pick a time that works and you'll get a confirmation instantly."
            )
            await db.commit()
            await escalate_to_agent(lead, f"Lead wants to book — no email on file, sent link", db)

        if inbound_channel == MessageChannel.text and lead.phone:
            if lead.linq_chat_id:
                await linq.send_to_chat(lead.linq_chat_id, confirmation)
            else:
                await linq.send(lead.phone, confirmation)
            await _append_message(lead.id, MessageDirection.outbound, MessageChannel.text, confirmation, db)
        elif lead.email:
            await sendgrid.send(lead.email, confirmation, subject=f"Meeting with {settings.agents_name}")
            await _append_message(lead.id, MessageDirection.outbound, MessageChannel.email, confirmation, db)
        await db.commit()
        return

    # Draft and send a conversational reply
    use_sonnet = intent == "question" and len(combined_latest) > 100
    logger.info("[SWEEPER] Drafting reply for lead=%d model=%s", lead.id, "sonnet" if use_sonnet else "haiku")
    reply_text = await drafter.draft_reply(
        lead.name, history_for_prompt, combined_latest, use_sonnet=use_sonnet
    )
    logger.info("[SWEEPER] Reply for lead=%d: %r", lead.id, reply_text[:100])

    if inbound_channel == MessageChannel.text and lead.phone:
        if lead.linq_chat_id:
            await linq.send_to_chat(lead.linq_chat_id, reply_text)
        else:
            await linq.send(lead.phone, reply_text)
        await _append_message(
            lead.id,
            MessageDirection.outbound,
            MessageChannel.text,
            reply_text,
            db,
            ai_model="claude-sonnet-4-6" if use_sonnet else "claude-haiku-4-5-20251001",
            intent=intent,
        )
    elif lead.email:
        await sendgrid.send(lead.email, reply_text)
        await _append_message(
            lead.id,
            MessageDirection.outbound,
            MessageChannel.email,
            reply_text,
            db,
            ai_model="claude-haiku-4-5-20251001",
            intent=intent,
        )

    if lead.state == LeadState.engaged and intent == "interested":
        lead.state = LeadState.qualifying

    await db.commit()
    await twenty.sync_lead(lead, db)
