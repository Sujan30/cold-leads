import csv
import io
import re

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.lead import Lead, LeadChannel, LeadState, LeadTemperature

router = APIRouter(prefix="/leads")


def _normalize_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return None


@router.get("")
async def list_leads(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Lead).order_by(Lead.created_at.desc()).limit(100))
    leads = result.scalars().all()
    return [
        {
            "id": l.id,
            "name": l.name,
            "phone": l.phone,
            "email": l.email,
            "state": l.state,
            "temperature": l.temperature,
            "consent_verified": l.consent_verified,
        }
        for l in leads
    ]


@router.post("/upload")
async def upload_leads(
    file: UploadFile,
    temperature: str = "aged",
    consent_verified: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """Upload a CSV of leads. Required columns: name, phone or email."""
    if temperature not in ("hot_inbound", "aged"):
        raise HTTPException(400, "temperature must be hot_inbound or aged")

    content = await file.read()
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    created, skipped = 0, 0

    for row in reader:
        name = (row.get("name") or "").strip()
        if not name:
            skipped += 1
            continue

        raw_phone = (row.get("phone") or "").strip()
        phone = _normalize_phone(raw_phone) if raw_phone else None
        email = (row.get("email") or "").strip() or None

        if not phone and not email:
            skipped += 1
            continue

        lead = Lead(
            name=name,
            phone=phone,
            email=email,
            source=row.get("source_url") or row.get("source") or None,
            property_interest=row.get("property_interest") or row.get("notes") or None,
            temperature=LeadTemperature(temperature),
            state=LeadState.new,
            channel=LeadChannel.text if phone else LeadChannel.email,
            consent_verified=consent_verified,
        )
        db.add(lead)
        created += 1

    await db.commit()
    return {"created": created, "skipped": skipped}
