"""Export/Import system — backup and restore CliTer state.

Can export: providers, config, sessions, skills, memories.
Creates portable JSON files for sharing between instances.
"""
import json
import time
from pathlib import Path
from cliter.proxy import manager as pm
from cliter.core import session, memory
from cliter.config import settings
from cliter.skills.loader import list_skills
from cliter.utils.paths import home_dir

EXPORT_DIR = home_dir() / "exports"


class Exporter:
    """Backup and restore CliTer state."""

    @staticmethod
    def _ensure_dir():
        EXPORT_DIR.mkdir(exist_ok=True)

    @staticmethod
    def _timestamp() -> str:
        return time.strftime("%Y%m%d_%H%M%S")

    async def export_all(self, label: str = "") -> str:
        """Export everything: providers, config, skills, sessions, memories."""
        self._ensure_dir()
        ts = self._timestamp()
        safe_label = "".join(c for c in label if c.isalnum() or c in "-_").strip() if label else ""
        suffix = f"_{safe_label}" if safe_label else ""
        filename = f"cliter_backup_{ts}{suffix}.json"
        path = EXPORT_DIR / filename

        data = {
            "exported_at": ts,
            "label": label or "full_backup",
            "cliter_version": settings.get("app", "version", default="1.0.0"),
            "providers": await self.export_providers(),
            "config": self.export_config(),
            "skills": self.export_skills(),
            "sessions": await self.export_sessions(),
            "memories": await self.export_memories(),
        }

        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        return str(path)

    async def export_providers(self) -> list[dict]:
        """Export all proxy providers (keys included)."""
        providers = await pm.list_providers()
        # Remove internal fields, keep config-relevant ones
        clean = []
        for p in providers:
            clean.append({
                "name": p.get("name"),
                "prefix": p.get("prefix"),
                "base_url": p.get("base_url"),
                "api_key": p.get("api_key", ""),
                "models": p.get("models", "[]"),
                "priority": p.get("priority", 0),
                "is_active": bool(p.get("is_active")),
            })
        return clean

    def export_config(self) -> dict:
        """Export settings."""
        return dict(settings._config) if settings._config else {}

    def export_skills(self) -> list[dict]:
        """Export all skills from ~/.cliter/skills/."""
        skills = list_skills()
        return [{
            "name": s.get("name"),
            "content": s.get("content"),
            "description": s.get("description", ""),
            "metadata": s.get("metadata", {}),
        } for s in skills]

    async def export_sessions(self) -> list[dict]:
        """Export session metadata (not full messages — can be huge)."""
        sessions = await session.list_sessions(limit=50)
        return [{
            "id": s.get("id"),
            "title": s.get("title"),
            "created_at": s.get("created_at"),
            "updated_at": s.get("updated_at"),
        } for s in sessions]

    async def export_memories(self) -> list[dict]:
        """Export all memories."""
        mems = await memory.list_all()
        return [{"category": m.get("category"), "content": m.get("content")} for m in mems]

    async def import_file(self, path: str) -> str:
        """Import from a backup JSON file."""
        p = Path(path)
        if not p.exists():
            return f"ERROR: file not found: {path}"

        data = json.loads(p.read_text(encoding="utf-8"))
        report = []

        # Import providers
        providers = data.get("providers", [])
        if providers:
            from cliter.proxy import manager as npm
            await npm.init_db()
            count = 0
            for prov in providers:
                try:
                    existing = await npm.get_provider(prov.get("prefix"))
                    if existing:
                        # Update
                        import aiosqlite
                        from cliter.proxy.manager import DB
                        async with aiosqlite.connect(DB) as db:
                            await db.execute(
                                "UPDATE proxy_providers SET base_url=?, api_key=?, models=?, priority=?, is_active=? WHERE prefix=?",
                                (prov.get("base_url"), prov.get("api_key"),
                                 json.dumps(prov.get("models", [])), prov.get("priority", 5),
                                 int(prov.get("is_active", True)), prov.get("prefix"))
                            )
                            await db.commit()
                    else:
                        await npm.add_provider(
                            name=prov.get("name", prov.get("prefix")),
                            prefix=prov.get("prefix"),
                            base_url=prov.get("base_url"),
                            api_key=prov.get("api_key", ""),
                            models=prov.get("models", []),
                            priority=prov.get("priority", 5),
                        )
                    count += 1
                except Exception as e:
                    report.append(f"  [warn] Provider {prov.get('name')}: {e}")
            report.append(f"  Providers: {count} imported/updated")

        # Import config
        config_data = data.get("config", {})
        if config_data:
            for key, value in config_data.items():
                settings._config[key] = value
            settings.save_user()
            report.append(f"  Config: {len(config_data)} sections imported")

        # Import skills
        skills = data.get("skills", [])
        if skills:
            from cliter.skills.manager import create_skill
            count = 0
            for sk in skills:
                try:
                    name = sk.get("name", "")
                    if name:
                        create_skill(name, sk.get("content", ""), sk.get("description", ""))
                        count += 1
                except Exception as e:
                    report.append(f"  [warn] Skill {sk.get('name')}: {e}")
            report.append(f"  Skills: {count} imported")

        # Import memories
        mems = data.get("memories", [])
        if mems:
            count = 0
            for m in mems:
                await memory.add(m.get("content", ""), m.get("category", "imported"))
                count += 1
            report.append(f"  Memories: {count} imported")

        return "\n".join(report) if report else "Nothing to import."

    @staticmethod
    def list_exports() -> list[dict]:
        """List available backup files."""
        EXPORT_DIR.mkdir(exist_ok=True)
        files = []
        for f in sorted(EXPORT_DIR.glob("cliter_backup_*.json"), reverse=True):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                files.append({
                    "path": str(f),
                    "label": data.get("label", "?"),
                    "exported_at": data.get("exported_at", "?"),
                    "size": f.stat().st_size,
                })
            except Exception:
                files.append({"path": str(f), "label": "corrupt", "size": f.stat().st_size})
        return files
