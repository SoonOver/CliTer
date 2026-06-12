"""Context Compactor — smart conversation summarization.

When conversations exceed a threshold, old messages are summarized
and replaced with a compact summary. Preserves memories and skills.
"""
import json
import time
from cliter.llm import get_provider
from cliter.llm.base import Message
from cliter.core import session
from cliter.config import settings

COMPACTOR_PROMPT = """Summarize the following conversation concisely.
Keep: decisions, key facts, code snippets, error messages, tool results.
Drop: greetings, pleasantries, trivial acknowledgments.
Output a dense bullet list (max 10 bullets)."""


class ContextCompactor:
    """Compresses long conversation history to stay within context limits."""

    def __init__(self, threshold: int = 30, target_count: int = 15):
        self.threshold = threshold  # messages before compaction triggers
        self.target_count = target_count  # messages to keep after compaction
        self.provider = get_provider()

    async def check_and_compact(self, session_id: str) -> bool:
        """Check message count and compact if needed. Returns True if compacted."""
        msgs = await session.get_messages(session_id, limit=100)
        if len(msgs) < self.threshold:
            return False

        # Keep the most recent target_count messages
        keep = msgs[-self.target_count:]
        compact_candidates = msgs[:-self.target_count]

        if not compact_candidates:
            return False

        # Summarize old messages
        summary = await self._summarize(compact_candidates)
        if not summary:
            return False

        # Delete old messages from DB and insert summary
        # We mark the summary as a system message
        first_id = compact_candidates[0]["id"]
        last_id = compact_candidates[-1]["id"]

        import aiosqlite
        from cliter.utils.paths import db_path

        db = str(db_path())
        async with aiosqlite.connect(db) as conn:
            # Delete the old messages
            await conn.execute(
                "DELETE FROM messages WHERE session_id = ? AND id BETWEEN ? AND ?",
                (session_id, first_id, last_id)
            )
            # Insert summary as a system message
            await conn.execute(
                "INSERT INTO messages (session_id, role, content, tool_calls, tool_call_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, "system", f"[Context compacted — {len(compact_candidates)} older messages summarized]\n{summary}", "[]", "", time.time())
            )
            await conn.commit()

        return True

    async def _summarize(self, messages: list[dict]) -> str:
        """Summarize a list of messages."""
        # Build text to summarize
        lines = []
        for m in messages:
            role = m.get("role", "?")
            content = m.get("content", "")
            if content:
                # Truncate very long messages
                if len(content) > 500:
                    content = content[:500] + "..."
                lines.append(f"[{role}] {content}")

        if not lines:
            return ""

        text = "\n".join(lines)
        if len(text) > 8000:
            text = text[:8000] + "\n... (truncated)"

        try:
            resp = await self.provider.chat([
                Message(role="system", content=COMPACTOR_PROMPT),
                Message(role="user", content=text),
            ])
            return resp.content.strip() or "Conversation summarized (no key points extracted)"
        except Exception as e:
            return f"[Summary unavailable: {e}]"
