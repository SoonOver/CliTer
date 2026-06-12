"""Session / conversation manager — SQLite backed."""
import json, time
import aiosqlite
from cliter.utils.paths import db_path

DB = str(db_path())

async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT DEFAULT 'New Chat',
                created_at REAL,
                updated_at REAL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT DEFAULT '',
                tool_calls TEXT DEFAULT '[]',
                tool_call_id TEXT DEFAULT '',
                created_at REAL,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_msg_session ON messages(session_id)")
        await db.commit()

async def create_session(session_id: str, title: str = "New Chat") -> str:
    now = time.time()
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                         (session_id, title, now, now))
        await db.commit()
    return session_id

async def list_sessions(limit: int = 20) -> list[dict]:
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?", (limit,))
        return [dict(r) for r in await cur.fetchall()]

async def rename_session(session_id: str, title: str):
    async with aiosqlite.connect(DB) as db:
        await db.execute("UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?", (title, time.time(), session_id))
        await db.commit()

async def delete_session(session_id: str):
    async with aiosqlite.connect(DB) as db:
        await db.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        await db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        await db.commit()

async def add_message(session_id: str, role: str, content: str = "", tool_calls: list = None, tool_call_id: str = ""):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT INTO messages (session_id, role, content, tool_calls, tool_call_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, role, content, json.dumps(tool_calls or []), tool_call_id, time.time())
        )
        await db.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (time.time(), session_id))
        await db.commit()

async def get_messages(session_id: str, limit: int = 50) -> list[dict]:
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at ASC LIMIT ?",
            (session_id, limit)
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

async def search_messages(query: str) -> list[dict]:
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT m.*, s.title FROM messages m JOIN sessions s ON m.session_id = s.id WHERE m.content LIKE ? ORDER BY m.created_at DESC LIMIT 20",
            (f"%{query}%",)
        )
        return [dict(r) for r in await cur.fetchall()]
