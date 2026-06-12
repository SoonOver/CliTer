"""Network Scanner — ARP-based local network discovery.

No root required. Uses `arp -a` (built-in) or reads /proc/net/arp.
Runs in Termux without extra dependencies.
"""
import asyncio
import re
from dataclasses import dataclass, field
from typing import Optional
from cliter.utils.log import get_logger

log = get_logger("network")


@dataclass
class NetworkDevice:
    ip: str
    mac: str
    hostname: str = "?"
    vendor: str = "?"
    first_seen: float = 0.0
    last_seen: float = 0.0
    online: bool = True


class NetworkScanner:
    """ARP-based local network scanner. Passive + active modes."""

    # Common OUI prefixes for quick vendor lookup
    OUI_DB: dict[str, str] = {
        "00": "Unknown",
        "08:00": "Intel",
        "00:1A": "Intel",
        "00:1B": "Intel",
        "00:1C": "Intel",
        "00:1E": "Intel",
        "00:21": "Intel",
        "00:24": "Intel",
        "00:26": "Intel",
        "00:50": "Intel",
        "00:0C": "Cisco",
        "00:14": "Cisco",
        "00:1D": "Cisco",
        "00:1F": "Cisco",
        "04:0E": "Cisco",
        "00:25": "Dell",
        "00:26": "Dell",
        "00:23": "Apple",
        "00:1E": "Apple",
        "00:25": "Apple",
        "04:0C": "Apple",
        "28:37": "Apple",
        "34:15": "Apple",
        "70:56": "Apple",
        "B8:5E": "Apple",
        "00:11": "Samsung",
        "00:15": "Samsung",
        "00:21": "Samsung",
        "00:27": "Samsung",
        "BC:F6": "Samsung",
        "E8:50": "Samsung",
        "00:12": "Nokia",
        "00:0E": "Xiaomi",
        "18:FE": "Xiaomi",
        "00:22": "Huawei",
        "04:3C": "Huawei",
        "0C:1D": "Huawei",
        "00:1F": "TP-Link",
        "00:50": "TP-Link",
        "14:CC": "TP-Link",
        "A4:2B": "TP-Link",
        "EC:08": "TP-Link",
        "00:26": "Buffalo",
        "00:24": "Linksys",
        "00:1A": "Netgear",
        "00:0F": "Netgear",
        "C0:3F": "Netgear",
        "30:05": "Google",
        "8C:DE": "Google",
        "A4:77": "Google",
        "A8:9C": "Google",
        "18:8B": "Amazon",
        "AC:63": "Amazon",
        "B0:4E": "Amazon",
        "00:17": "Raspberry Pi",
        "B8:27": "Raspberry Pi",
        "DC:A6": "Raspberry Pi",
        "E4:5F": "Raspberry Pi",
        "00:0A": "Xerox",
        "00:1B": "Roku",
        "00:23": "Sonos",
    }

    def __init__(self):
        self._devices: dict[str, NetworkDevice] = {}
        self._scan_interval = 60  # seconds
        self._running = False
        self._task: asyncio.Task | None = None

    def _oui_lookup(self, mac: str) -> str:
        """Lookup vendor by MAC OUI."""
        mac_upper = mac.upper().replace(":", "")
        for prefix, vendor in sorted(self.OUI_DB.items(), key=lambda x: -len(x[0])):
            p = prefix.replace(":", "").upper()
            if mac_upper.startswith(p):
                return vendor
        return "?"

    def _parse_arp(self, text: str) -> list[dict]:
        """Parse `arp -a` output into device list."""
        devices = []
        for line in text.split("\n"):
            line = line.strip()
            if not line or "incomplete" in line:
                continue
            # Windows:  "192.168.1.1     xx-xx-xx-xx-xx-xx     dynamic"
            m = re.search(r"(\d+\.\d+\.\d+\.\d+)\s+([\da-fA-F:-]{10,})", line)
            if m:
                ip = m.group(1)
                mac = m.group(2).replace("-", ":").upper()
                if len(mac) == 12:
                    mac = ":".join(mac[i:i+2] for i in range(0, 12, 2))
                devices.append({"ip": ip, "mac": mac})
            # Linux: "192.168.1.1   ether   xx:xx:xx:xx:xx:xx   C"
            m2 = re.search(r"(\d+\.\d+\.\d+\.\d+)\s+.*?([\da-fA-F]{2}(?::[\da-fA-F]{2}){5})", line)
            if m2 and not m:
                devices.append({"ip": m2.group(1), "mac": m2.group(2).upper()})
        return devices

    async def scan(self) -> list[NetworkDevice]:
        """Run ARP scan and return device list."""
        import time
        now = time.time()
        text = ""
        try:
            proc = await asyncio.create_subprocess_shell(
                "arp -a",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            text = stdout.decode("utf-8", errors="replace")
        except Exception:
            # Try reading /proc/net/arp on Linux
            try:
                import aiofiles
                text = await aiofiles.open("/proc/net/arp").read()
            except Exception:
                pass

        raw = self._parse_arp(text)
        for d in raw:
            ip = d["ip"]
            mac = d["mac"]
            if ip in self._devices:
                self._devices[ip].last_seen = now
                self._devices[ip].online = True
            else:
                self._devices[ip] = NetworkDevice(
                    ip=ip, mac=mac,
                    vendor=self._oui_lookup(mac),
                    first_seen=now, last_seen=now,
                )

        # Mark devices not seen this scan as offline
        for dev in self._devices.values():
            if dev.last_seen < now - 5:
                dev.online = False

        return list(self._devices.values())

    @property
    def devices(self) -> list[NetworkDevice]:
        return sorted(self._devices.values(), key=lambda d: d.ip)

    async def start(self, interval: int = 60):
        self._scan_interval = interval
        self._running = True
        self._task = asyncio.create_task(self._loop())
        log.info("Network scanner started")

    def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        log.info("Network scanner stopped")

    async def _loop(self):
        # Do an immediate scan
        await self.scan()
        while self._running:
            await asyncio.sleep(self._scan_interval)
            try:
                await self.scan()
            except Exception:
                pass

    @property
    def status(self) -> dict:
        return {
            "running": self._running,
            "devices": len(self._devices),
            "online": sum(1 for d in self._devices.values() if d.online),
        }


# Global singleton
_scanner: NetworkScanner | None = None


def get_scanner() -> NetworkScanner:
    global _scanner
    if _scanner is None:
        _scanner = NetworkScanner()
    return _scanner
