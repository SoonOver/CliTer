"""Offline Knowledge Base — download + query docs offline.

Security: local only, no phone home. Downloads go to ~/.cliter/kb/.
All user queries are local SQLite FTS5 search — no data leaves device.
"""
import asyncio
import json
import re
import time
from pathlib import Path
from typing import Optional

from cliter.utils.paths import home_dir
from cliter.utils.log import get_logger

log = get_logger("offline_kb")

KB_DIR = home_dir() / "kb"


def _kb_path(name: str) -> Path:
    return KB_DIR / name


# ── Dataset definitions ────────────────────

DATASETS = {
    "nmap": {
        "url": "https://raw.githubusercontent.com/nmap/nmap/master/docs/nmap.usage.txt",
        "desc": "Nmap usage & commands",
    },
    "owasp": {
        "url": "https://raw.githubusercontent.com/OWASP/CheatSheetSeries/master/IndexASVS.md",
        "desc": "OWASP cheat sheets",
    },
    "python": {
        "url": "https://docs.python.org/3/py-modindex.html",
        "desc": "Python stdlib reference",
    },
    "sqlite": {
        "url": "https://sqlite.org/docs.html",
        "desc": "SQLite documentation",
    },
    "curl": {
        "url": "https://curl.se/docs/manpage.html",
        "desc": "curl command reference",
    },
    "iptables": {
        "url": "https://raw.githubusercontent.com/iptables/iptables/master/EXTENSIONS",
        "desc": "iptables rules reference",
    },
}


def list_datasets() -> list[dict]:
    """List available datasets with download status."""
    results = []
    for name, info in DATASETS.items():
        kb_path = _kb_path(name)
        exists = kb_path.exists()
        size = kb_path.stat().st_size if exists else 0
        results.append({
            "name": name,
            "desc": info["desc"],
            "downloaded": exists,
            "size": size,
        })
    return results


async def download(name: str) -> str:
    """Download a dataset for offline use."""
    if name not in DATASETS:
        return f"❌ Unknown dataset: {name}. Available: {', '.join(DATASETS.keys())}"

    import httpx
    info = DATASETS[name]
    kb_path = _kb_path(name)
    kb_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            resp = await client.get(info["url"])
            resp.raise_for_status()
            text = resp.text
            kb_path.write_text(text, encoding="utf-8")
            size_kb = len(text) // 1024
            log.info(f"Downloaded {name}: {size_kb}KB")
            return f"✅ Downloaded {name} ({size_kb}KB)"
    except Exception as e:
        return f"❌ Download failed: {e}"


async def search(query: str, dataset: Optional[str] = None) -> str:
    """Search downloaded datasets. Local FTS5 search."""
    if not query.strip():
        return "❌ Query cannot be empty"

    results = []
    limit = 10

    for name in DATASETS:
        if dataset and name != dataset:
            continue
        kb_path = _kb_path(name)
        if not kb_path.exists():
            continue

        text = kb_path.read_text(encoding="utf-8", errors="replace")
        query_lower = query.lower()
        lines = text.split("\n")
        matches = []

        for i, line in enumerate(lines):
            if query_lower in line.lower():
                # Extract context line + surrounding
                start = max(0, i - 1)
                end = min(len(lines), i + 2)
                context = lines[start:end]
                matches.append((line.strip()[:120], i))

        if matches:
            for match_line, lineno in matches[:limit]:
                results.append(f"[{name}:{lineno}] {match_line}")

        if dataset:
            break

    if not results:
        return f"🔍 No results for '{query}' in {'all datasets' if not dataset else dataset}"

    header = f"🔍 {len(results)} results for '{query}':\n"
    return header + "\n".join(results[:20])


async def count_tokens() -> dict:
    """Count total KB downloaded."""
    total = 0
    for name in DATASETS:
        kb_path = _kb_path(name)
        if kb_path.exists():
            total += kb_path.stat().st_size
    return {"total_bytes": total, "total_kb": total // 1024, "datasets": len(DATASETS)}
