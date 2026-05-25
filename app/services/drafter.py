import logging

from app.ai.client import complete, complete_with_history
from app.ai.models import HAIKU, SONNET
from app.ai.prompts import (
    FIRST_TOUCH_EMAIL_PROMPT,
    FIRST_TOUCH_TEXT_PROMPT,
    REPLY_PROMPT,
)
from app.config import settings

logger = logging.getLogger(__name__)


async def draft_first_touch_text(name: str, property_interest: str = "") -> str:
    prompt = FIRST_TOUCH_TEXT_PROMPT.format(
        name=name,
        agent_name=settings.agents_name,
        property_interest=property_interest or "real estate in the Bay Area",
    )
    return await complete(prompt, model=HAIKU)


async def draft_first_touch_email(name: str, property_interest: str = "") -> tuple[str, str]:
    """Returns (subject, body)."""
    prompt = FIRST_TOUCH_EMAIL_PROMPT.format(
        name=name,
        agent_name=settings.agents_name,
        property_interest=property_interest or "real estate in the Bay Area",
    )
    result = await complete(prompt, model=HAIKU, max_tokens=600)
    lines = result.strip().splitlines()
    subject = lines[0].replace("Subject:", "").strip() if lines else "Quick question"
    body = "\n".join(lines[2:]).strip() if len(lines) > 2 else result
    return subject, body


async def draft_reply(
    name: str,
    history: list[dict],
    latest_message: str,
    use_sonnet: bool = False,
) -> str:
    model = SONNET if use_sonnet else HAIKU
    history_text = "\n".join(
        f"{'Lead' if t['role'] == 'user' else 'Agent'}: {t['content']}"
        for t in history
    )
    prompt = REPLY_PROMPT.format(
        name=name,
        agent_name=settings.agents_name,
        history=history_text or "(no prior messages)",
        latest=latest_message,
    )
    full_history = [
        {"role": "user", "content": f"Lead name: {name}\nConversation history:\n{history_text}"},
        {"role": "assistant", "content": "Got it. I'll craft a reply."},
        {"role": "user", "content": f"Their latest: {latest_message}\nWrite the reply:"},
    ]
    return await complete_with_history(full_history, model=model)
