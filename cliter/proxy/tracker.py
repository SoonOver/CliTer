"""Token usage & rate-limit tracker — SQLite backed."""
import json, time, asyncio
import aiosqlite
from cliter.utils.paths import db_path
from cliter.utils.log import get_logger

log = get_logger("tracker")

DB = str(db_path())
RATE_LIMIT_COOLDOWN = 30  # seconds to wait after 429 before retrying

async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS usage_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider_id TEXT,
                connection_id TEXT,
                model TEXT,
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                cost REAL DEFAULT 0,
                status TEXT DEFAULT 'ok',
                timestamp REAL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS daily_budget (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT UNIQUE NOT NULL,
                tokens_used INTEGER DEFAULT 0,
                budget_limit INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS rate_limits (
                connection_id TEXT PRIMARY KEY,
                cooldown_until REAL DEFAULT 0,
                consecutive_429 INTEGER DEFAULT 0,
                last_429 REAL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS provider_reliability (
                provider_id TEXT PRIMARY KEY,
                total_requests INTEGER DEFAULT 0,
                successful INTEGER DEFAULT 0,
                failed INTEGER DEFAULT 0,
                total_latency_ms REAL DEFAULT 0,
                last_success REAL,
                last_failure REAL
            )
        """)
        await db.commit()

# ── Log usage ──────────────────────────────────────────

async def log_usage(provider_id: str, connection_id: str, model: str,
                    prompt_tokens: int = 0, completion_tokens: int = 0,
                    status: str = "ok"):
    now = time.time()
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT INTO usage_log (provider_id, connection_id, model, prompt_tokens, completion_tokens, status, timestamp) VALUES (?,?,?,?,?,?,?)",
            (provider_id, connection_id, model, prompt_tokens, completion_tokens, status, now)
        )
        # Update daily budget
        date = time.strftime("%Y-%m-%d")
        await db.execute(
            "INSERT INTO daily_budget (date, tokens_used) VALUES (?, ?) ON CONFLICT(date) DO UPDATE SET tokens_used = tokens_used + ?",
            (date, prompt_tokens + completion_tokens, prompt_tokens + completion_tokens)
        )
        await db.commit()

# ── Rate limit tracking ───────────────────────────────

async def record_429(connection_id: str):
    now = time.time()
    async with aiosqlite.connect(DB) as db:
        existing = await db.execute(
            "SELECT consecutive_429 FROM rate_limits WHERE connection_id = ?",
            (connection_id,)
        )
        row = await existing.fetchone()
        consec = (row[0] if row else 0) + 1
        cooldown = RATE_LIMIT_COOLDOWN * min(consec, 5)  # max 5x multiplier = 150s
        await db.execute(
            "INSERT INTO rate_limits (connection_id, cooldown_until, consecutive_429, last_429) VALUES (?, ?, ?, ?) ON CONFLICT(connection_id) DO UPDATE SET cooldown_until=?, consecutive_429=?, last_429=?",
            (connection_id, now + cooldown, consec, now, now + cooldown, consec, now)
        )
        await db.commit()
        return cooldown

async def record_success(connection_id: str):
    """Reset rate-limit counter on successful request."""
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "UPDATE rate_limits SET consecutive_429 = 0, cooldown_until = 0 WHERE connection_id = ?",
            (connection_id,)
        )
        await db.commit()

async def is_rate_limited(connection_id: str) -> bool:
    """Check if connection is in cooldown."""
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute(
            "SELECT cooldown_until FROM rate_limits WHERE connection_id = ? AND cooldown_until > ?",
            (connection_id, time.time())
        )
        row = await cur.fetchone()
        return row is not None

async def get_available_connections(connection_ids: list[str]) -> list[str]:
    """Return connection IDs that are NOT rate-limited."""
    available = []
    for cid in connection_ids:
        if not await is_rate_limited(cid):
            available.append(cid)
    return available

# ── Budget ─────────────────────────────────────────────

async def set_budget(tokens: int):
    """Set daily budget limit."""
    date = time.strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT INTO daily_budget (date, budget_limit) VALUES (?, ?) ON CONFLICT(date) DO UPDATE SET budget_limit = ?",
            (date, tokens, tokens)
        )
        await db.commit()

async def get_budget() -> dict:
    date = time.strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute(
            "SELECT tokens_used, budget_limit FROM daily_budget WHERE date = ?",
            (date,)
        )
        row = await cur.fetchone()
        if row:
            return {"date": date, "used": row[0], "limit": row[1] or 0}
        return {"date": date, "used": 0, "limit": 0}

async def set_budget(limit: int):
    """Set daily budget limit (0 = unlimited)."""
    date = time.strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT INTO daily_budget (date, tokens_used, budget_limit) VALUES (?, 0, ?) ON CONFLICT(date) DO UPDATE SET budget_limit = ?",
            (date, limit, limit)
        )
        await db.commit()

async def get_usage_summary(days: int = 7) -> list[dict]:
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        cutoff = time.time() - days * 86400
        cur = await db.execute(
            "SELECT provider_id, model, COUNT(*) as requests, SUM(prompt_tokens) as prompt, SUM(completion_tokens) as completion, SUM(cost) as cost FROM usage_log WHERE timestamp > ? GROUP BY provider_id, model ORDER BY cost DESC",
            (cutoff,)
        )
        return [dict(r) for r in await cur.fetchall()]


# ── Reliability tracking ──────────────────────────

async def record_success_latency(provider_id: str, latency_ms: float):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            """INSERT INTO provider_reliability (provider_id, total_requests, successful, total_latency_ms, last_success)
               VALUES (?, 1, 1, ?, ?)
               ON CONFLICT(provider_id) DO UPDATE SET
               total_requests = total_requests + 1,
               successful = successful + 1,
               total_latency_ms = total_latency_ms + ?,
               last_success = ?""",
            (provider_id, latency_ms, time.time(), latency_ms, time.time())
        )
        await db.commit()

async def record_failure(provider_id: str):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            """INSERT INTO provider_reliability (provider_id, total_requests, failed, last_failure)
               VALUES (?, 1, 1, ?)
               ON CONFLICT(provider_id) DO UPDATE SET
               total_requests = total_requests + 1,
               failed = failed + 1,
               last_failure = ?""",
            (provider_id, time.time(), time.time())
        )
        await db.commit()

async def get_reliability(provider_id: str) -> dict:
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM provider_reliability WHERE provider_id = ?",
            (provider_id,)
        )
        row = await cur.fetchone()
        if row:
            d = dict(row)
            total = d["total_requests"] or 1
            d["success_rate"] = round(d["successful"] / total * 100, 1)
            d["avg_latency_ms"] = round(d["total_latency_ms"] / total, 0) if d["total_requests"] > 0 else 0
            return d
        return {
            "provider_id": provider_id,
            "total_requests": 0,
            "successful": 0,
            "failed": 0,
            "success_rate": 100.0,
            "avg_latency_ms": 0,
        }

async def get_reliabilities() -> list[dict]:
    """Get reliability for all providers, sorted by success_rate desc, latency asc."""
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM provider_reliability ORDER BY successful * 1.0 / total_requests DESC, total_latency_ms * 1.0 / total_requests ASC")
        rows = await cur.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            total = max(d["total_requests"], 1)
            d["success_rate"] = round(d["successful"] / total * 100, 1)
            d["avg_latency_ms"] = round(d["total_latency_ms"] / total, 0) if d["total_requests"] > 0 else 0
            result.append(d)
        return result
