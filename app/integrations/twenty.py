"""
Twenty CRM sync service (one-way: Neon DB → Twenty).

All Twenty API calls are wrapped in try/except so a Twenty outage
never blocks SMS delivery or any other core functionality.
"""

import logging

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.lead import Lead, LeadState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Stage mapping: LeadState → Twenty Opportunity stage
# ---------------------------------------------------------------------------

_STATE_TO_STAGE: dict[LeadState, str] = {
    LeadState.new: "NEW",
    LeadState.contacted: "NEW",
    LeadState.no_reply: "NEW",
    LeadState.engaged: "SCREENING",
    LeadState.qualifying: "SCREENING",
    LeadState.booked: "MEETING",
    LeadState.handed_off: "MEETING",
    LeadState.dormant: "CLOSED_LOST",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_configured() -> bool:
    """Return True only when both required Twenty settings are present."""
    return bool(settings.twenty_api_url and settings.twenty_api_key)


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.twenty_api_key}",
        "Content-Type": "application/json",
    }


def _parse_name(full_name: str) -> tuple[str, str]:
    """Split a full name into (firstName, lastName). lastName defaults to ''."""
    parts = full_name.strip().split(" ", 1)
    first = parts[0]
    last = parts[1] if len(parts) > 1 else ""
    return first, last


def _build_person_data(lead: Lead) -> dict:
    """Build the person data dict for the Twenty GraphQL mutation."""
    first, last = _parse_name(lead.name)
    data: dict = {
        "name": {"firstName": first, "lastName": last},
    }

    if lead.email is not None:
        data["emails"] = {"primaryEmail": lead.email}

    if lead.phone is not None:
        # Strip a leading +1 if present; keep the remaining digits as the number.
        raw = lead.phone.strip()
        if raw.startswith("+1"):
            number = raw[2:]
        elif raw.startswith("1") and len(raw) == 11:
            number = raw[1:]
        else:
            number = raw
        data["phones"] = {
            "primaryPhoneNumber": number,
            "primaryPhoneCountryCode": "US",
            "primaryPhoneCallingCode": "+1",
        }

    # Include the existing ID so Twenty upserts by ID rather than deduplicating
    # on email/phone (which could match the wrong record on edge cases).
    if lead.twenty_person_id:
        data["id"] = lead.twenty_person_id

    return data


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def upsert_person(lead: Lead, db: AsyncSession) -> None:
    """
    Create or update the Twenty Person record that corresponds to *lead*.

    Persists the returned Twenty person ID back to lead.twenty_person_id and
    commits the session if the ID changed.  All errors are caught and logged;
    this function never raises.
    """
    try:
        if not _is_configured():
            return

        person_data = _build_person_data(lead)

        mutation = """
        mutation CreatePeople($data: [PersonCreateInput!]!, $upsert: Boolean) {
          createPeople(data: $data, upsert: $upsert) {
            id
            name { firstName lastName }
          }
        }
        """
        variables = {"data": [person_data], "upsert": True}

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{settings.twenty_api_url}/graphql",
                headers=_headers(),
                json={"query": mutation, "variables": variables},
            )

        if resp.status_code != 200:
            logger.error(
                "[TWENTY] upsert_person failed HTTP %d for lead_id=%s: %s",
                resp.status_code,
                lead.id,
                resp.text[:300],
            )
            return

        body = resp.json()
        errors = body.get("errors")
        if errors:
            logger.error(
                "[TWENTY] upsert_person GraphQL errors for lead_id=%s: %s",
                lead.id,
                errors,
            )
            return

        records = body.get("data", {}).get("createPeople", [])
        if not records:
            logger.warning("[TWENTY] upsert_person returned empty records for lead_id=%s", lead.id)
            return

        returned_id: str = records[0]["id"]
        logger.info("[TWENTY] person upserted id=%s for lead_id=%s", returned_id, lead.id)

        if lead.twenty_person_id != returned_id:
            lead.twenty_person_id = returned_id
            await db.commit()

    except Exception:
        logger.exception("[TWENTY] upsert_person unexpected error for lead_id=%s", lead.id)


async def upsert_opportunity(lead: Lead, db: AsyncSession) -> None:
    """
    Create or update the Twenty Opportunity linked to *lead*'s Person record.

    Stage is derived from lead.state.  The returned opportunity ID is stored
    in lead.twenty_opportunity_id and committed.  All errors are caught and
    logged; this function never raises.
    """
    try:
        if not _is_configured():
            return

        if not lead.twenty_person_id:
            logger.debug(
                "[TWENTY] upsert_opportunity skipped — no twenty_person_id for lead_id=%s",
                lead.id,
            )
            return

        stage = _STATE_TO_STAGE.get(lead.state, "NEW")
        opportunity_name = f"{lead.name} — {lead.source or 'Cold Lead'}"

        # ------------------------------------------------------------------
        # If we already have an opportunity ID, update it directly.
        # ------------------------------------------------------------------
        if lead.twenty_opportunity_id:
            returned_id = await _update_opportunity_stage(
                lead.twenty_opportunity_id, stage, lead.id
            )
            if returned_id and lead.twenty_opportunity_id != returned_id:
                lead.twenty_opportunity_id = returned_id
                await db.commit()
            return

        # ------------------------------------------------------------------
        # No local ID — check whether one already exists in Twenty for this
        # Person so we don't create duplicates.
        # ------------------------------------------------------------------
        existing_id = await _find_opportunity_for_person(lead.twenty_person_id, lead.id)

        if existing_id:
            lead.twenty_opportunity_id = existing_id
            returned_id = await _update_opportunity_stage(existing_id, stage, lead.id)
            if returned_id:
                lead.twenty_opportunity_id = returned_id
            await db.commit()
            return

        # ------------------------------------------------------------------
        # Create a brand-new opportunity.
        # ------------------------------------------------------------------
        mutation = """
        mutation CreateOpportunities($data: [OpportunityCreateInput!]!, $upsert: Boolean) {
          createOpportunities(data: $data, upsert: $upsert) {
            id
            name
            stage
          }
        }
        """
        variables = {
            "data": [
                {
                    "name": opportunity_name,
                    "stage": stage,
                    "pointOfContactId": lead.twenty_person_id,
                }
            ],
            "upsert": False,
        }

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{settings.twenty_api_url}/graphql",
                headers=_headers(),
                json={"query": mutation, "variables": variables},
            )

        if resp.status_code != 200:
            logger.error(
                "[TWENTY] create opportunity failed HTTP %d for lead_id=%s: %s",
                resp.status_code,
                lead.id,
                resp.text[:300],
            )
            return

        body = resp.json()
        errors = body.get("errors")
        if errors:
            logger.error(
                "[TWENTY] create opportunity GraphQL errors for lead_id=%s: %s",
                lead.id,
                errors,
            )
            return

        records = body.get("data", {}).get("createOpportunities", [])
        if not records:
            logger.warning(
                "[TWENTY] create opportunity returned empty records for lead_id=%s", lead.id
            )
            return

        returned_id = records[0]["id"]
        logger.info(
            "[TWENTY] opportunity created id=%s stage=%s for lead_id=%s",
            returned_id,
            stage,
            lead.id,
        )

        lead.twenty_opportunity_id = returned_id
        await db.commit()

    except Exception:
        logger.exception("[TWENTY] upsert_opportunity unexpected error for lead_id=%s", lead.id)


async def sync_lead(lead: Lead, db: AsyncSession) -> None:
    """
    Full sync of *lead* to Twenty CRM.

    Upserts the Person record first (so the person ID is available), then
    upserts the linked Opportunity.  This is the single call-point that
    state_machine.py uses.
    """
    await upsert_person(lead, db)
    await upsert_opportunity(lead, db)


# ---------------------------------------------------------------------------
# Private helpers (not part of the public API)
# ---------------------------------------------------------------------------

async def _update_opportunity_stage(
    opportunity_id: str, stage: str, lead_id: int
) -> str | None:
    """
    Update the stage on an existing Opportunity by ID.
    Returns the opportunity ID on success, None on failure.
    """
    mutation = """
    mutation CreateOpportunities($data: [OpportunityCreateInput!]!, $upsert: Boolean) {
      createOpportunities(data: $data, upsert: $upsert) {
        id
        name
        stage
      }
    }
    """
    variables = {
        "data": [{"id": opportunity_id, "stage": stage}],
        "upsert": True,
    }

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{settings.twenty_api_url}/graphql",
            headers=_headers(),
            json={"query": mutation, "variables": variables},
        )

    if resp.status_code != 200:
        logger.error(
            "[TWENTY] _update_opportunity_stage failed HTTP %d for lead_id=%s: %s",
            resp.status_code,
            lead_id,
            resp.text[:300],
        )
        return None

    body = resp.json()
    errors = body.get("errors")
    if errors:
        logger.error(
            "[TWENTY] _update_opportunity_stage GraphQL errors for lead_id=%s: %s",
            lead_id,
            errors,
        )
        return None

    records = body.get("data", {}).get("createOpportunities", [])
    if not records:
        return None

    returned_id: str = records[0]["id"]
    logger.info(
        "[TWENTY] opportunity stage updated id=%s stage=%s for lead_id=%s",
        returned_id,
        stage,
        lead_id,
    )
    return returned_id


async def _find_opportunity_for_person(person_id: str, lead_id: int) -> str | None:
    """
    Query Twenty for an Opportunity whose pointOfContact matches *person_id*.
    Returns the opportunity ID if found, None otherwise.
    """
    query = """
    query FindOpportunity($filter: OpportunityFilterInput) {
      opportunities(filter: $filter) {
        edges { node { id name stage } }
      }
    }
    """
    variables = {"filter": {"pointOfContactId": {"eq": person_id}}}

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{settings.twenty_api_url}/graphql",
            headers=_headers(),
            json={"query": query, "variables": variables},
        )

    if resp.status_code != 200:
        logger.error(
            "[TWENTY] _find_opportunity_for_person failed HTTP %d for lead_id=%s: %s",
            resp.status_code,
            lead_id,
            resp.text[:300],
        )
        return None

    body = resp.json()
    errors = body.get("errors")
    if errors:
        logger.error(
            "[TWENTY] _find_opportunity_for_person GraphQL errors for lead_id=%s: %s",
            lead_id,
            errors,
        )
        return None

    edges = body.get("data", {}).get("opportunities", {}).get("edges", [])
    if not edges:
        return None

    existing_id: str = edges[0]["node"]["id"]
    logger.info(
        "[TWENTY] found existing opportunity id=%s for person_id=%s lead_id=%s",
        existing_id,
        person_id,
        lead_id,
    )
    return existing_id
