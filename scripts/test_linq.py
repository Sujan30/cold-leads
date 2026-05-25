"""Phase 1 smoke test: send a text via Linq and wait for webhook reply."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.channels.linq import linq


async def main():
    to = input("Enter your phone number (E.164, e.g. +14155550100): ").strip()
    print(f"Sending test message to {to}...")
    result = await linq.send(to, "Hey — this is a test from the lead agent. Reply anything!")
    print("Sent:", result)
    await linq.aclose()


if __name__ == "__main__":
    asyncio.run(main())
