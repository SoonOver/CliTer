"""Provider management for CliTer proxy — SQLite backed."""
import json, time, uuid
import aiosqlite
from cliter.utils.paths import db_path

DB = str(db_path())

async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS proxy_providers (
                id TEXT PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                prefix TEXT UNIQUE NOT NULL,
                base_url TEXT NOT NULL,
                api_key TEXT DEFAULT '',
                models TEXT DEFAULT '[]',
                priority INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                created_at REAL,
                updated_at REAL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS proxy_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        await db.commit()

async def add_provider(name: str, prefix: str, base_url: str, api_key: str = "",
                       models: list = None, priority: int = 0) -> dict:
    pid = f"prov-{uuid.uuid4().hex[:12]}"
    now = time.time()
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT INTO proxy_providers (id, name, prefix, base_url, api_key, models, priority, is_active, created_at, updated_at) VALUES (?,?,?,?,?,?,?,1,?,?)",
            (pid, name, prefix, base_url, api_key, json.dumps(models or []), priority, now, now)
        )
        await db.commit()
    return {"id": pid, "name": name, "prefix": prefix}

async def remove_provider(ident: str) -> bool:
    """Remove by name or prefix or id."""
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("DELETE FROM proxy_providers WHERE name=? OR prefix=? OR id=?", (ident, ident, ident))
        await db.commit()
        return cur.rowcount > 0

async def list_providers() -> list[dict]:
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM proxy_providers ORDER BY priority DESC, name ASC")
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

async def get_provider(ident: str) -> dict | None:
    """Get by prefix first, then name, then id."""
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        for field in ("prefix", "name", "id"):
            cur = await db.execute(f"SELECT * FROM proxy_providers WHERE {field}=?", (ident,))
            row = await cur.fetchone()
            if row:
                return dict(row)
    return None

async def set_default(name: str = ""):
    """Set default provider by name. Empty = no default."""
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT OR REPLACE INTO proxy_settings (key, value) VALUES ('default_provider', ?)", (name,))
        await db.commit()

async def get_default() -> str:
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT value FROM proxy_settings WHERE key='default_provider'")
        row = await cur.fetchone()
        return row[0] if row else ""

async def set_config(key: str, value: str):
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT OR REPLACE INTO proxy_settings (key, value) VALUES (?,?)", (key, value))
        await db.commit()

async def get_config(key: str, default: str = "") -> str:
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT value FROM proxy_settings WHERE key=?", (key,))
        row = await cur.fetchone()
        return row[0] if row else default

async def set_model_aliases(aliases: dict):
    """Store model prefix aliases as JSON (e.g. {'gh': '1', 'gitlawb': 'chat/completions'})"""
    await set_config("model_aliases", json.dumps(aliases))

async def get_model_aliases() -> dict:
    raw = await get_config("model_aliases", "{}")
    return json.loads(raw)

async def get_all_models() -> list[str]:
    """Return all models from all active providers, e.g. ['kr/gpt-4o', 'gitlawb/claude-3']"""
    models = []
    providers = await list_providers()
    for p in providers:
        if not p["is_active"]:
            continue
        prefix = p["prefix"]
        prov_models = json.loads(p.get("models", "[]"))
        if prov_models:
            for m in prov_models:
                models.append(f"{prefix}/{m}")
        else:
            # wildcard — just show prefix entry
            models.append(prefix)
    return models

async def set_provider_models(name: str, models: list[str]):
    async with aiosqlite.connect(DB) as db:
        await db.execute("UPDATE proxy_providers SET models=?, updated_at=? WHERE name=?",
                         (json.dumps(models), time.time(), name))
        await db.commit()

async def set_api_key(name: str, api_key: str):
    """Set API key for a provider by name."""
    async with aiosqlite.connect(DB) as db:
        await db.execute("UPDATE proxy_providers SET api_key=?, updated_at=? WHERE name=?",
                         (api_key, time.time(), name))
        await db.commit()
        return db.total_changes > 0

async def set_active(provider_id: str, active: bool):
    """Enable or disable a provider by ID."""
    async with aiosqlite.connect(DB) as db:
        await db.execute("UPDATE proxy_providers SET is_active=?, updated_at=? WHERE id=?",
                         (1 if active else 0, time.time(), provider_id))
        await db.commit()

async def get_provider_by_id(provider_id: str) -> dict | None:
    """Get a single provider by ID."""
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM proxy_providers WHERE id=?", (provider_id,))
        row = await cur.fetchone()
        return dict(row) if row else None

async def delete_provider(provider_id: str) -> bool:
    """Delete a provider by ID."""
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("DELETE FROM proxy_providers WHERE id=?", (provider_id,))
        await db.commit()
        return cur.rowcount > 0
