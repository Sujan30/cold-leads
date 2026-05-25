import logging

from app.ai.client import complete
from app.ai.models import HAIKU
from app.ai.prompts import INTENT_CLASSIFY_PROMPT

logger = logging.getLogger(__name__)

VALID_INTENTS = {
    "interested",
    "not_interested",
    "question",
    "ready_to_book",
    "wrong_number",
    "unclear",
}


async def classify(body: str, context: list[dict] | None = None) -> str:
    if context:
        ctx_lines = "\n".join(
            f"{'Lead' if m['role'] == 'user' else 'Agent'}: {m['content']}"
            for m in context
        )
        ctx_block = f"\nRecent conversation:\n{ctx_lines}\n"
    else:
        ctx_block = ""
    prompt = INTENT_CLASSIFY_PROMPT.format(body=body, context=ctx_block)
    result = await complete(prompt, model=HAIKU, max_tokens=20)
    intent = result.strip().lower().split()[0]
    if intent not in VALID_INTENTS:
        logger.warning("Unexpected intent '%s' — defaulting to unclear", intent)
        return "unclear"
    return intent
