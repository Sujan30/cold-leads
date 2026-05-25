import zoneinfo
from datetime import datetime

import anthropic

from app.ai.models import HAIKU, SONNET
from app.ai.prompts import build_system_block
from app.config import settings

_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)


def _system_blocks() -> list[dict]:
    pt = zoneinfo.ZoneInfo("America/Los_Angeles")
    now_str = datetime.now(pt).strftime("%A, %B %-d, %Y at %-I:%M %p %Z")
    return [
        {
            "type": "text",
            "text": build_system_block(settings.agents_name),
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": f"Current date and time: {now_str}",
        },
    ]


async def complete(prompt: str, model: str = HAIKU, max_tokens: int = 512) -> str:
    """Single-turn completion with cached system prompt."""
    response = await _client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=_system_blocks(),
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


async def complete_with_history(
    history: list[dict],
    model: str = HAIKU,
    max_tokens: int = 512,
) -> str:
    """Multi-turn completion. History is a list of {role, content} dicts.
    The first message gets cache_control so repeated lead histories hit cache."""
    messages = []
    for i, turn in enumerate(history):
        if i == 0 and turn["role"] == "user":
            messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": turn["content"],
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            })
        else:
            messages.append(turn)

    response = await _client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=_system_blocks(),
        messages=messages,
    )
    return response.content[0].text.strip()
