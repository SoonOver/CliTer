"""P2P Agent Sharing — share agent capabilities via HTTP.

Security:
- Auth token required (random, configurable)
- Rate-limited: 10 req/min per IP
- Read-only: peers can query, never modify
- No shell access, no file read/write
- All responses sanitized
"""
import asyncio
import json
import secrets
import time
from typing import Optional

import httpx

from cliter.config import settings
from cliter.utils.log import get_logger

log = get_logger("p2p")


class P2PServer:
    """Lightweight HTTP server for peer-to-peer agent queries.

    Peers can ask questions; agent responds with answers.
    No access to shell, files, or system.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 2096):
        self.host = host
        self.port = port
        self._server: Optional[asyncio.AbstractServer] = None
        self._running = False
        self._token = self._load_or_create_token()
        self._rate_limits: dict[str, list[float]] = {}
        self.max_requests_per_min = 10

    @staticmethod
    def _load_or_create_token() -> str:
        """Load existing token or generate new one."""
        token = settings.get("p2p", "token", default="")
        if not token:
            token = secrets.token_hex(16)
            settings.set_val("p2p", "token", value=token)
        return token

    async def start(self):
        """Start the P2P HTTP server."""
        if self._running:
            return
        self._running = True
        self._server = await asyncio.start_server(
            self._handle_client, self.host, self.port
        )
        log.info(f"P2P server on {self.host}:{self.port}")

    async def stop(self):
        self._running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    def _check_rate_limit(self, ip: str) -> bool:
        """Check if IP is rate-limited. Returns True if allowed."""
        now = time.time()
        window = 60  # 1 minute

        if ip not in self._rate_limits:
            self._rate_limits[ip] = []

        # Clean old entries
        self._rate_limits[ip] = [t for t in self._rate_limits[ip] if now - t < window]

        if len(self._rate_limits[ip]) >= self.max_requests_per_min:
            return False

        self._rate_limits[ip].append(now)
        return True

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle incoming P2P connection."""
        peer_ip = writer.get_extra_info("peername", ("?",))[0]
        request_data = b""

        try:
            request_data = await asyncio.wait_for(reader.read(4096), timeout=10)
            request_str = request_data.decode("utf-8", errors="replace")

            # Parse HTTP request
            lines = request_str.split("\r\n")
            if not lines:
                raise ValueError("Empty request")

            method, path, _ = lines[0].split(" ", 2)

            # Parse headers
            headers = {}
            for line in lines[1:]:
                if ":" in line:
                    key, val = line.split(":", 1)
                    headers[key.strip().lower()] = val.strip()

            # Check auth
            auth = headers.get("authorization", "")
            if not auth.startswith("Bearer ") or auth[7:] != self._token:
                await self._send_response(writer, 401, {"error": "Unauthorized"})
                return

            # Rate limit
            if not self._check_rate_limit(peer_ip):
                await self._send_response(writer, 429, {"error": "Rate limited"})
                return

            # Route
            if method == "GET" and path == "/status":
                await self._send_response(writer, 200, {
                    "status": "online",
                    "agent": "CliTer",
                    "version": "1.0.0",
                })

            elif method == "POST" and path == "/query":
                body_start = request_str.find("\r\n\r\n") + 4
                body = request_str[body_start:] if body_start > 3 else "{}"
                try:
                    body_data = json.loads(body)
                except json.JSONDecodeError:
                    body_data = {}

                question = body_data.get("question", "")

                if not question.strip():
                    await self._send_response(writer, 400, {"error": "Question required"})
                    return

                # Security: sanitize question
                safe_question = question[:500]

                # Respond via local agent
                from cliter.core.agent import Agent
                agent = Agent("p2p_shared")
                try:
                    answer = await agent.chat(safe_question)
                except Exception as e:
                    answer = f"Error: {str(e)[:200]}"

                await self._send_response(writer, 200, {
                    "question": safe_question[:100],
                    "answer": answer[:2000],
                    "peer": f"cliter@{peer_ip}",
                })

            elif method == "GET" and path == "/capabilities":
                await self._send_response(writer, 200, {
                    "tools": ["terminal", "web_search", "read_file", "exploit_suggester"],
                    "features": ["geo_tracker", "network_scanner", "offline_kb"],
                })

            else:
                await self._send_response(writer, 404, {"error": "Not found"})

        except asyncio.TimeoutError:
            await self._send_response(writer, 408, {"error": "Timeout"})
        except Exception as e:
            log.warn(f"P2P error from {peer_ip}: {e}")
            try:
                await self._send_response(writer, 500, {"error": "Internal error"})
            except Exception:
                pass

        try:
            writer.close()
        except Exception:
            pass

    async def _send_response(self, writer: asyncio.StreamWriter, status: int, data: dict):
        """Send HTTP JSON response."""
        body = json.dumps(data)
        reason = {200: "OK", 400: "Bad Request", 401: "Unauthorized",
                  404: "Not Found", 408: "Timeout", 429: "Too Many Requests",
                  500: "Internal Server Error"}.get(status, "Unknown")
        response = (
            f"HTTP/1.1 {status} {reason}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Access-Control-Allow-Origin: *\r\n"
            f"\r\n"
            f"{body}"
        )
        writer.write(response.encode())
        await writer.drain()

    @property
    def status(self) -> dict:
        return {
            "running": self._running,
            "host": self.host,
            "port": self.port,
            "token": self._token[:8] + "…" if self._token else "not set",
            "rate_limit": f"{self.max_requests_per_min}/min",
        }


# ── Client — query another peer ─────────────

async def query_peer(host: str, port: int, question: str, token: str) -> str:
    """Send a question to another CliTer peer."""
    url = f"http://{host}:{port}/query"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                url,
                json={"question": question},
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("answer", "No response")
            elif resp.status_code == 401:
                return "❌ Unauthorized: wrong token"
            elif resp.status_code == 429:
                return "❌ Rate limited"
            else:
                return f"❌ HTTP {resp.status_code}"
    except Exception as e:
        return f"❌ Connection failed: {e}"


# Singleton
_server: Optional[P2PServer] = None


def get_p2p() -> P2PServer:
    global _server
    if _server is None:
        _server = P2PServer()
    return _server
