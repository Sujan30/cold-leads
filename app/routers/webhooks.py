import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, BackgroundTasks, Request, Response
from sqlalchemy import select

from app.channels.linq import linq
from app.channels.sendgrid import sendgrid
from app.config import settings
from app.database import AsyncSessionLocal

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks")


async def _handle_inbound_text(payload: dict):
    logger.info("[LINQ] Processing inbound payload: %s", payload)
    msg = linq.parse_inbound(payload)
    if not msg:
        logger.warning("[LINQ] Could not parse inbound message from payload — skipping")
        return
    logger.info("[LINQ] Inbound from %s: %r", msg.sender, msg.body[:120])
    try:
        async with AsyncSessionLocal() as db:
            from app.services.state_machine import handle_inbound
            await handle_inbound(msg, db)
    except Exception as e:
        logger.exception("[LINQ] Error handling inbound message from %s: %s", msg.sender, e)


async def _handle_inbound_email(payload: dict):
    logger.info("[SENDGRID] Inbound email payload keys: %s", list(payload.keys()))
    msg = sendgrid.parse_inbound(payload)
    if not msg:
        logger.warning("[SENDGRID] Could not parse inbound email — skipping")
        return
    logger.info("[SENDGRID] Inbound from %s: %r", msg.sender, msg.body[:120])
    try:
        async with AsyncSessionLocal() as db:
            from app.services.state_machine import handle_inbound
            await handle_inbound(msg, db)
    except Exception as e:
        logger.exception("[SENDGRID] Error handling inbound email from %s: %s", msg.sender, e)


async def _process_linq_request(request: Request, background_tasks: BackgroundTasks):
    body_bytes = await request.body()
    logger.info("[LINQ WEBHOOK] Received POST — %d bytes — headers: %s",
                len(body_bytes), dict(request.headers))

    sig = request.headers.get("x-linq-signature", "")
    if sig and not linq.verify_signature(body_bytes, sig):
        logger.warning("[LINQ WEBHOOK] Signature mismatch — rejecting request")
        return Response(status_code=401)

    try:
        import json
        payload = json.loads(body_bytes)
    except Exception:
        logger.error("[LINQ WEBHOOK] Failed to parse JSON body: %r", body_bytes[:200])
        return Response(status_code=400)

    logger.info("[LINQ WEBHOOK] Payload event=%s from=%s",
                payload.get("event") or payload.get("type"), payload.get("from") or payload.get("sender"))
    background_tasks.add_task(_handle_inbound_text, payload)
    return {"ok": True}


async def _handle_calcom_event(payload: dict) -> None:
    trigger = payload.get("triggerEvent", "")
    logger.info("[CALCOM] Event: %s", trigger)

    if trigger not in ("BOOKING_CREATED", "BOOKING_RESCHEDULED", "BOOKING_CANCELLED"):
        return

    attendee_email = None
    attendee_name = None
    booking_uid = payload.get("uid") or payload.get("bookingUid")

    # Cal.com webhook payload: attendees is a list
    attendees = payload.get("attendees", [])
    if attendees:
        attendee_email = attendees[0].get("email")
        attendee_name = attendees[0].get("name")
    # Fallback: some payloads put it at top level
    if not attendee_email:
        attendee_email = payload.get("email") or payload.get("attendeeEmail")

    if not attendee_email:
        logger.warning("[CALCOM] No attendee email in payload — cannot match lead")
        return

    async with AsyncSessionLocal() as db:
        from app.models.lead import Lead, LeadState
        result = await db.execute(select(Lead).where(Lead.email == attendee_email))
        lead = result.scalar_one_or_none()
        if not lead:
            logger.warning("[CALCOM] No lead found for email %s", attendee_email)
            return

        if trigger == "BOOKING_CREATED":
            lead.calcom_booking_id = booking_uid
            lead.state = LeadState.booked
            logger.info("[CALCOM] Lead %d (%s) → booked uid=%s", lead.id, lead.name, booking_uid)
        elif trigger == "BOOKING_CANCELLED":
            lead.state = LeadState.engaged
            lead.calcom_booking_id = None
            logger.info("[CALCOM] Lead %d (%s) booking cancelled — reverted to engaged", lead.id, lead.name)
        elif trigger == "BOOKING_RESCHEDULED":
            new_uid = payload.get("uid")
            if new_uid:
                lead.calcom_booking_id = new_uid
            logger.info("[CALCOM] Lead %d (%s) booking rescheduled uid=%s", lead.id, lead.name, new_uid)

        await db.commit()


@router.post("/calcom")
async def calcom_webhook(request: Request, background_tasks: BackgroundTasks):
    body_bytes = await request.body()

    # Verify HMAC-SHA256 signature if secret is configured
    if settings.cal_secret:
        sig = request.headers.get("x-cal-signature-256", "")
        expected = hmac.new(
            settings.cal_secret.encode(), body_bytes, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig, expected):
            logger.warning("[CALCOM WEBHOOK] Signature mismatch — rejecting")
            return Response(status_code=401)

    try:
        payload = json.loads(body_bytes)
    except Exception:
        logger.error("[CALCOM WEBHOOK] Invalid JSON: %r", body_bytes[:200])
        return Response(status_code=400)

    background_tasks.add_task(_handle_calcom_event, payload)
    return {"ok": True}


@router.post("/linq")
async def linq_webhook(request: Request, background_tasks: BackgroundTasks):
    return await _process_linq_request(request, background_tasks)


@router.post("/sendgrid")
async def sendgrid_webhook(request: Request, background_tasks: BackgroundTasks):
    form = await request.form()
    payload = dict(form)
    logger.info("[SENDGRID WEBHOOK] Received POST — keys: %s", list(payload.keys()))
    background_tasks.add_task(_handle_inbound_email, payload)
    return {"ok": True}
