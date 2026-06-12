"""Persistent memory — SQLite backed."""
import aiosqlite
from cliter.utils.paths import db_path

DB = str(db_path())

async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT DEFAULT 'general',
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()

async def add(content: str, category: str = "general") -> int:
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("INSERT INTO memories (category, content) VALUES (?, ?)", (category, content))
        await db.commit()
        return cur.lastrowid

async def remove(memory_id: int):
    async with aiosqlite.connect(DB) as db:
        await db.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        await db.commit()

async def list_all(category: str = None) -> list[dict]:
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        if category:
            cur = await db.execute("SELECT * FROM memories WHERE category = ? ORDER BY created_at DESC", (category,))
        else:
            cur = await db.execute("SELECT * FROM memories ORDER BY created_at DESC")
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

async def search(query: str) -> list[dict]:
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM memories WHERE content LIKE ? ORDER BY created_at DESC", (f"%{query}%",))
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

async def get_context() -> str:
    """Get all memories as context string for system prompt."""
    mems = await list_all()
    if not mems:
        return ""
    lines = ["[Memories]"]
    for m in mems[:30]:  # cap at 30
        lines.append(f"- [{m['category']}] {m['content']}")
    return "\n".join(lines)
