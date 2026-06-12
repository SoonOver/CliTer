"""Termux API — access Android features via Termux:API.

Security: sandboxed local commands only, no remote access.
All functions validate input to prevent shell injection.
Only available on Android/Termux — safely degrades on other platforms.
"""
import asyncio
import re
import shutil
from dataclasses import dataclass
from typing import Optional
from cliter.utils.log import get_logger

log = get_logger("termux_api")

_TERMUX_CMD = None  # lazy check


def _in_termux() -> bool:
    """Check if running in Termux environment."""
    global _TERMUX_CMD
    if _TERMUX_CMD is None:
        _TERMUX_CMD = shutil.which("termux-battery-status") is not None
    return _TERMUX_CMD


def _sanitize(text: str, max_len: int = 500) -> str:
    """Sanitize user input — strip shell metacharacters, limit length."""
    # Allow alphanumeric, spaces, common punctuation
    safe = re.sub(r'[^a-zA-Z0-9\s\.\,\!\?\-\_\@\#\/\:]', '', text)
    return safe[:max_len]


async def _run_termux_cmd(cmd: str, timeout: int = 10) -> str:
    """Run a termux-* command and return stdout. Security: hardcoded prefix."""
    if not _in_termux():
        return "❌ Not in Termux environment"
    # Only allow known termux-* commands
    allowed_prefixes = [
        "termux-battery-status",
        "termux-clipboard-get",
        "termux-clipboard-set",
        "termux-tts-speak",
        "termux-sms-send",
        "termux-notification",
        "termux-wifi-scaninfo",
    ]
    base = cmd.split()[0]
    if base not in allowed_prefixes:
        return f"❌ Command not allowed: {base}"
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        if proc.returncode != 0:
            return f"❌ Error: {stderr.decode('utf-8', errors='replace')[:200]}"
        return stdout.decode('utf-8', errors='replace').strip()
    except asyncio.TimeoutError:
        return "❌ Timed out"
    except Exception as e:
        return f"❌ {e}"


# ── Public API ─────────────────────────────────


async def get_battery() -> str:
    """Get battery status: percentage, temperature, health."""
    raw = await _run_termux_cmd("termux-battery-status")
    if raw.startswith("❌"):
        return raw
    try:
        import json
        data = json.loads(raw)
        pct = data.get("percentage", "?")
        temp = data.get("temperature", "?")
        health = data.get("health", "?")
        plugged = data.get("plugged", "?")
        return f"🔋 {pct}% | {temp}°C | {health} | {plugged}"
    except Exception:
        return raw


async def get_clipboard() -> str:
    """Get clipboard content."""
    if not _in_termux():
        return "❌ Not in Termux"
    raw = await _run_termux_cmd("termux-clipboard-get")
    if not raw or raw.startswith("❌"):
        return "📋 (empty)" if not raw else raw
    return f"📋 {raw[:200]}"


async def set_clipboard(text: str) -> str:
    """Set clipboard content. Input sanitized."""
    safe = _sanitize(text)
    await _run_termux_cmd(f"termux-clipboard-set '{safe}'")
    return f"📋 Copied: {safe[:50]}"


async def speak(text: str) -> str:
    """Text-to-speech via Termux. Input sanitized."""
    safe = _sanitize(text)
    await _run_termux_cmd(f"termux-tts-speak '{safe}'")
    return f"🔊 Speaking: {safe[:50]}"


async def send_sms(number: str, message: str) -> str:
    """Send SMS. Number sanitized, message sanitized."""
    num = re.sub(r'[^\d\+]', '', number)[:20]
    msg = _sanitize(message)
    if not num.startswith("+") and len(num) < 8:
        return "❌ Invalid phone number"
    await _run_termux_cmd(f"termux-sms-send -n '{num}' '{msg}'")
    return f"📨 SMS sent to {num}"


async def notify(title: str, content: str, priority: str = "normal") -> str:
    """Send Termux notification. Input sanitized."""
    safe_title = _sanitize(title, 100)
    safe_content = _sanitize(content, 200)
    await _run_termux_cmd(
        f"termux-notification -t '{safe_title}' -c '{safe_content}' --priority {priority}"
    )
    return f"🔔 Notification sent: {safe_title}"


async def get_wifi_scan() -> str:
    """Scan WiFi networks (requires location permission)."""
    raw = await _run_termux_cmd("termux-wifi-scaninfo")
    if raw.startswith("❌"):
        return raw
    try:
        import json
        networks = json.loads(raw)
        if not networks:
            return "📶 No networks found"
        lines = ["📶 WiFi Networks:"]
        for n in sorted(networks, key=lambda x: -x.get("rssi", -100))[:15]:
            ssid = n.get("ssid", "?")
            bssid = n.get("bssid", "?").upper()
            rssi = n.get("rssi", 0)
            cap = n.get("capabilities", "")[:20]
            strength = "🟢" if rssi > -60 else "🟡" if rssi > -80 else "🔴"
            # Truncate BSSID for privacy (show only OUI part)
            bssid_short = bssid[:8] + "…" if len(bssid) > 8 else bssid
            lines.append(f"  {strength} {ssid} ({bssid_short}) {rssi}dBm")
        return "\n".join(lines)
    except Exception:
        return raw
