"""Chat history helper — wraps session messages into LLM Message objects."""
import json
from cliter.llm.base import Message
from cliter.core import session

async def get_llm_messages(session_id: str, limit: int = 50) -> list[Message]:
    rows = await session.get_messages(session_id, limit)
    msgs = []
    for r in rows:
        m = Message(
            role=r["role"],
            content=r["content"],
            tool_calls=json.loads(r["tool_calls"]) if r["tool_calls"] else [],
            tool_call_id=r["tool_call_id"] or None,
        )
        msgs.append(m)
    return msgs
