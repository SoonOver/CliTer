"""Agent Evolution Timeline — show agent development history from git log.

Reads the project's git log and maps commits to skill/system additions.
Security: local only, reads .git directory, no network.
"""
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from cliter.utils.paths import project_dir
from cliter.utils.log import get_logger

log = get_logger("timeline")


class TimelineEntry:
    def __init__(self, sha: str, date: str, message: str):
        self.sha = sha[:7]
        self.date = date
        self.message = message
        self.tags: list[str] = []

    def __repr__(self):
        return f"[{self.sha}] {self.date} {self.message[:50]}"


def get_timeline(limit: int = 30) -> list[TimelineEntry]:
    """Read git log and extract timeline entries."""
    repo_path = project_dir()
    if not (repo_path / ".git").exists():
        return []

    try:
        result = subprocess.run(
            ["git", "log", f"--max-count={limit}", "--format=%H|%ai|%s"],
            capture_output=True, text=True, timeout=10,
            cwd=str(repo_path),
        )
        if result.returncode != 0:
            return []

        entries = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("|", 2)
            if len(parts) == 3:
                entry = TimelineEntry(parts[0], parts[1], parts[2])
                entry.tags = _categorize(parts[2])
                entries.append(entry)
        return entries

    except Exception as e:
        log.warn(f"Timeline failed: {e}")
        return []


def _categorize(message: str) -> list[str]:
    """Categorize a commit message into feature tags."""
    msg = message.lower()
    tags = []

    # Strict security filter — timeline only shows feature categories
    if "feat" in msg or "feature" in msg or "new" in msg:
        pass  # Core feature

    if "search" in msg or "search_bar" in msg:
        tags.append("🔍 Search")
    if "toast" in msg or "notif" in msg:
        tags.append("🔔 Toast")
    if "memory" in msg:
        tags.append("🧠 Memory")
    if "network" in msg or "scanner" in msg or "net_" in msg:
        tags.append("📡 Network")
    if "provider" in msg or "toggle" in msg:
        tags.append("🔌 Provider")
    if "sync" in msg:
        tags.append("🔄 Sync")
    if "exploit" in msg or "cve" in msg:
        tags.append("🔥 Exploit")
    if "kb" in msg or "knowledge" in msg or "offline" in msg:
        tags.append("📚 KB")
    if "timeline" in msg or "evolution" in msg:
        tags.append("📊 Timeline")
    if "geo" in msg or "tracker" in msg or "location" in msg:
        tags.append("📍 Geo")
    if "planner" in msg:
        tags.append("🤖 Planner")
    if "export" in msg or "import" in msg:
        tags.append("💾 Export")
    if "session" in msg and "switch" in msg:
        tags.append("🔄 Session")
    if "action" in msg or "button" in msg:
        tags.append("⚡ Action")
    if "dashboard" in msg or "status" in msg:
        tags.append("📊 UI")
    if "proxy" in msg:
        tags.append("🌐 Proxy")
    if "termux" in msg:
        tags.append("📱 Termux")
    if "p2p" in msg or "share" in msg or "peer" in msg:
        tags.append("🔗 P2P")
    if "init" in msg or "initial" in msg:
        tags.append("🚀 Init")

    if not tags:
        tags.append("🔧 Improvement")

    return tags


def format_timeline(limit: int = 20) -> str:
    """Format timeline as rich text for TUI display."""
    entries = get_timeline(limit)
    if not entries:
        return "No git history found. Init project first."

    lines = ["📊 **Agent Evolution Timeline**", ""]
    current_date = ""

    for entry in entries:
        # Date header
        day = entry.date[:10]
        if day != current_date:
            current_date = day
            lines.append(f"  __{day}__")

        # Entry
        tags_str = " ".join(entry.tags) if entry.tags else ""
        msg_clean = entry.message[:80]
        lines.append(f"    {entry.sha} │ {msg_clean} {tags_str}")

    stats = _compute_stats()
    lines.append("")
    lines.append(f"  **Stats:** {stats['total_commits']} commits, {stats['features']} features, "
                 f"{stats['contributors']} contributor(s)")
    return "\n".join(lines)


def _compute_stats() -> dict:
    """Compute simple stats from git log."""
    try:
        repo_path = project_dir()
        total = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            capture_output=True, text=True, timeout=5, cwd=str(repo_path),
        )
        authors = subprocess.run(
            ["git", "shortlog", "-sn"],
            capture_output=True, text=True, timeout=5, cwd=str(repo_path),
        )
        return {
            "total_commits": total.stdout.strip(),
            "features": len(get_timeline(20)),
            "contributors": len([l for l in authors.stdout.split("\n") if l.strip()]),
        }
    except Exception:
        return {"total_commits": "?", "features": 0, "contributors": "?"}
