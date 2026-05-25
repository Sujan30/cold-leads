"""Seeds the dev lead for local testing."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.database import AsyncSessionLocal
from app.models.follow_up import FollowUp
from app.models.lead import Lead, LeadChannel, LeadState, LeadTemperature
from app.models.message import Message
from sqlalchemy import delete


async def seed():
    async with AsyncSessionLocal() as db:
        await db.execute(delete(FollowUp))
        await db.execute(delete(Message))
        await db.execute(delete(Lead))

        leads = [
            Lead(
            name="Sujan Nandikol Sunilkumar",
            phone="+19259676795",
            email="nandikolsujan@gmail.com",
            source="test",
            property_interest="Looking to buy in San Jose, Communication Hills, 5 bed 4 bath, budget 1.7M",
            temperature=LeadTemperature.hot_inbound,
            state=LeadState.new,
            channel=LeadChannel.text,
            consent_verified=True,    
            ),
            Lead(
            name="Yashi Rajan", 
            phone="+19253182956",
            email="sujan.nandikolsunilkumar@sjsu.edu",
            source='test',
            property_interest="Looking to purchase a house in Mountain View, 3 bed 2 bath minimum",
            temperature=LeadTemperature.hot_inbound,
            state=LeadState.new,
            channel=LeadChannel.text,
            consent_verified=True

            )
        ]
        
        for lead in leads:
            db.add(lead)
            print(f"added {lead.name} phone number: {lead.phone} to db")
        
        await db.commit()

        
        


if __name__ == "__main__":
    asyncio.run(seed())
