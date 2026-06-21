"""Query expansion and trivial prompt filtering for smarter recall."""

import logging
import re
from typing import Optional

from app.config import settings
from app.llm import get_llm_client

log = logging.getLogger("nexus.search.expand")

_TRIVIAL_PATTERNS = re.compile(
    r"^(ok|yes|no|sure|thanks|thank you|got it|understood|continue|go ahead|"
    r"sounds good|perfect|great|cool|nice|fine|alright|yep|nope|hmm|hm|"
    r"hello|hi|hey|bye|goodbye|please|help|stop|wait|what|huh|lol|lmao|"
    r"/\w+)[\s.!?]*$",
    re.IGNORECASE,
)

_EXPAND_PROMPT = """Given this search query for a memory system, generate 2-3 alternative search phrases that would help find relevant memories. Include synonyms, related concepts, and rephrased versions.

Query: {query}

Return ONLY a comma-separated list of alternative search phrases. No numbering, no explanation."""


def is_trivial_query(query: str) -> bool:
    """Return True if the query carries no semantic signal worth searching for."""
    stripped = query.strip()
    if len(stripped) < 8:
        return True
    if _TRIVIAL_PATTERNS.match(stripped):
        return True
    if stripped.startswith("/"):
        return True
    return False


async def expand_query(query: str) -> str:
    """Expand a query with synonyms and related concepts via LLM.
    Returns the original query augmented with expansion terms."""
    if len(query.strip()) < 15:
        return query

    llm = get_llm_client()
    if not llm:
        return query

    try:
        resp = await llm.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "user", "content": _EXPAND_PROMPT.format(query=query[:300])}],
            max_tokens=80,
            temperature=0.3,
        )
        expansions = (resp.choices[0].message.content or "").strip()
        if expansions:
            return f"{query} {expansions}"
    except Exception as e:
        log.debug("Query expansion failed: %s", e)

    return query
