"""Multi-Device Sync — sync sessions, memory, providers across devices via GitHub.

Security:
- GitHub token stored in config, never in code
- All data encrypted in transit (HTTPS)
- No API keys uploaded (filtered before sync)
- Rate-limited: max 1 sync per minute
"""
import json
import time
import asyncio
import base64
from typing import Optional

import httpx

from cliter.config import settings
from cliter.core import memory, session
from cliter.proxy import manager as proxy_mgr
from cliter.utils.log import get_logger

log = get_logger("sync")

SYNC_GIST_FILENAME = "cliter-sync.json"
SYNC_GIST_DESC = "🔄 CliTer Multi-Device Sync"
MIN_SYNC_INTERVAL = 60  # seconds


class SyncService:
    """Push/pull state to GitHub gist for cross-device sync."""

    def __init__(self):
        self._gist_id: Optional[str] = None
        self._last_sync = 0

    # ── Auth ──────────────────────────────────

    @property
    def _token(self) -> str:
        return settings.get("github", "token", default="")

    @property
    def _headers(self) -> dict:
        return {
            "Authorization": f"token {self._token}",
            "Accept": "application/vnd.github.v3+json",
        }

    def is_configured(self) -> bool:
        return bool(self._token)

    # ── Gist management ───────────────────────

    async def _find_gist(self) -> Optional[str]:
        """Find existing sync gist."""
        if not self.is_configured():
            return None
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    "https://api.github.com/gists", headers=self._headers
                )
                for g in resp.json():
                    if SYNC_GIST_FILENAME in g.get("files", {}):
                        return g["id"]
        except Exception:
            pass
        return None

    async def _ensure_gist(self) -> Optional[str]:
        """Get or create sync gist."""
        if self._gist_id:
            return self._gist_id
        self._gist_id = await self._find_gist()
        return self._gist_id

    # ── Build sync data (filtered) ───────────

    async def _build_payload(self) -> dict:
        """Build sync payload. API keys filtered out, user data only."""
        # Sessions — recent 20
        sessions_list = await session.list_sessions(limit=20)
        sessions_data = []
        for s in sessions_list:
            msgs = await session.get_messages(s["id"])
            sessions_data.append({
                "id": s["id"],
                "title": s.get("title", ""),
                "messages": [{"role": m["role"], "content": m["content"]} for m in msgs],
            })

        # Memories — all
        memories = await memory.list_all()
        memories_data = [{"category": m["category"], "content": m["content"]} for m in memories]

        # Providers — names only (no API keys!)
        providers = await proxy_mgr.list_providers()
        provider_names = [p["name"] for p in providers if p.get("is_active")]

        return {
            "version": "1",
            "synced_at": time.time(),
            "device": settings.get("device", "name", default="unknown"),
            "sessions": sessions_data,
            "memories": memories_data,
            "active_providers": provider_names,
        }

    # ── Push ──────────────────────────────────

    async def push(self) -> str:
        """Push current state to sync gist."""
        if not self.is_configured():
            return "❌ GitHub token not configured. Set via `/config github.token <token>`"

        # Rate limit
        if time.time() - self._last_sync < MIN_SYNC_INTERVAL:
            remaining = int(MIN_SYNC_INTERVAL - (time.time() - self._last_sync))
            return f"⏳ Rate limited. Wait {remaining}s"

        payload = await self._build_payload()
        content = json.dumps(payload, indent=2)
        files = {SYNC_GIST_FILENAME: {"content": content}}

        gist_id = await self._ensure_gist()
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                if gist_id:
                    resp = await client.patch(
                        f"https://api.github.com/gists/{gist_id}",
                        json={"files": files}, headers=self._headers
                    )
                else:
                    resp = await client.post(
                        "https://api.github.com/gists",
                        json={"description": SYNC_GIST_DESC, "public": False, "files": files},
                        headers=self._headers,
                    )
                    if resp.status_code == 201:
                        self._gist_id = resp.json().get("id")

                if resp.status_code in (200, 201):
                    self._last_sync = time.time()
                    dev = payload["device"]
                    size_kb = len(content) // 1024
                    return f"✅ Synced from {dev} ({size_kb}KB)"
                return f"❌ Sync failed: HTTP {resp.status_code}"

        except Exception as e:
            return f"❌ Sync failed: {e}"

    # ── Pull ──────────────────────────────────

    async def pull(self) -> str:
        """Pull state from sync gist and apply locally."""
        gist_id = await self._ensure_gist()
        if not gist_id:
            return "❌ No sync gist found. Push first from another device."

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"https://api.github.com/gists/{gist_id}",
                    headers=self._headers
                )
                if resp.status_code != 200:
                    return f"❌ Pull failed: HTTP {resp.status_code}"

                data = resp.json()
                content = data["files"][SYNC_GIST_FILENAME]["content"]
                payload = json.loads(content)

                # Import memories
                mem_count = 0
                for m in payload.get("memories", []):
                    await memory.add(content=m["content"], category=m["category"])
                    mem_count += 1

                # Import sessions
                sess_count = 0
                for s in payload.get("sessions", []):
                    exists = await session.get_messages(s["id"])
                    if not exists:
                        await session.create_session(s["id"], s.get("title", "Synced"))
                        for msg in s.get("messages", []):
                            await session.add_message(s["id"], msg["role"], msg["content"])
                        sess_count += 1

                self._last_sync = time.time()
                dev = payload.get("device", "unknown")
                return (
                    f"✅ Pulled from {dev}\n"
                    f"  Memories: {mem_count} imported\n"
                    f"  Sessions: {sess_count} imported\n"
                    f"  Active: {len(payload.get('active_providers', []))} providers"
                )

        except Exception as e:
            return f"❌ Pull failed: {e}"

    @property
    def status(self) -> dict:
        return {
            "configured": self.is_configured(),
            "gist_id": self._gist_id,
            "last_sync": self._last_sync,
        }


# Singleton
_service: Optional[SyncService] = None


def get_sync() -> SyncService:
    global _service
    if _service is None:
        _service = SyncService()
    return _service
